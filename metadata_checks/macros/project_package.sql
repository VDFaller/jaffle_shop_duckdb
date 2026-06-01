{% macro metadata_project_package() -%}
  {%- set package_name = var('metadata_project_package', env_var('DBT_METADATA_PROJECT_PACKAGE', 'jaffle_shop')) -%}
  '{{ package_name | replace("'", "''") }}'
{%- endmacro %}
