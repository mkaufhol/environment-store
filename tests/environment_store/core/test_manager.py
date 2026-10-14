import pytest

from environment_store.core.manager import EnvironmentStoreManager
from environment_store.core.schemas import Variable


class TestEnvironmentStoreManager:
    """Test suite for EnvironmentStoreManager."""

    def test_initialization(self):
        """Test that EnvironmentStoreManager initializes."""
        manager = EnvironmentStoreManager(adapter=None)  # ty: ignore[invalid-argument-type]
        assert isinstance(manager, EnvironmentStoreManager)

    def test_overwrite_hierarchy_variables_with_no_duplicates(self):
        """Test that overwrite_hierarchy_variables works."""
        variables = [Variable(name="a", value="1"), Variable(name="b", value="2")]
        overwrite_variables = [Variable(name="c", value="3"), Variable(name="d", value="4")]
        result = EnvironmentStoreManager.overwrite_hierarchy_variables(
            variables, overwrite_variables
        )
        assert result == variables + overwrite_variables

    def test_overwrite_hierarchy_variables_with_duplicate_names_and_overwrite_parent(self):
        """Test that overwrite_hierarchy_variables works."""

        variables = [Variable(name="a", value="1"), Variable(name="b", value="2")]
        overwrite_variables = [Variable(name="b", value="3"), Variable(name="c", value="4")]
        result = EnvironmentStoreManager.overwrite_hierarchy_variables(
            variables,
            overwrite_variables,
            overwrite_parent=True,
        )
        assert result == [
            Variable(name="a", value="1"),
            Variable(name="b", value="3"),
            Variable(name="c", value="4"),
        ]

    def test_overwrite_hierarchy_variables_with_duplicate_names_and_not_overwrite_parent(self):
        """Test that overwrite_hierarchy_variables works."""

        variables = [Variable(name="a", value="1"), Variable(name="b", value="2")]
        overwrite_variables = [Variable(name="b", value="3"), Variable(name="c", value="4")]
        result = EnvironmentStoreManager.overwrite_hierarchy_variables(
            variables,
            overwrite_variables,
            overwrite_parent=False,
        )
        assert result == [
            Variable(name="a", value="1"),
            Variable(name="b", value="2"),
            Variable(name="c", value="4"),
        ]

    def test_overwrite_hierarchy_variables_with_empty_lists(self):
        """Test that overwrite_hierarchy_variables works with empty lists."""

        variables = []
        overwrite_variables = []
        result = EnvironmentStoreManager.overwrite_hierarchy_variables(
            variables, overwrite_variables
        )
        assert result == []

    def test_overwrite_hierarchy_variables_with_empty_overwrite_list(self):
        """Test that overwrite_hierarchy_variables works with empty overwrite list."""
        variables = [Variable(name="a", value="1"), Variable(name="b", value="2")]
        overwrite_variables = []
        result = EnvironmentStoreManager.overwrite_hierarchy_variables(
            variables, overwrite_variables
        )
        assert result == variables

    def test_overwrite_hierarchy_variables_with_empty_variables_list(self):
        """Test that overwrite_hierarchy_variables works with empty variables list."""
        variables = []
        overwrite_variables = [Variable(name="a", value="1"), Variable(name="b", value="2")]
        result = EnvironmentStoreManager.overwrite_hierarchy_variables(
            variables, overwrite_variables
        )
        assert result == overwrite_variables

    def test_overwrite_hierarchy_variables_with_none_variables(self):
        """Test that overwrite_hierarchy_variables raises ValueError with None variables."""
        with pytest.raises(ValueError) as exc_info:
            EnvironmentStoreManager.overwrite_hierarchy_variables(None, None)  # ty: ignore[invalid-argument-type]
        assert "variables must be a list" in str(exc_info.value)

    def test_overwrite_hierarchy_variables_with_none_overwrite_variables(self):
        """Test that overwrite_hierarchy_variables raises ValueError with None overwrite_variables."""
        with pytest.raises(ValueError) as exc_info:
            EnvironmentStoreManager.overwrite_hierarchy_variables([], None)  # ty: ignore[invalid-argument-type]
        assert "overwrite_variables must be a list" in str(exc_info.value)


class TestDeleteLevel:
    @pytest.fixture
    def manager(self, tmp_path):
        from environment_store.adapters.json.json_file_adapter import JsonFileAdapter

        m = EnvironmentStoreManager(JsonFileAdapter(str(tmp_path / "s.json")))
        m.set_variable("ROOT", "r")
        m.set_variable("A", "1", organisation="acme")
        m.set_variable("B", "2", organisation="acme", project="web")
        m.set_variable("C", "3", organisation="acme", project="web", environment="dev")
        m.set_variable(
            "D", "4", organisation="acme", project="web", environment="dev", service="api"
        )
        m.set_variable("E", "5", organisation="other")
        return m

    def test_count_level(self, manager):
        assert manager.count_level(organisation="acme") == (4, 3)
        assert manager.count_level(organisation="acme", project="web", environment="dev") == (
            2,
            1,
        )

    def test_delete_level_removes_level_and_descendants(self, manager):
        assert manager.delete_level(organisation="acme", project="web") == 3
        assert manager.get_projects("acme") == []
        assert [v.name for v in manager.get_variables(organisation="acme")] == ["A"]
        assert manager.get_organisations() == ["acme", "other"]

    def test_delete_organisation_leaves_root_and_siblings(self, manager):
        assert manager.delete_level(organisation="acme") == 4
        assert manager.get_organisations() == ["other"]
        assert manager.get_variable("ROOT") == "r"

    def test_delete_level_requires_organisation_for_deeper_levels(self, manager):
        with pytest.raises(ValueError, match="requires organisation"):
            manager.delete_level(organisation=None, project="web")
