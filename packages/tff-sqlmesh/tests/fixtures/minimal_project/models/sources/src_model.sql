MODEL (
  name sqlmesh_example.src_model,
  kind FULL,
  owner 'data_team',
  description 'Staging model',
  grain id
);

SELECT id FROM sqlmesh_example.violating_model;
