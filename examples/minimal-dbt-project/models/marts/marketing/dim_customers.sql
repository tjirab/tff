SELECT
    c.customer_id,
    c.name,
    c.email,
    coalesce(o.order_count, 0) AS order_count,
    coalesce(o.total_spent, 0) AS total_spent
FROM {{ ref("stg_customers") }} AS c
LEFT JOIN {{ ref("int_customer_orders") }} AS o
    ON c.customer_id = o.customer_id
