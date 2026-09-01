MODEL (
  name sqlmesh_example.marketing_all_users,
  kind FULL,
  owner 'marketing_team',
  description 'All marketing users consolidated',
  grain user_id
);

WITH marketing_cleaned_users AS (
  SELECT
    user_id,
    user_name,
    LOWER(user_name) AS normalized_name
  FROM sqlmesh_example.src_users
  WHERE user_id IS NOT NULL AND user_name != ''
)
SELECT
  u.user_id,
  u.user_name,
  f.revenue
FROM marketing_cleaned_users u
LEFT JOIN sqlmesh_example.finance_stats f
  ON u.user_id = f.user_id;
