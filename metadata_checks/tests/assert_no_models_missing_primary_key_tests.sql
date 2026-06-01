{{ config(tags=['project_metadata_checks']) }}

with tests as (

    select
        attached_node as unique_id,
        test_name,
        coalesce(test_namespace, '') as test_namespace,
        column_name
    from {{ source('dbt_index', 'test_metadata') }}
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

coverage as (

    select
        nodes.unique_id,
        nodes.name as model_name,
        nodes.original_file_path,
        case
            when {% if var('metadata_single_column_pk_requires_not_null', true) %}true{% else %}false{% endif %}
                then coalesce(array_length(single_column_pk_tests.unique_not_null_columns), 0) > 0
            else coalesce(array_length(single_column_pk_tests.unique_columns), 0) > 0
        end
        or coalesce(model_pk_tests.has_dbt_utils_compound_unique_test, false)
        or coalesce(model_pk_tests.has_dbt_expectations_compound_unique_test, false)
            as has_primary_key_test,
        single_column_pk_tests.unique_not_null_columns,
        single_column_pk_tests.unique_columns,
        single_column_pk_tests.not_null_columns,
        coalesce(model_pk_tests.has_dbt_utils_compound_unique_test, false)
            as has_dbt_utils_compound_unique_test,
        coalesce(model_pk_tests.has_dbt_expectations_compound_unique_test, false)
            as has_dbt_expectations_compound_unique_test
    from {{ source('dbt_index', 'nodes') }} as nodes
    left join single_column_pk_tests
        on nodes.unique_id = single_column_pk_tests.unique_id
    left join model_pk_tests
        on nodes.unique_id = model_pk_tests.unique_id
    where nodes.resource_type = 'model'
      and nodes.enabled
      and nodes.package_name = {{ metadata_project_package() }}

)

select
    model_name,
    original_file_path,
    unique_not_null_columns,
    unique_columns,
    not_null_columns,
    has_dbt_utils_compound_unique_test,
    has_dbt_expectations_compound_unique_test
from coverage
where not has_primary_key_test
