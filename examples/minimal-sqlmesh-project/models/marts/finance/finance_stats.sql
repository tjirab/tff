MODEL (
  name sqlmesh_example.finance_stats,
  kind FULL,
  owner 'finance_team',
  description 'Core finance statistics',
  grain user_id
);

WITH cleaned_users AS (
  SELECT
    user_id,
    user_name,
    LOWER(user_name) AS normalized_name
  FROM sqlmesh_example.src_users
  WHERE user_id IS NOT NULL AND user_name != ''
)
SELECT
  user_id,
  CAST(100.0 AS DOUBLE) AS revenue
FROM cleaned_users;
