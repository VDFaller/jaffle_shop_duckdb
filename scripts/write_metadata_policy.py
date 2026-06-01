#!/usr/bin/env python3
"""Resolve dbt_project.yml metadata check policy into JSON rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

import duckdb
from jinja2 import Environment
import yaml


DEFAULT_PK_TESTS = {
    "unique",
    "dbt_utils.unique_combination_of_columns",
    "dbt_expectations.expect_compound_columns_to_be_unique",
}

CONFIG_PATTERN = re.compile(r"\{\{\s*config\s*\((.*?)\)\s*\}\}", re.DOTALL)


def deep_merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def metadata_checks_from_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}

    config_block = config.get("config") or {}
    config_meta = config_block.get("meta") if isinstance(config_block, dict) else {}
    meta = config.get("+meta") or config.get("meta") or config_meta or {}
    if not isinstance(meta, dict):
        return {}

    policy = meta.get("metadata_checks") or {}
    return policy if isinstance(policy, dict) else {}


def resolved_project_policy(project: dict[str, Any], fqn: list[str]) -> dict[str, Any]:
    if not fqn:
        return {}

    models_config = project.get("models") or {}
    if not isinstance(models_config, dict):
        return {}

    current = models_config.get(fqn[0])
    policy: dict[str, Any] = {}

    if isinstance(current, dict):
        policy = deep_merge(policy, metadata_checks_from_config(current))

    for part in fqn[1:]:
        if not isinstance(current, dict):
            break
        current = current.get(part)
        if isinstance(current, dict):
            policy = deep_merge(policy, metadata_checks_from_config(current))

    return policy


def load_schema_model_policies(project_dir: Path) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    for path in sorted(project_dir.glob("models/**/*.yml")) + sorted(
        project_dir.glob("models/**/*.yaml")
    ):
        with path.open() as schema_file:
            schema_data = yaml.safe_load(schema_file) or {}

        for model in schema_data.get("models") or []:
            if not isinstance(model, dict) or "name" not in model:
                continue

            policy = metadata_checks_from_config(model)
            if policy:
                policies[str(model["name"])] = deep_merge(
                    policies.get(str(model["name"]), {}),
                    policy,
                )

    return policies


def metadata_checks_from_sql(sql: str) -> dict[str, Any]:
    policies: dict[str, Any] = {}
    environment = Environment()

    for match in CONFIG_PATTERN.finditer(sql):
        configs: list[dict[str, Any]] = []

        def capture_config(*_args: Any, **kwargs: Any) -> str:
            configs.append(kwargs)
            return ""

        template = environment.from_string(f"{{{{ config({match.group(1)}) }}}}")
        template.render(config=capture_config)

        for config in configs:
            policies = deep_merge(policies, metadata_checks_from_config(config))

    return policies


def load_sql_model_policies(project_dir: Path) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    for path in sorted(project_dir.glob("models/**/*.sql")):
        policy = metadata_checks_from_sql(path.read_text())
        if policy:
            policies[path.stem] = deep_merge(policies.get(path.stem, {}), policy)
    return policies


def normalize_bool(policy: dict[str, Any], key: str) -> bool:
    return bool(policy.get(key, False))


def normalize_pk_tests(policy: dict[str, Any]) -> set[str]:
    configured = policy.get("primary_key_tests")
    if configured is None:
        return set(DEFAULT_PK_TESTS)
    if not isinstance(configured, list):
        return set()
    return {str(item) for item in configured}


def policy_row(node: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    pk_tests = normalize_pk_tests(policy)
    return {
        "unique_id": node["unique_id"],
        "model_name": node["name"],
        "original_file_path": node["original_file_path"],
        "require_model_description": normalize_bool(policy, "require_model_description"),
        "require_column_descriptions": normalize_bool(policy, "require_column_descriptions"),
        "require_primary_key_test": normalize_bool(policy, "require_primary_key_test"),
        "pk_test_requires_not_null": bool(policy.get("pk_test_requires_not_null", True)),
        "allow_unique": "unique" in pk_tests,
        "allow_dbt_utils_unique_combination_of_columns": (
            "dbt_utils.unique_combination_of_columns" in pk_tests
        ),
        "allow_dbt_expectations_expect_compound_columns_to_be_unique": (
            "dbt_expectations.expect_compound_columns_to_be_unique" in pk_tests
        ),
    }


def load_model_nodes(index_dir: Path, package_name: str) -> list[dict[str, Any]]:
    nodes_path = index_dir / "dbt.nodes.parquet"
    con = duckdb.connect()
    rows = con.execute(
        """
        select unique_id, name, original_file_path, fqn
        from read_parquet(?)
        where resource_type = 'model'
          and enabled
          and package_name = ?
        order by unique_id
        """,
        [str(nodes_path), package_name],
    ).fetchall()

    return [
        {
            "unique_id": unique_id,
            "name": name,
            "original_file_path": original_file_path,
            "fqn": list(fqn),
        }
        for unique_id, name, original_file_path, fqn in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--package-name", required=True)
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    with (project_dir / "dbt_project.yml").open() as project_file:
        project = yaml.safe_load(project_file) or {}

    schema_model_policies = load_schema_model_policies(project_dir)
    sql_model_policies = load_sql_model_policies(project_dir)
    rows = []
    for node in load_model_nodes(Path(args.index_dir), args.package_name):
        policy = resolved_project_policy(project, node["fqn"])
        policy = deep_merge(policy, schema_model_policies.get(node["name"], {}))
        policy = deep_merge(policy, sql_model_policies.get(node["name"], {}))
        rows.append(policy_row(node, policy))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as output_file:
        for row in rows:
            output_file.write(json.dumps(row, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
