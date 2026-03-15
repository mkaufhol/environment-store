-- initial
-- depends:
DROP TRIGGER IF EXISTS update_environment_store_updated_at ON environment_store;
DROP FUNCTION IF EXISTS update_updated_at_column();
DROP TABLE IF EXISTS environment_store;
