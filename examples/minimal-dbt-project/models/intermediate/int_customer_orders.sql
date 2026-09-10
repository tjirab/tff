SELECT
    customer_id,
    count(*) AS order_count,
    sum(amount) AS total_spent
FROM {{ ref("stg_orders") }}
GROUP BY customer_id
