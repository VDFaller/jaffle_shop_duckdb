# Project Metadata Checks

This is a companion dbt project for metadata governance. The parent project owns
the policy; this project only enforces it.

To try it, run the pre-commit hook from the repository root:

```shell
uv run pre-commit run -a
```

To run only the metadata check wrapper:

```shell
scripts/check_project_metadata.sh
```

Use `--verbose` when you want fix hints and the resolved policy table:

```shell
scripts/check_project_metadata.sh --verbose
```

## Pattern

- Define metadata expectations in the parent project with
  `meta.metadata_checks`.
- Set broad defaults in `dbt_project.yml`.
- Put model-specific overrides in schema YAML with
  `config.meta.metadata_checks`.
- Keep `metadata_checks` generic so policy changes do not require changing the
  test project.
- Failed checks point back to the schema YAML location to fix.

Example project-level defaults:

```yaml
models:
  jaffle_shop:
    +meta:
      metadata_checks:
        require_model_description: true
        require_column_descriptions: false
        require_primary_key_test: false
        pk_test_requires_not_null: true
    staging:
      +meta:
        metadata_checks:
          require_column_descriptions: true
          require_primary_key_test: true
```

Example model override:

```yaml
models:
  - name: customers
    config:
      meta:
        metadata_checks:
          require_column_descriptions: true
          require_primary_key_test: true
```

## Checks

The current policy can require:

- model descriptions
- column descriptions
- primary-key coverage

Primary-key coverage accepts a single column with both `unique` and `not_null`,
`dbt_utils.unique_combination_of_columns`, or
`dbt_expectations.expect_compound_columns_to_be_unique`.
When `pk_test_requires_not_null` is true, compound PK tests also need `not_null`
coverage for every PK column.
