-- name: GetEntry :one
SELECT *
FROM environment_store
WHERE organization = $1
  AND project = $2
  AND environment = $3
  AND service = $4
  AND var = $5
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

-- name: GetRootEnvironment :many
SELECT var,
       var_value,
       is_secret
FROM environment_store
WHERE organization IS NULL
  AND project IS NULL
  AND environment IS NULL
  AND service IS NULL
ORDER BY var;

-- name: GetOrganizationEnvironment :many
SELECT var,
       var_value,
       is_secret
FROM environment_store
WHERE organization = $1
  AND project IS NULL
  AND environment IS NULL
  AND service IS NULL
ORDER BY var;

-- name: GetProjectEnvironment :many
SELECT var,
       var_value,
       is_secret
FROM environment_store
WHERE organization = $1
  AND project = $2
  AND environment IS NULL
  AND service IS NULL
ORDER BY var;

-- name: GetEnvironmentEnvironment :many
SELECT var,
       var_value,
       is_secret
FROM environment_store
WHERE organization = $1
  AND project = $2
  AND environment = $3
  AND service IS NULL
ORDER BY var;

-- name: GetServiceEnvironment :many
SELECT var,
       var_value,
       is_secret
FROM environment_store
WHERE organization = $1
  AND project = $2
  AND environment = $3
  AND service = $4
ORDER BY var;

-- name: CreateEntry :one
INSERT INTO environment_store (organization,
                               project,
                               environment,
                               service,
                               var,
                               var_value,
                               is_secret)
VALUES ($1,
        $2,
        $3,
        $4,
        $5,
        $6,
        $7)
RETURNING *;

-- name: UpdateEntry :exec
UPDATE environment_store
set var_value = $6,
    is_secret = $7
WHERE organization = $1
  AND project = $2
  AND environment = $3
  AND service = $4
  AND var = $5;

-- name: DeleteEntry :exec
DELETE
FROM environment_store
WHERE organization = $1
  AND project = $2
  AND environment = $3
  AND service = $4;
