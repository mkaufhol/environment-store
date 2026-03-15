-- initial
-- depends:
CREATE TABLE environment_store
(
    id           SERIAL PRIMARY KEY,
    is_secret    BOOLEAN NOT NULL DEFAULT FALSE,
    organization VARCHAR(100),
    project      VARCHAR(100),
    environment  VARCHAR(100),
    service      VARCHAR(100),
    var          VARCHAR(100),
    var_value    TEXT,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (
            organization,
            project,
            environment,
            service,
            var
        ),
    CONSTRAINT environment_store_hierarchy_check CHECK (
        (project IS NULL OR organization IS NOT NULL)
        AND (environment IS NULL OR (organization IS NOT NULL AND project IS NOT NULL))
        AND (
            service IS NULL
            OR (organization IS NOT NULL AND project IS NOT NULL AND environment IS NOT NULL)
        )
    )
);

-- Trigger function to update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach trigger to table
CREATE TRIGGER update_environment_store_updated_at
    BEFORE UPDATE ON environment_store
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
