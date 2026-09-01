MODEL (
  name sqlmesh_example.layer_violation,
  kind FULL,
  owner 'core_team',
  description 'Violates layer integrity by depending on marts',
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
  user_id
FROM cleaned_users;
