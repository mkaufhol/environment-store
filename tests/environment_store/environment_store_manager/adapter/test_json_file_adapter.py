import json
import pytest
from pathlib import Path

from environment_store.environment_store_manager.adapter.json_file_adapter import (
    JsonFileAdapter,
)
from environment_store.environment_store_manager.schemas import Variable


@pytest.fixture
def temp_file(tmp_path: Path):
    """Create a temporary file path for testing (file doesn't exist yet)."""
    return tmp_path / "test_env.json"


@pytest.fixture
def adapter(temp_file: Path):
    """Create a JsonFileAdapter instance for testing."""
    return JsonFileAdapter(str(temp_file))


class TestJsonFileAdapter:
    """Test suite for JsonFileAdapter."""

    #####################
    # Test get_variable #
    #####################

    def test_get_variable_root_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test getting a variable at the root level."""
        temp_file.write_text(json.dumps({"test": "value"}))
        assert adapter.get_variable("test") == "value"
        assert adapter.get_organisations() == []
        assert adapter.get_projects("acme") == []
        assert adapter.get_environments("acme", "webapp") == []
        assert adapter.get_services("acme", "webapp", "dev") == []

    def test_get_variable_organisation_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test getting a variable at the organisation level."""
        temp_file.write_text(json.dumps({"acme": {"test": "value"}}))
        assert adapter.get_variable("test", organisation="acme") == "value"
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == []
        assert adapter.get_environments("acme", "webapp") == []
        assert adapter.get_services("acme", "webapp", "dev") == []

    def test_get_variable_project_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test getting a variable at the project level."""
        temp_file.write_text(json.dumps({"acme": {"webapp": {"test": "value"}}}))
        assert adapter.get_variable("test", organisation="acme", project="webapp") == "value"
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == ["webapp"]
        assert adapter.get_environments("acme", "webapp") == []
        assert adapter.get_services("acme", "webapp", "dev") == []

    def test_get_variable_environment_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test getting a variable at the environment level."""
        temp_file.write_text(json.dumps({"acme": {"webapp": {"dev": {"test": "value"}}}}))
        assert (
            adapter.get_variable(
                "test", organisation="acme", project="webapp", environment="dev"
            )
            == "value"
        )
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == ["webapp"]
        assert adapter.get_environments("acme", "webapp") == ["dev"]
        assert adapter.get_services("acme", "webapp", "dev") == []

    def test_get_variable_service_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test getting a variable at the service level."""
        temp_file.write_text(
            json.dumps({"acme": {"webapp": {"dev": {"api": {"test": "value"}}}}})
        )
        assert (
            adapter.get_variable(
                "test", organisation="acme", project="webapp", environment="dev", service="api"
            )
            == "value"
        )
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == ["webapp"]
        assert adapter.get_environments("acme", "webapp") == ["dev"]
        assert adapter.get_services("acme", "webapp", "dev") == ["api"]

    #####################
    # Test set_variable #
    #####################

    def test_set_variable_root_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test setting a variable."""
        adapter.set_variable("test", "value")
        assert adapter.get_variable("test") == "value"
        assert adapter.get_organisations() == []

        data = json.loads(temp_file.read_text())
        assert data == {"test": "value"}

    def test_set_variable_root_level_with_existing_data(
        self, adapter: JsonFileAdapter, temp_file: Path
    ):
        """Test setting a variable when there is existing data."""
        temp_file.write_text(json.dumps({"existing": "data"}))
        adapter.set_variable("test", "value")
        assert adapter.get_variable("test") == "value"
        assert adapter.get_organisations() == []
        data = json.loads(temp_file.read_text())
        assert data == {"existing": "data", "test": "value"}

        adapter.set_variable("test", "value2")
        assert adapter.get_variable("test") == "value2"
        data = json.loads(temp_file.read_text())
        assert data == {"existing": "data", "test": "value2"}

    def test_set_variable_organisation_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test setting a variable at the organisation level."""
        adapter.set_variable("test", "value", organisation="acme")
        assert adapter.get_variable("test", organisation="acme") == "value"
        assert adapter.get_organisations() == ["acme"]

        data = json.loads(temp_file.read_text())
        assert data == {"acme": {"test": "value"}}

    def test_set_variable_project_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test setting a variable at the project level."""
        adapter.set_variable("test", "value", organisation="acme", project="webapp")
        assert adapter.get_variable("test", organisation="acme", project="webapp") == "value"
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == ["webapp"]

        data = json.loads(temp_file.read_text())
        assert data == {"acme": {"webapp": {"test": "value"}}}

    def test_set_variable_environment_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test setting a variable at the environment level."""
        adapter.set_variable(
            "test", "value", organisation="acme", project="webapp", environment="dev"
        )
        assert (
            adapter.get_variable(
                "test", organisation="acme", project="webapp", environment="dev"
            )
            == "value"
        )
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == ["webapp"]
        assert adapter.get_environments("acme", "webapp") == ["dev"]

        data = json.loads(temp_file.read_text())
        assert data == {"acme": {"webapp": {"dev": {"test": "value"}}}}

    def test_set_variable_service_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test setting a variable at the service level."""
        adapter.set_variable(
            "test",
            "value",
            organisation="acme",
            project="webapp",
            environment="dev",
            service="api",
        )
        assert (
            adapter.get_variable(
                "test", organisation="acme", project="webapp", environment="dev", service="api"
            )
            == "value"
        )
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == ["webapp"]
        assert adapter.get_environments("acme", "webapp") == ["dev"]
        assert adapter.get_services("acme", "webapp", "dev") == ["api"]

        data = json.loads(temp_file.read_text())
        assert data == {"acme": {"webapp": {"dev": {"api": {"test": "value"}}}}}

    ######################
    # Test set_variables #
    ######################

    def test_set_variables_root_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test setting multiple variables at the root level."""
        variables = [
            Variable(name="test1", value="value1"),
            Variable(name="test2", value="value2"),
        ]
        adapter.set_variables(variables)
        assert adapter.get_variable("test1") == "value1"
        assert adapter.get_variable("test2") == "value2"
        assert adapter.get_organisations() == []
        assert adapter.get_projects("acme") == []
        assert adapter.get_environments("acme", "webapp") == []
        assert adapter.get_services("acme", "webapp", "dev") == []

        data = json.loads(temp_file.read_text())
        assert data == {"test1": "value1", "test2": "value2"}

    def test_set_variables_root_level_with_existing_data(
        self, adapter: JsonFileAdapter, temp_file: Path
    ):
        """Test setting multiple variables at the root level with existing data."""
        temp_file.write_text(json.dumps({"existing": "data"}))
        variables = [
            Variable(name="test1", value="value1"),
            Variable(name="test2", value="value2"),
        ]
        adapter.set_variables(variables)
        assert adapter.get_variable("test1") == "value1"
        assert adapter.get_variable("test2") == "value2"
        assert adapter.get_organisations() == []
        data = json.loads(temp_file.read_text())
        assert data == {"existing": "data", "test1": "value1", "test2": "value2"}

        variables = [
            Variable(name="test1", value="value1_changed"),
            Variable(name="test2", value="value2_changed"),
        ]
        adapter.set_variables(variables)
        assert adapter.get_variable("test1") == "value1_changed"
        assert adapter.get_variable("test2") == "value2_changed"

    def test_set_variables_organisation_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test setting multiple variables at the organisation level."""
        variables = [
            Variable(name="test1", value="value1"),
            Variable(name="test2", value="value2"),
        ]
        adapter.set_variables(variables, organisation="acme")
        assert adapter.get_variable("test1", organisation="acme") == "value1"
        assert adapter.get_variable("test2", organisation="acme") == "value2"
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == []
        assert adapter.get_environments("acme", "webapp") == []
        assert adapter.get_services("acme", "webapp", "dev") == []

    def test_set_variables_project_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test setting multiple variables at the project level."""
        variables = [
            Variable(name="test1", value="value1"),
            Variable(name="test2", value="value2"),
        ]
        adapter.set_variables(variables, organisation="acme", project="webapp")
        assert adapter.get_variable("test1", organisation="acme", project="webapp") == "value1"
        assert adapter.get_variable("test2", organisation="acme", project="webapp") == "value2"
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == ["webapp"]
        assert adapter.get_environments("acme", "webapp") == []
        assert adapter.get_services("acme", "webapp", "dev") == []

    def test_set_variables_environment_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test setting multiple variables at the environment level."""
        variables = [
            Variable(name="test1", value="value1"),
            Variable(name="test2", value="value2"),
        ]
        adapter.set_variables(
            variables, organisation="acme", project="webapp", environment="dev"
        )
        assert (
            adapter.get_variable(
                "test1", organisation="acme", project="webapp", environment="dev"
            )
            == "value1"
        )
        assert (
            adapter.get_variable(
                "test2", organisation="acme", project="webapp", environment="dev"
            )
            == "value2"
        )
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == ["webapp"]
        assert adapter.get_environments("acme", "webapp") == ["dev"]
        assert adapter.get_services("acme", "webapp", "dev") == []

    def test_set_variables_service_level(self, adapter: JsonFileAdapter, temp_file: Path):
        """Test setting multiple variables at the service level."""
        variables = [
            Variable(name="test1", value="value1"),
            Variable(name="test2", value="value2"),
        ]
        adapter.set_variables(
            variables, organisation="acme", project="webapp", environment="dev", service="api"
        )
        assert (
            adapter.get_variable(
                "test1", organisation="acme", project="webapp", environment="dev", service="api"
            )
            == "value1"
        )
        assert (
            adapter.get_variable(
                "test2", organisation="acme", project="webapp", environment="dev", service="api"
            )
            == "value2"
        )
        assert adapter.get_organisations() == ["acme"]
        assert adapter.get_projects("acme") == ["webapp"]
        assert adapter.get_environments("acme", "webapp") == ["dev"]
        assert adapter.get_services("acme", "webapp", "dev") == ["api"]
