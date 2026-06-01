#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -n "${DBT_METADATA_FUSION_TARGET_PATH:-}" ]]; then
  fusion_target_path="$DBT_METADATA_FUSION_TARGET_PATH"
else
  fusion_target_path="$(mktemp -d "${TMPDIR:-/tmp}/dbt-metadata-index.XXXXXX")"
fi
index_dir="${DBT_METADATA_INDEX_DIR:-${fusion_target_path}/index}"
project_package="${DBT_METADATA_PROJECT_PACKAGE:-jaffle_shop}"
fusion_dbt="${DBT_FUSION_BIN:-dbt}"
static_analysis="${DBT_METADATA_STATIC_ANALYSIS:-}"
test_engine="${DBT_METADATA_TEST_ENGINE:-fusion}"

if [[ "$test_engine" == "core" ]]; then
  if [[ -n "${DBT_CORE_BIN:-}" ]]; then
    test_dbt=("$DBT_CORE_BIN")
  elif [[ -x "$repo_root/.venv/bin/dbt" ]]; then
    test_dbt=("$repo_root/.venv/bin/dbt")
  elif command -v uv >/dev/null 2>&1; then
    export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
    test_dbt=(uv run dbt)
  else
    echo "Could not find dbt Core. Set DBT_CORE_BIN, create .venv, or install uv." >&2
    exit 1
  fi
  test_args=(--quiet)
else
  test_dbt=("$fusion_dbt")
  test_args=(--no-version-check)
fi

compile_args=(
  compile
  --write-index
  --target-path "$fusion_target_path"
  --profiles-dir .
  --project-dir .
  --quiet
  --no-version-check
  --show none
)

if [[ -n "$static_analysis" ]]; then
  compile_args+=(--static-analysis "$static_analysis")
fi

"$fusion_dbt" "${compile_args[@]}"

"${test_dbt[@]}" test \
  --project-dir metadata_checks \
  --profiles-dir metadata_checks \
  --select tag:project_metadata_checks \
  --vars "{\"metadata_index_dir\":\"${index_dir}\",\"metadata_project_package\":\"${project_package}\"}" \
  "${test_args[@]}"
