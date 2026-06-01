{{ config(tags=['project_metadata_checks']) }}

select
    nodes.name as model_name,
    nodes.original_file_path
from {{ source('dbt_index', 'nodes') }} as nodes
left join {{ source('dbt_index', 'node_columns') }} as columns
    on nodes.unique_id = columns.unique_id
where nodes.resource_type = 'model'
  and nodes.enabled
  and nodes.package_name = {{ metadata_project_package() }}
group by 1, 2
having count(columns.column_name) = 0
