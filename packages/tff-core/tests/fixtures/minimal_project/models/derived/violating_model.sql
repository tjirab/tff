MODEL (
  name sqlmesh_example.violating_model,
  kind FULL,
  owner 'data_team',
  description 'Derived model',
  grain id
);

SELECT 1 AS id;
