{{ config(tags=['project_metadata_checks']) }}

select
    name as model_name,
    original_file_path
from {{ source('dbt_index', 'nodes') }}
where resource_type = 'model'
  and enabled
  and package_name = {{ metadata_project_package() }}
  and nullif(trim(description), '') is null
