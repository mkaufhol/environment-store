-- name: GetEntry :one
SELECT *
FROM environment_store
WHERE organization IS NOT DISTINCT FROM sqlc.narg('organization')
  AND project IS NOT DISTINCT FROM sqlc.narg('project')
  AND environment IS NOT DISTINCT FROM sqlc.narg('environment')
  AND service IS NOT DISTINCT FROM sqlc.narg('service')
  AND var = sqlc.arg('var')
LIMIT 1;

-- name: GetAllEntries :many
SELECT organization,
       project,
       environment,
       service,
       var,
       var_value,
       is_secret,
       created_at,
       updated_at
FROM environment_store
ORDER BY organization,
         project,
         environment,
         service,
         var;

-- name: GetAllEntriesAsPath :many
SELECT concat_ws('/', organization, project, environment, service, var) AS key_path,
       var_value,
       is_secret
FROM environment_store
ORDER BY organization,
         project,
         environment,
         service,
         var;

-- name: GetVariables :many
SELECT var,
       var_value,
       is_secret
FROM environment_store
WHERE organization IS NOT DISTINCT FROM sqlc.narg('organization')
  AND project IS NOT DISTINCT FROM sqlc.narg('project')
  AND environment IS NOT DISTINCT FROM sqlc.narg('environment')
  AND service IS NOT DISTINCT FROM sqlc.narg('service')
  AND var IS NOT NULL
ORDER BY var;

-- name: CreateEntry :one
INSERT INTO environment_store (organization,
                               project,
                               environment,
                               service,
                               var,
                               var_value,
                               is_secret)
VALUES (sqlc.narg('organization'),
        sqlc.narg('project'),
        sqlc.narg('environment'),
        sqlc.narg('service'),
        sqlc.arg('var'),
        sqlc.arg('var_value'),
        sqlc.arg('is_secret'))
RETURNING *;

-- name: UpsertEntry :exec
INSERT INTO environment_store (organization,
                               project,
                               environment,
                               service,
                               var,
                               var_value)
VALUES (sqlc.narg('organization'),
        sqlc.narg('project'),
        sqlc.narg('environment'),
        sqlc.narg('service'),
        sqlc.arg('var'),
        sqlc.arg('var_value'))
ON CONFLICT (organization, project, environment, service, var)
    DO UPDATE SET var_value = EXCLUDED.var_value;

-- name: UpdateEntry :execrows
UPDATE environment_store
SET var_value = sqlc.arg('var_value')
WHERE organization IS NOT DISTINCT FROM sqlc.narg('organization')
  AND project IS NOT DISTINCT FROM sqlc.narg('project')
  AND environment IS NOT DISTINCT FROM sqlc.narg('environment')
  AND service IS NOT DISTINCT FROM sqlc.narg('service')
  AND var = sqlc.arg('var');

-- name: DeleteEntry :execrows
DELETE
FROM environment_store
WHERE organization IS NOT DISTINCT FROM sqlc.narg('organization')
  AND project IS NOT DISTINCT FROM sqlc.narg('project')
  AND environment IS NOT DISTINCT FROM sqlc.narg('environment')
  AND service IS NOT DISTINCT FROM sqlc.narg('service')
  AND var = sqlc.arg('var');

-- name: ListOrganizations :many
SELECT DISTINCT organization
FROM environment_store
WHERE organization IS NOT NULL
ORDER BY organization;

-- name: ListProjects :many
SELECT DISTINCT project
FROM environment_store
WHERE organization = sqlc.arg('organization')
  AND project IS NOT NULL
ORDER BY project;

-- name: ListEnvironments :many
SELECT DISTINCT environment
FROM environment_store
WHERE organization = sqlc.arg('organization')
  AND project = sqlc.arg('project')
  AND environment IS NOT NULL
ORDER BY environment;

-- name: ListServices :many
SELECT DISTINCT service
FROM environment_store
WHERE organization = sqlc.arg('organization')
  AND project = sqlc.arg('project')
  AND environment = sqlc.arg('environment')
  AND service IS NOT NULL
ORDER BY service;
