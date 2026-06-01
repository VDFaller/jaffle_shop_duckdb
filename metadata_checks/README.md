# Project Metadata Checks

This dbt subproject tests the Fusion index written by the parent project. It
only declares the index Parquet files as dbt sources, then runs singular dbt
data tests against those sources. It is intended for fast local/pre-commit
checks that should not query a remote warehouse.

Run from the repository root:

```shell
dbt compile --write-index --profiles-dir . --project-dir . --quiet --no-version-check --show none
dbt test --project-dir metadata_checks/ --profiles-dir metadata_checks/
```

Or use the pre-commit wrapper:

```shell
scripts/check_project_metadata.sh
```

The wrapper uses Fusion `dbt` for both the index-writing compile step and the
DuckDB-backed test step. Run `dbt system install-drivers` once if Fusion has not
cached the DuckDB driver yet. Set `DBT_METADATA_TEST_ENGINE=core` to run the test
step with dbt Core from `.venv/bin/dbt` or `uv run dbt` instead.

The wrapper writes the index to a fresh temporary target path by default. That
avoids stale index Parquet files passing after a YAML description or test is
removed. Set `DBT_METADATA_FUSION_TARGET_PATH` only when you intentionally want
to inspect or reuse a generated index.

The checks currently enforce:

- every enabled model has a non-empty description
- every indexed model column has a non-empty description
- every enabled model in the target package has primary-key test coverage
- every enabled model has at least one indexed column, so an empty index does
  not pass silently

Primary-key coverage accepts either:

- a single column with both `unique` and `not_null`
- `dbt_utils.unique_combination_of_columns`
- `dbt_expectations.expect_compound_columns_to_be_unique`

Without licensed strict static analysis, Fusion may only index columns declared
in YAML. In that mode these tests enforce metadata quality for indexed columns,
not complete SQL-output column coverage.

Set `DBT_METADATA_STATIC_ANALYSIS=strict` before the wrapper command if you have
Fusion licensing/authentication available and want the index to include stricter
SQL-derived metadata.
