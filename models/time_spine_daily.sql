{{
    config(
        materialized = 'table',
    )
}}

select
    cast(date_day as date) as date_day
from range(
    date '2020-01-01',
    date '2031-01-01',
    interval 1 day
) as days(date_day)
