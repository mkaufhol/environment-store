-- unique-nulls-not-distinct
-- depends: 20260315_01_Dj4Bk-initial

-- A plain UNIQUE constraint treats NULLs as distinct, so entries on the upper hierarchy
-- levels (where organization/project/environment/service are NULL) could be duplicated.
ALTER TABLE environment_store
    DROP CONSTRAINT environment_store_organization_project_environment_service__key;

ALTER TABLE environment_store
    ADD CONSTRAINT environment_store_organization_project_environment_service__key
        UNIQUE NULLS NOT DISTINCT (organization, project, environment, service, var);
