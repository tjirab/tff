MODEL (
  name sqlmesh_example.marketing_type_violation,
  kind FULL,
  owner 'marketing_team',
  description 'Demonstrates Connascence of Type (CoT) join type parity violation',
  grain (order_id, user_id)
);

WITH orders AS (
  SELECT
    1 AS order_id,
    100 AS user_id,
    49.99 AS order_amount
)
SELECT
  o.order_id,
  o.user_id,
  u.user_name,
  o.order_amount
FROM orders o
LEFT JOIN sqlmesh_example.users u
  ON o.user_id = u.user_id;
