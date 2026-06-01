#!/usr/bin/env python3
"""Print project metadata check failures with schema YAML locations."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import duckdb
import yaml

FailureRow = tuple[str, str, str | None, str, str]

RED = "31"
GREEN = "32"
RESET = "\033[0m"
RULE_LABELS = {
    "model_description": "model description",
    "column_description": "column description",
    "primary_key": "primary key",
    "indexed_columns": "indexed columns",
}


class LineLoader(yaml.SafeLoader):
    pass


def construct_mapping(loader: LineLoader, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=deep)
    mapping["__line__"] = node.start_mark.line + 1
    return mapping


LineLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)


def load_schema_locations(project_dir: Path) -> tuple[dict[str, tuple[str, int]], dict[tuple[str, str], tuple[str, int]]]:
    model_locations: dict[str, tuple[str, int]] = {}
    column_locations: dict[tuple[str, str], tuple[str, int]] = {}

    schema_paths = sorted(project_dir.glob("models/**/*.yml")) + sorted(
        project_dir.glob("models/**/*.yaml")
    )
    for path in schema_paths:
        with path.open() as schema_file:
            schema_data = yaml.load(schema_file, Loader=LineLoader) or {}

        for model in schema_data.get("models") or []:
            if not isinstance(model, dict) or "name" not in model:
                continue

            model_name = str(model["name"])
            model_locations[model_name] = (str(path), int(model.get("__line__", 1)))

            for column in model.get("columns") or []:
                if not isinstance(column, dict) or "name" not in column:
                    continue
                column_locations[(model_name, str(column["name"]))] = (
                    str(path),
                    int(column.get("__line__", model.get("__line__", 1))),
                )

    return model_locations, column_locations


def location_for(
    model_name: str,
    column_name: str | None,
    model_locations: dict[str, tuple[str, int]],
    column_locations: dict[tuple[str, str], tuple[str, int]],
) -> str:
    if column_name:
        location = column_locations.get((model_name, column_name))
        if location:
            return f"{location[0]}:{location[1]}"

    location = model_locations.get(model_name)
    if location:
        return f"{location[0]}:{location[1]}"
    return "schema YAML not found"


def should_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("CLICOLOR_FORCE") not in (None, "", "0"):
        return True
    if os.environ.get("FORCE_COLOR") not in (None, "", "0"):
        return True
    return sys.stdout.isatty()


def colorize(value: str, color: str, enabled: bool) -> str:
    if not enabled:
        return value
    return f"\033[{color}m{value}{RESET}"


def status_line(status: str, color: str, rule: str, target: str, yaml_location: str, use_color: bool) -> str:
    padded_status = f"{status:<6}"
    styled_status = colorize(padded_status, color, use_color)
    label = RULE_LABELS.get(rule, rule.replace("_", " "))
    location_suffix = f" ({yaml_location})" if yaml_location else ""
    return f"    {styled_status} [metadata] test  {label:<18} {target}{location_suffix}"


def failure_rows(index_dir: Path, policy_path: Path, package_name: str) -> list[FailureRow]:
    con = duckdb.connect()
    nodes = str(index_dir / "dbt.nodes.parquet")
    columns = str(index_dir / "dbt.node_columns.parquet")
    test_metadata = str(index_dir / "dbt.test_metadata.parquet")

    return con.execute(
        """
        with policy as (
            select * from read_json_auto(?)
        ),

        tests as (
            select
                attached_node as unique_id,
                test_name,
                coalesce(test_namespace, '') as test_namespace,
                column_name
            from read_parquet(?)
            where attached_node is not null
        ),

        column_pk_tests as (
            select
                unique_id,
                column_name,
                bool_or(test_name = 'unique') as has_unique_test,
                bool_or(test_name = 'not_null') as has_not_null_test
            from tests
            where column_name is not null
            group by 1, 2
        ),

        single_column_pk_tests as (
            select
                unique_id,
                list(column_name order by column_name)
                    filter (where has_unique_test and has_not_null_test) as unique_not_null_columns,
                list(column_name order by column_name)
                    filter (where has_unique_test) as unique_columns,
                list(column_name order by column_name)
                    filter (where has_not_null_test) as not_null_columns
            from column_pk_tests
            group by 1
        ),

        model_pk_tests as (
            select
                unique_id,
                bool_or(
                    test_name = 'unique_combination_of_columns'
                    and test_namespace in ('dbt_utils', '')
                ) as has_dbt_utils_compound_unique_test,
                bool_or(
                    test_name = 'expect_compound_columns_to_be_unique'
                    and test_namespace in ('dbt_expectations', '')
                ) as has_dbt_expectations_compound_unique_test
            from tests
            group by 1
        ),

        model_description_failures as (
            select
                'model_description' as rule,
                nodes.name as model_name,
                cast(null as varchar) as column_name,
                nodes.original_file_path,
                'Add a non-empty model description.' as fix
            from read_parquet(?) as nodes
            inner join policy
                on nodes.unique_id = policy.unique_id
            where nodes.resource_type = 'model'
              and nodes.enabled
              and nodes.package_name = ?
              and coalesce(policy.require_model_description, false)
              and nullif(trim(nodes.description), '') is null
        ),

        column_description_failures as (
            select
                'column_description' as rule,
                nodes.name as model_name,
                columns.column_name,
                nodes.original_file_path,
                'Add a non-empty column description.' as fix
            from read_parquet(?) as nodes
            inner join policy
                on nodes.unique_id = policy.unique_id
            inner join read_parquet(?) as columns
                on nodes.unique_id = columns.unique_id
            where nodes.resource_type = 'model'
              and nodes.enabled
              and nodes.package_name = ?
              and coalesce(policy.require_column_descriptions, false)
              and nullif(trim(columns.description), '') is null
        ),

        primary_key_failures as (
            select
                'primary_key' as rule,
                nodes.name as model_name,
                cast(null as varchar) as column_name,
                nodes.original_file_path,
                'Add an accepted PK test: unique+not_null on one column, dbt_utils.unique_combination_of_columns, or dbt_expectations.expect_compound_columns_to_be_unique.' as fix
            from read_parquet(?) as nodes
            inner join policy
                on nodes.unique_id = policy.unique_id
            left join single_column_pk_tests
                on nodes.unique_id = single_column_pk_tests.unique_id
            left join model_pk_tests
                on nodes.unique_id = model_pk_tests.unique_id
            where nodes.resource_type = 'model'
              and nodes.enabled
              and nodes.package_name = ?
              and coalesce(policy.require_primary_key_test, false)
              and not (
                  (
                      coalesce(policy.allow_unique, false)
                      and case
                          when coalesce(policy.single_column_unique_requires_not_null, true)
                              then coalesce(array_length(single_column_pk_tests.unique_not_null_columns), 0) > 0
                          else coalesce(array_length(single_column_pk_tests.unique_columns), 0) > 0
                      end
                  )
                  or (
                      coalesce(policy.allow_dbt_utils_unique_combination_of_columns, false)
                      and coalesce(model_pk_tests.has_dbt_utils_compound_unique_test, false)
                  )
                  or (
                      coalesce(policy.allow_dbt_expectations_expect_compound_columns_to_be_unique, false)
                      and coalesce(model_pk_tests.has_dbt_expectations_compound_unique_test, false)
                  )
              )
        ),

        indexed_column_failures as (
            select
                'indexed_columns' as rule,
                nodes.name as model_name,
                cast(null as varchar) as column_name,
                nodes.original_file_path,
                'Ensure the model has indexed columns in the Fusion metadata index.' as fix
            from read_parquet(?) as nodes
            inner join policy
                on nodes.unique_id = policy.unique_id
            left join read_parquet(?) as columns
                on nodes.unique_id = columns.unique_id
            where nodes.resource_type = 'model'
              and nodes.enabled
              and nodes.package_name = ?
              and coalesce(policy.require_indexed_columns, false)
            group by 1, 2, 3, 4, 5
            having count(columns.column_name) = 0
        )

        select * from model_description_failures
        union all
        select * from column_description_failures
        union all
        select * from primary_key_failures
        union all
        select * from indexed_column_failures
        order by rule, model_name, column_name
        """,
        [
            str(policy_path),
            test_metadata,
            nodes,
            package_name,
            nodes,
            columns,
            package_name,
            nodes,
            package_name,
            nodes,
            columns,
            package_name,
        ],
    ).fetchall()


def policy_rows(policy_path: Path) -> list[tuple[Any, ...]]:
    return duckdb.connect().execute(
        """
        select
            model_name,
            require_model_description,
            require_column_descriptions,
            require_primary_key_test,
            require_indexed_columns
        from read_json_auto(?)
        order by model_name
        """,
        [str(policy_path)],
    ).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--policy-path", required=True)
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    model_locations, column_locations = load_schema_locations(project_dir)
    rows = failure_rows(Path(args.index_dir), Path(args.policy_path), args.package_name)
    use_color = should_color()

    if not rows:
        print(status_line("Passed", GREEN, "metadata", "project metadata checks", "", use_color))
        return

    print("")
    for rule, model_name, column_name, _original_file_path, fix in rows:
        target = f"{model_name}.{column_name}" if column_name else model_name
        yaml_location = location_for(model_name, column_name, model_locations, column_locations)
        print(status_line("Failed", RED, rule, target, yaml_location, use_color))
        if args.verbose:
            print(f"      fix: {fix}")

    if args.verbose:
        print("")
        print("Resolved metadata policy")
        print("========================")
        for row in policy_rows(Path(args.policy_path)):
            model_name, model_desc, column_desc, pk_test, indexed_columns = row
            print(
                f"- {model_name}: model_description={model_desc}, "
                f"column_descriptions={column_desc}, "
                f"primary_key_test={pk_test}, indexed_columns={indexed_columns}"
            )


if __name__ == "__main__":
    main()
