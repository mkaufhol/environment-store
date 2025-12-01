import pytest
from environment_store.environment_store_manager.manager import EnvironmentStoreManager
from environment_store.environment_store_manager.schemas import Variable


class TestEnvironmentStoreManager:
    """Test suite for EnvironmentStoreManager."""

    def test_initialization(self):
        """Test that EnvironmentStoreManager initializes."""
        manager = EnvironmentStoreManager(adapter=None)
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
            EnvironmentStoreManager.overwrite_hierarchy_variables(None, None)  # noqa
        assert "variables must be a list" in str(exc_info.value)

    def test_overwrite_hierarchy_variables_with_none_overwrite_variables(self):
        """Test that overwrite_hierarchy_variables raises ValueError with None overwrite_variables."""
        with pytest.raises(ValueError) as exc_info:
            EnvironmentStoreManager.overwrite_hierarchy_variables([], None)  # noqa
        assert "overwrite_variables must be a list" in str(exc_info.value)
