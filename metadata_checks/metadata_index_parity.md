# Metadata Tool Coverage

This note estimates which existing dbt governance checks can fit the current
metadata-only pattern:

1. run Fusion `dbtf compile --write-index`
2. expose the generated `target/index/dbt.*.parquet` files as dbt sources
3. enforce rules with dbt tests in `metadata_checks`

`dbtf parse --write-index` is accepted by Fusion, but in this local check it
wrote `target/metadata/parse/*/v1_0.parquet`, not the normalized
`target/index/dbt.*.parquet` files. The companion project currently needs
`compile --write-index`.

## Local Index Boundaries

Observed useful compile index tables:

- `dbt.nodes`: resources, paths, descriptions, raw/compiled SQL,
  materialization, access, contracts, tags, source fields
- `dbt.node_columns`: declared/documented columns, descriptions, constraints,
  tags, type fields
- `dbt.test_metadata`: generic test name, namespace, attached node, column,
  kwargs, severity
- `dbt.edges`: parent/child relationships
- `dbt.macros`, `dbt.docs`, `dbt.exposures`, semantic-layer tables, unit tests

Observed gaps:

- Generic test rows point to generated test SQL, not the original schema YAML.
- Model `meta` and `config` were null/empty in the compile index for this
  project, even when SQL `config(meta=...)` existed.
- `node_columns` held documented/declared columns, but local `data_type`,
  `declared_type`, and `inferred_type` were null for the current models.
- File mutation hooks are outside this pattern. We can report failures, but we
  do not rewrite YAML or SQL from a dbt test.

Status meanings:

- `Yes`: the compile index looks rich enough for a dbt-test implementation.
- `Partial`: possible, but needs raw file parsing, stricter Fusion analysis,
  catalog data, or a less exact approximation.
- `No`: not a good fit for this metadata-only pattern today.
- `N/A`: this is a command wrapper or mutator rather than a metadata assertion.

## dbt-project-evaluator

Source: [dbt-project-evaluator rule list](https://dbt-labs.github.io/dbt-project-evaluator/latest/rules/).

| Capability | Upstream rule | Metadata rich enough? | Notes |
| --- | --- | --- | --- |
| Staging models depend on other staging models | `fct_staging_dependent_on_staging` | Yes | Needs edges plus naming/path conventions. |
| Source fanout | `fct_source_fanout` | Yes | Needs source nodes and child counts from `dbt.edges`. |
| Rejoining upstream concepts | `fct_rejoining_of_upstream_concepts` | Yes | Graph-shape rule over direct parent/child edges. |
| Model fanout | `fct_model_fanout` | Yes | Needs child counts and leaf detection from edges. |
| Marts/intermediate models depend directly on sources | `fct_marts_or_intermediate_dependent_on_source` | Yes | Needs edges plus folder/name classification. |
| Direct join to source | `fct_direct_join_to_source` | Yes | Needs models with both model and source parents. |
| Duplicate sources | `fct_duplicate_sources` | Yes | Needs source database/schema/identifier fields. |
| Hard-coded references | `fct_hard_coded_references` | Partial | `raw_code` is present, but exact matching still needs SQL/regex logic and relation-name heuristics. |
| Multiple sources joined | `fct_multiple_sources_joined` | Yes | Needs count of direct source parents. |
| Root models | `fct_root_models` | Yes | Needs models with no model/source parents. |
| Staging models depend on marts/intermediate models | `fct_staging_dependent_on_marts_or_intermediate` | Yes | Needs edges plus folder/name classification. |
| Unused sources | `fct_unused_sources` | Yes | Needs source nodes with no children. |
| Models with too many joins | `fct_too_many_joins` | Yes | Needs direct parent counts. |
| Missing primary-key tests | `fct_missing_primary_key_tests` | Yes | This PoC already covers the core version with `dbt.test_metadata`. |
| Missing source freshness | `fct_sources_without_freshness` | Yes | Source freshness is exposed on source rows in `dbt.nodes`. |
| Test coverage | `fct_test_coverage` | Yes | Needs `dbt.test_metadata` attached to models/sources. |
| Undocumented models | `fct_undocumented_models` | Yes | This PoC already covers model descriptions and can cover columns. |
| Documentation coverage | `fct_documentation_coverage` | Yes | Needs model and column descriptions from `dbt.nodes` and `dbt.node_columns`. |
| Undocumented source tables | `fct_undocumented_source_tables` | Yes | Source table descriptions are exposed on source rows. |
| Undocumented sources | `fct_undocumented_sources` | Yes | Source-level descriptions are exposed on source rows. |
| Test directories | `fct_test_directories` | Partial | Generic test `original_file_path` points to generated SQL, not the schema YAML that defined the test. |
| Model naming conventions | `fct_model_naming_conventions` | Yes | Needs model name and file path. |
| Source directories | `fct_source_directories` | Yes | Needs source name and source original file path. |
| Model directories | `fct_model_directories` | Yes | Needs model path plus source/model lineage. |
| Chained view dependencies | `fct_chained_views_dependencies` | Yes | Needs transitive graph traversal plus materialization. |
| Exposure parent materializations | `fct_exposure_parents_materializations` | Yes | Needs exposures, exposure parents, and parent materialization. |
| Public models without contracts | `fct_public_models_without_contracts` | Yes | Needs access level and contract flag. |
| Exposures dependent on private models | `fct_exposures_dependent_on_private_models` | Yes | Needs exposure parent edges and model access level. |
| Undocumented public models | `fct_undocumented_public_models` | Yes | Needs access level plus model and column descriptions. |

## dbt-checkpoint

Sources:

- [dbt-checkpoint README hook list](https://github.com/dbt-checkpoint/dbt-checkpoint#list-of-dbt-checkpoint-hooks)
- [dbt-checkpoint hook manifest](https://github.com/dbt-checkpoint/dbt-checkpoint/blob/main/.pre-commit-hooks.yaml)

| Capability | Hook | Metadata rich enough? | Notes |
| --- | --- | --- | --- |
| Column descriptions are consistent across models | `check-column-desc-are-same` | Yes | Needs declared column names and descriptions. |
| Column names match a contract | `check-column-name-contract` | Yes | Needs column names and configurable regex/rules. |
| Model columns have descriptions | `check-model-columns-have-desc` | Yes | This PoC already covers the core version. |
| Model columns have required meta keys | `check-model-columns-have-meta-keys` | Partial | Column `meta` exists, but inherited/SQL-configured meta was not reliable in the compile index locally. |
| Model has all columns in properties file | `check-model-has-all-columns` | Partial | Needs actual output/catalog columns. Local index only showed documented columns with null inferred/type fields. |
| Model has mandatory columns with types | `check-model-has-columns-with-types` | Partial | Needs reliable actual or declared types; local type fields were null. |
| Model has contract enforced | `check-model-has-contract` | Yes | `contract_enforced` is available. |
| Model has specific constraints | `check-model-has-constraints` | Yes | `node_constraints` and `column_constraints` are available. |
| Model has generic constraints | `check-model-has-generic-constraints` | Yes | Same metadata as specific constraints. |
| Model has description | `check-model-has-description` | Yes | This PoC already covers it. |
| Model has required meta keys | `check-model-has-meta-keys` | Partial | Model `meta` was null locally even for SQL-configured meta; file parsing is safer. |
| Model has required label keys | `check-model-has-labels-keys` | Partial | Column labels exist, but model-level labels were not observed as a normalized field. |
| Model has a properties file | `check-model-has-properties-file` | Partial | `patch_path` was null locally, so this needs schema YAML discovery. |
| Model has tests by group | `check-model-has-tests-by-group` | Yes | Generic tests are available in `dbt.test_metadata`; group mapping is policy logic. |
| Model has tests by name | `check-model-has-tests-by-name` | Yes | `test_name` and attached model are available. |
| Model has tests by type | `check-model-has-tests-by-type` | Yes | Can infer generic vs singular from test metadata and node resource shape. |
| Model has any tests | `check-model-has-tests` | Yes | Needs attached test counts. |
| Model name matches a contract | `check-model-name-contract` | Yes | Needs model name and configurable regex/rules. |
| Model has parent/child count bounds | `check-model-parents-and-childs` | Yes | Needs `dbt.edges`. |
| Model parents are in allowed databases | `check-model-parents-database` | Yes | Needs parent nodes and database fields. |
| Model parents have required name prefix | `check-model-parents-name-prefix` | Yes | Needs parent node names. |
| Model parents are in allowed schemas | `check-model-parents-schema` | Yes | Needs parent nodes and schema fields. |
| Model has valid tags | `check-model-tags` | Yes | Tags are available on node rows. |
| Materialization matches child-count policy | `check-model-materialization-by-childs` | Yes | Needs materialization plus child counts. |
| SQL does not end with semicolon | `check-script-semicolon` | Yes | `raw_code` is available for dbt SQL nodes. |
| SQL avoids hard-coded table names | `check-script-has-no-table-name` | Partial | `raw_code` is available, but exact detection needs SQL parsing/regex outside pure metadata joins. |
| SQL refs/sources exist | `check-script-ref-and-source` | Partial | If compile succeeds, refs/sources already resolved; missing refs may prevent producing the index. |
| Source columns have descriptions | `check-source-columns-have-desc` | Yes | Source columns can be checked through source nodes plus `dbt.node_columns`. |
| Source has all columns in properties file | `check-source-has-all-columns` | Partial | Needs actual source/catalog columns, not just declared YAML columns. |
| Source has description | `check-source-has-description` | Yes | Source description fields are available. |
| Source table has description | `check-source-table-has-description` | Yes | Source table description fields are available. |
| Source has freshness | `check-source-has-freshness` | Yes | Freshness is exposed on source rows. |
| Source has loader | `check-source-has-loader` | Yes | Loader is exposed on source rows. |
| Source has required meta keys | `check-source-has-meta-keys` | Yes | Source/source-table meta fields are exposed on source rows. |
| Source has required label keys | `check-source-has-labels-keys` | Partial | Labels were not observed as a consistent source field in the local index. |
| Source has tests by name | `check-source-has-tests-by-name` | Yes | Same attached-test pattern as models. |
| Source has tests by type | `check-source-has-tests-by-type` | Yes | Same attached-test pattern as models. |
| Source has tests by group | `check-source-has-tests-by-group` | Yes | Same attached-test pattern as models. |
| Source has any tests | `check-source-has-tests` | Yes | Needs attached test counts. |
| Source has valid tags | `check-source-tags` | Yes | Tags are available on source rows. |
| Source has child count bounds | `check-source-childs` | Yes | Needs source child counts from `dbt.edges`. |
| Macro has description | `check-macro-has-description` | Yes | `dbt.macros` has descriptions. |
| Macro arguments have descriptions | `check-macro-arguments-have-desc` | Partial | Macro arguments are present; need confirm Fusion populates argument descriptions when provided. |
| Macro has required meta keys | `check-macro-has-meta-keys` | Yes | `dbt.macros` has `meta`. |
| Exposure has required meta keys | `check-exposure-has-meta-keys` | Yes | `dbt.exposures` has `meta`. |
| Seed has required meta keys | `check-seed-has-meta-keys` | Partial | Seeds appear as node rows, but local node `meta` was not reliable. |
| Snapshot has required meta keys | `check-snapshot-has-meta-keys` | Partial | Snapshots should appear as node rows, but local node `meta` reliability is the issue. |
| Singular test has required meta keys | `check-test-has-meta-keys` | Partial | Test nodes exist, but local node `meta` reliability is the issue. |
| Test has valid tags | `check-test-tags` | Yes | Test tags are available on node rows. |
| Generate missing sources | `generate-missing-sources` | N/A | Mutates YAML; outside a dbt-test metadata assertion. |
| Generate model properties file | `generate-model-properties-file` | N/A | Mutates YAML; outside this pattern. |
| Unify column descriptions | `unify-column-description` | N/A | Mutates YAML; metadata can detect drift, not rewrite files. |
| Replace hard-coded table names | `replace-script-table-names` | N/A | Mutates SQL; outside this pattern. |
| Remove script semicolon | `remove-script-semicolon` | N/A | Mutates SQL; the assertion version is covered by `check-script-semicolon`. |
| Run `dbt clean` | `dbt-clean` | N/A | Command wrapper, not a metadata assertion. |
| Run `dbt compile` | `dbt-compile` | N/A | Command wrapper. Our wrapper already runs Fusion compile. |
| Run `dbt deps` | `dbt-deps` | N/A | Command wrapper. |
| Run `dbt docs generate` | `dbt-docs-generate` | N/A | Command wrapper. |
| Run `dbt parse` | `dbt-parse` | N/A | Command wrapper. |
| Run `dbt run` | `dbt-run` | N/A | Executes models; outside metadata-only checks. |
| Run `dbt test` | `dbt-test` | N/A | Command wrapper. Our wrapper already runs the metadata tests. |
| Database/schema casing consistency | `check-database-casing-consistency` | No | Needs manifest-vs-catalog comparison; the current compile index is not enough. |

## Takeaway

For this PoC, `compile --write-index` is the right default. Most
dbt-project-evaluator-style rules fit well because they are graph, config,
documentation, or test-coverage checks.

The weaker areas are file-location checks, file mutation hooks, exact SQL
linting, checks that need actual warehouse/catalog columns, and checks depending
on `meta` fields that Fusion is not currently surfacing reliably in the
normalized compile index.
