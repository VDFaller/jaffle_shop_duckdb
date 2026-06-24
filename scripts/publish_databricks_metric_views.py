#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml


AGGREGATIONS = {
    "sum": "sum({expr})",
    "count": "count({expr})",
    "count_distinct": "count(distinct {expr})",
    "average": "avg({expr})",
    "avg": "avg({expr})",
    "min": "min({expr})",
    "max": "max({expr})",
}


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as file:
        return yaml.safe_load(file) or {}


def load_json(path: Path) -> dict[str, Any]:
    with path.open() as file:
        return json.load(file)


def quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def dotted_relation(*parts: str) -> str:
    return ".".join(parts)


def yaml_block(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False).strip()


def find_semantic_definitions(paths: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    semantic_models: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []

    for path in paths:
        data = load_yaml(path)
        semantic_models.extend(data.get("semantic_models", []))
        metrics.extend(data.get("metrics", []))

    return semantic_models, metrics


def ref_name(model_ref: str) -> str:
    match = re.fullmatch(r"ref\(['\"]([^'\"]+)['\"]\)", model_ref.strip())
    if not match:
        raise ValueError(f"Expected model ref like ref('orders'), got: {model_ref}")
    return match.group(1)


def model_node(manifest: dict[str, Any], model_name: str) -> dict[str, Any]:
    unique_id = f"model.{manifest['metadata']['project_name']}.{model_name}"
    node = manifest["nodes"].get(unique_id)
    if not node:
        raise KeyError(f"Could not find {unique_id} in target/manifest.json")
    return node


def source_relation(
    manifest: dict[str, Any],
    model_name: str,
    target_catalog: str | None,
    target_schema: str | None,
) -> str:
    node = model_node(manifest, model_name)
    if manifest["metadata"].get("adapter_type") == "databricks":
        return node["relation_name"].replace("`", "")
    if not target_catalog or not target_schema:
        raise ValueError("A Databricks catalog and schema are required when manifest is not Databricks")
    return dotted_relation(target_catalog, target_schema, node["alias"])


def metric_measure(metric: dict[str, Any]) -> str:
    measure = metric["type_params"]["measure"]
    if isinstance(measure, str):
        return measure
    return measure["name"]


def metric_view_name(semantic_model: dict[str, Any]) -> str:
    return f"{semantic_model['name']}_metrics"


def with_optional_description(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    description = source.get("description")
    if description:
        target["comment"] = description
    return target


def build_metric_view(
    semantic_model: dict[str, Any],
    metrics: list[dict[str, Any]],
    manifest: dict[str, Any],
    target_catalog: str | None,
    target_schema: str | None,
) -> tuple[str, str]:
    source = source_relation(manifest, ref_name(semantic_model["model"]), target_catalog, target_schema)
    measures_by_name = {measure["name"]: measure for measure in semantic_model.get("measures", [])}
    view_name = metric_view_name(semantic_model)

    view_parts = []
    if target_catalog:
        view_parts.append(quote_identifier(target_catalog))
    if target_schema:
        view_parts.append(quote_identifier(target_schema))
    view_parts.append(quote_identifier(view_name))
    view_relation = ".".join(view_parts)

    dimensions = []
    for dimension in semantic_model.get("dimensions", []):
        expr = dimension.get("expr", dimension["name"])
        dimensions.append(
            with_optional_description(
                {"name": dimension["name"], "expr": expr},
                dimension,
            )
        )

    databricks_measures = []
    for metric in metrics:
        if metric.get("type") != "simple":
            raise ValueError(f"Only simple metrics are supported by this example bridge: {metric['name']}")
        measure = measures_by_name[metric_measure(metric)]
        agg = measure["agg"]
        if agg not in AGGREGATIONS:
            raise ValueError(f"Unsupported aggregation for Databricks metric view example: {agg}")
        databricks_measures.append(
            with_optional_description(
                {
                    "name": metric["name"],
                    "expr": AGGREGATIONS[agg].format(expr=measure.get("expr", measure["name"])),
                    "display_name": metric.get("label", metric["name"].replace("_", " ").title()),
                },
                metric,
            )
        )

    definition = {
        "version": "1.1",
        "source": source,
        "comment": semantic_model.get("description"),
        "dimensions": dimensions,
        "measures": databricks_measures,
    }

    ddl = (
        f"CREATE OR REPLACE VIEW {view_relation}\n"
        "WITH METRICS\n"
        "LANGUAGE YAML\n"
        "AS $$\n"
        f"{yaml_block(definition)}\n"
        "$$"
    )
    return view_relation, ddl


def profile_target(profile_path: Path, profile_name: str, target_name: str | None) -> dict[str, Any]:
    profiles = load_yaml(profile_path)
    profile = profiles[profile_name]
    target = target_name or profile["target"]
    output = profile["outputs"][target]
    if output.get("type") != "databricks":
        raise ValueError(f"Profile target {profile_name}.{target} is not databricks")
    return output


def warehouse_id(http_path: str) -> str:
    return http_path.rstrip("/").split("/")[-1]


def databricks_request(host: str, token: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://{host.rstrip('/')}{path}"
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Databricks API request failed with HTTP {exc.code}: {body}") from exc


def execute_statement(target: dict[str, Any], statement: str) -> dict[str, Any]:
    response = databricks_request(
        target["host"],
        target["token"],
        "/api/2.0/sql/statements",
        {
            "warehouse_id": warehouse_id(target["http_path"]),
            "catalog": target.get("catalog"),
            "schema": target.get("schema"),
            "statement": statement,
            "wait_timeout": "10s",
        },
    )
    statement_id = response["statement_id"]
    while response["status"]["state"] in {"PENDING", "RUNNING"}:
        time.sleep(2)
        response = databricks_request(target["host"], target["token"], f"/api/2.0/sql/statements/{statement_id}")
    if response["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(json.dumps(response["status"], indent=2))
    return response


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish dbt semantic models as Databricks metric views.")
    parser.add_argument("--semantic-yaml", action="append", type=Path, default=[Path("models/semantic_models.yml")])
    parser.add_argument("--manifest", type=Path, default=Path("target/manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("target/databricks_metric_views.sql"))
    parser.add_argument("--profiles-dir", type=Path, default=Path.home() / ".dbt")
    parser.add_argument("--profile", default="jaffle_shop")
    parser.add_argument("--target", default="dbx")
    parser.add_argument("--catalog")
    parser.add_argument("--schema")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    semantic_models, metrics = find_semantic_definitions(args.semantic_yaml)
    manifest = load_json(args.manifest)
    target = profile_target(args.profiles_dir / "profiles.yml", args.profile, args.target)
    catalog = args.catalog or target.get("catalog")
    schema = args.schema or target.get("schema")

    statements = []
    for semantic_model in semantic_models:
        measure_names = {measure["name"] for measure in semantic_model.get("measures", [])}
        view_metrics = [metric for metric in metrics if metric_measure(metric) in measure_names]
        view_relation, ddl = build_metric_view(semantic_model, view_metrics, manifest, catalog, schema)
        statements.append((view_relation, ddl))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(";\n\n".join(ddl for _, ddl in statements) + ";\n")

    for view_relation, ddl in statements:
        print(f"Wrote {view_relation} to {args.output}")
        if args.apply:
            execute_statement(target, ddl)
            print(f"Published {view_relation}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
