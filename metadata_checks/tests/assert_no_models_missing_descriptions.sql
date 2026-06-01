{{ config(tags=['project_metadata_checks']) }}

select
    nodes.name as model_name,
    nodes.original_file_path
from {{ source('dbt_index', 'nodes') }} as nodes
inner join {{ source('dbt_index', 'metadata_policy') }} as policy
    on nodes.unique_id = policy.unique_id
where nodes.resource_type = 'model'
  and nodes.enabled
  and nodes.package_name = {{ metadata_project_package() }}
  and coalesce(policy.require_model_description, false)
  and nullif(trim(nodes.description), '') is null
