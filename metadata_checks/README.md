# Project Metadata Checks

This dbt subproject tests the Fusion index written by the parent project. It
only declares the index Parquet files as dbt sources, then runs singular dbt
data tests against those sources. It is intended for fast local/pre-commit
checks that should not query a remote warehouse.

Run the pre-commit wrapper from the repository root:

```shell
scripts/check_project_metadata.sh
```

The wrapper uses Fusion `dbt` for the index-writing compile step, resolves the
metadata policy from the parent project, then runs the DuckDB-backed dbt tests.
If tests fail, it silences Fusion's generic progress output and prints the
specific model or column failures as Fusion-style status lines with schema YAML
locations. Run with `--verbose` to include fix hints and the resolved policy
table:

```shell
scripts/check_project_metadata.sh --verbose
```

Run `dbt system install-drivers` once if Fusion has not cached the DuckDB driver
yet. Set `DBT_METADATA_TEST_ENGINE=core` to run the test step with dbt Core from
`.venv/bin/dbt` or `uv run dbt` instead.

The wrapper writes the index to a fresh temporary target path by default. That
avoids stale index Parquet files passing after a YAML description or test is
removed. Set `DBT_METADATA_FUSION_TARGET_PATH` only when you intentionally want
to inspect or reuse a generated index.

For a manual run, generate both the index and the policy file, then point the
test project at both:

```shell
tmp_target="$(mktemp -d)"
dbt compile --write-index --target-path "$tmp_target" --profiles-dir . --project-dir . --quiet --no-version-check --show none --log-level error
.venv/bin/python scripts/write_metadata_policy.py --project-dir . --index-dir "$tmp_target/index" --output "$tmp_target/metadata_policy.jsonl" --package-name jaffle_shop
dbt test --project-dir metadata_checks/ --profiles-dir metadata_checks/ --select tag:project_metadata_checks --vars "{\"metadata_index_dir\":\"$tmp_target/index\",\"metadata_policy_path\":\"$tmp_target/metadata_policy.jsonl\",\"metadata_project_package\":\"jaffle_shop\"}"
```

Configure policy only in the parent project. The generator resolves project and
folder defaults from `dbt_project.yml`, then merges model-specific overrides from
schema files using `config.meta.metadata_checks`.

```yaml
models:
  jaffle_shop:
    +meta:
      metadata_checks:
        require_model_description: true
        require_column_descriptions: false
        require_primary_key_test: false
        require_indexed_columns: true
        single_column_unique_requires_not_null: true
        primary_key_tests:
          - unique
          - dbt_utils.unique_combination_of_columns
          - dbt_expectations.expect_compound_columns_to_be_unique
    staging:
      +meta:
        metadata_checks:
          require_column_descriptions: true
          require_primary_key_test: true
```

```yaml
# models/schema.yml
models:
  - name: customers
    config:
      meta:
        metadata_checks:
          require_column_descriptions: true
          require_primary_key_test: true
```

The checks currently enforce:

- model descriptions, column descriptions, primary-key coverage, and indexed
  column presence only where the resolved project policy enables each rule

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
