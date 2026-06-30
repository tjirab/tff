MODEL (
  name sqlmesh_example.users,
  kind FULL,
  description 'Core users table',
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
  *
FROM cleaned_users;
