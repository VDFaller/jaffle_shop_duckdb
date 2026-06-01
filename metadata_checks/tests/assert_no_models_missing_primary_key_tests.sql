{{ config(tags=['project_metadata_checks']) }}

with tests as (

    select
        unique_id as test_unique_id,
        attached_node as unique_id,
        test_name,
        coalesce(test_namespace, '') as test_namespace,
        column_name,
        kwargs
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

compound_pk_test_columns as (

    select
        unique_id,
        test_unique_id,
        test_name,
        test_namespace,
        unnest(
            case
                when test_name = 'unique_combination_of_columns'
                    then coalesce(
                        json_extract_string(kwargs, '$.combination_of_columns')::varchar[],
                        json_extract_string(kwargs, '$.arguments.combination_of_columns')::varchar[],
                        []::varchar[]
                    )
                when test_name = 'expect_compound_columns_to_be_unique'
                    then coalesce(
                        json_extract_string(kwargs, '$.column_list')::varchar[],
                        json_extract_string(kwargs, '$.arguments.column_list')::varchar[],
                        []::varchar[]
                    )
                else []::varchar[]
            end
        ) as column_name
    from tests
    where test_name in (
        'unique_combination_of_columns',
        'expect_compound_columns_to_be_unique'
    )

),

compound_pk_tests as (

    select
        compound_pk_test_columns.unique_id,
        compound_pk_test_columns.test_unique_id,
        compound_pk_test_columns.test_name,
        compound_pk_test_columns.test_namespace,
        count(*) as pk_column_count,
        count(column_pk_tests.column_name) filter (
            where coalesce(column_pk_tests.has_not_null_test, false)
        ) as not_null_column_count
    from compound_pk_test_columns
    left join column_pk_tests
        on compound_pk_test_columns.unique_id = column_pk_tests.unique_id
        and compound_pk_test_columns.column_name = column_pk_tests.column_name
    group by 1, 2, 3, 4

),

model_pk_tests as (

    select
        unique_id,
        bool_or(
            test_name = 'unique_combination_of_columns'
            and test_namespace in ('dbt_utils', '')
        ) as has_dbt_utils_compound_unique_test,
        bool_or(
            test_name = 'unique_combination_of_columns'
            and test_namespace in ('dbt_utils', '')
            and pk_column_count > 0
            and pk_column_count = not_null_column_count
        ) as has_dbt_utils_compound_unique_with_not_null,
        bool_or(
            test_name = 'expect_compound_columns_to_be_unique'
            and test_namespace in ('dbt_expectations', '')
        ) as has_dbt_expectations_compound_unique_test,
        bool_or(
            test_name = 'expect_compound_columns_to_be_unique'
            and test_namespace in ('dbt_expectations', '')
            and pk_column_count > 0
            and pk_column_count = not_null_column_count
        ) as has_dbt_expectations_compound_unique_with_not_null
    from compound_pk_tests
    group by 1

),

coverage as (

    select
        nodes.unique_id,
        nodes.name as model_name,
        nodes.original_file_path,
        coalesce(policy.require_primary_key_test, false) as require_primary_key_test,
        (
            coalesce(policy.allow_unique, false)
            and case
                when coalesce(policy.pk_test_requires_not_null, true)
                    then coalesce(array_length(single_column_pk_tests.unique_not_null_columns), 0) > 0
                else coalesce(array_length(single_column_pk_tests.unique_columns), 0) > 0
            end
        )
        or (
            coalesce(policy.allow_dbt_utils_unique_combination_of_columns, false)
            and case
                when coalesce(policy.pk_test_requires_not_null, true)
                    then coalesce(model_pk_tests.has_dbt_utils_compound_unique_with_not_null, false)
                else coalesce(model_pk_tests.has_dbt_utils_compound_unique_test, false)
            end
        )
        or (
            coalesce(policy.allow_dbt_expectations_expect_compound_columns_to_be_unique, false)
            and case
                when coalesce(policy.pk_test_requires_not_null, true)
                    then coalesce(model_pk_tests.has_dbt_expectations_compound_unique_with_not_null, false)
                else coalesce(model_pk_tests.has_dbt_expectations_compound_unique_test, false)
            end
        )
            as has_primary_key_test,
        single_column_pk_tests.unique_not_null_columns,
        single_column_pk_tests.unique_columns,
        single_column_pk_tests.not_null_columns,
        coalesce(model_pk_tests.has_dbt_utils_compound_unique_test, false)
            as has_dbt_utils_compound_unique_test,
        coalesce(model_pk_tests.has_dbt_utils_compound_unique_with_not_null, false)
            as has_dbt_utils_compound_unique_with_not_null,
        coalesce(model_pk_tests.has_dbt_expectations_compound_unique_test, false)
            as has_dbt_expectations_compound_unique_test,
        coalesce(model_pk_tests.has_dbt_expectations_compound_unique_with_not_null, false)
            as has_dbt_expectations_compound_unique_with_not_null
    from {{ source('dbt_index', 'nodes') }} as nodes
    inner join {{ source('dbt_index', 'metadata_policy') }} as policy
        on nodes.unique_id = policy.unique_id
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
    has_dbt_utils_compound_unique_with_not_null,
    has_dbt_expectations_compound_unique_test,
    has_dbt_expectations_compound_unique_with_not_null
from coverage
where require_primary_key_test
  and not has_primary_key_test
