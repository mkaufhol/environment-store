-- unique-nulls-not-distinct (rollback)
ALTER TABLE environment_store
    DROP CONSTRAINT environment_store_organization_project_environment_service__key;

ALTER TABLE environment_store
    ADD CONSTRAINT environment_store_organization_project_environment_service__key
        UNIQUE (organization, project, environment, service, var);
