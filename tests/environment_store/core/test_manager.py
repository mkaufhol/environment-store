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
        assert manager.delete_level(organisation="acme", project="web", confirm="web") == 3
        assert manager.get_projects("acme") == []
        assert [v.name for v in manager.get_variables(organisation="acme")] == ["A"]
        assert manager.get_organisations() == ["acme", "other"]

    def test_delete_organisation_leaves_root_and_siblings(self, manager):
        assert manager.delete_level(organisation="acme", confirm="acme") == 4
        assert manager.get_organisations() == ["other"]
        assert manager.get_variable("ROOT") == "r"

    def test_delete_level_requires_organisation_for_deeper_levels(self, manager):
        with pytest.raises(ValueError, match="requires organisation"):
            manager.delete_level(organisation=None, project="web", confirm="web")

    def test_delete_level_requires_exact_name(self, manager):
        from environment_store.core.exceptions import ConfirmationMismatchError

        for wrong in ("", "ACME", "web"):
            with pytest.raises(ConfirmationMismatchError):
                manager.delete_level(organisation="acme", confirm=wrong)
        assert manager.count_level(organisation="acme") == (4, 3)

    def test_delete_level_requires_confirm_keyword(self, manager):
        with pytest.raises(TypeError):
            manager.delete_level(organisation="acme")

    def test_get_child_levels(self, manager):
        assert manager.get_child_levels() == ["acme", "other"]
        assert manager.get_child_levels(organisation="acme") == ["web"]
        assert manager.get_child_levels(organisation="acme", project="web") == ["dev"]
        assert manager.get_child_levels(
            organisation="acme", project="web", environment="dev"
        ) == ["api"]
        assert (
            manager.get_child_levels(
                organisation="acme", project="web", environment="dev", service="api"
            )
            == []
        )

    def test_get_resolved_variables(self, manager):
        manager.set_variable("A", "svc", organisation="acme", project="web", environment="dev")
        resolved = {
            v.name: v.value
            for v in manager.get_resolved_variables(
                organisation="acme", project="web", environment="dev"
            )
        }
        assert resolved == {"ROOT": "r", "A": "svc", "B": "2", "C": "3"}
        assert [v.name for v in manager.get_resolved_variables()] == ["ROOT"]
        with pytest.raises(ValueError, match="requires organisation"):
            manager.get_resolved_variables(project="web")


class TestImportFrom:
    @pytest.fixture
    def stores(self, tmp_path):
        from environment_store.adapters.json.json_file_adapter import JsonFileAdapter

        source = EnvironmentStoreManager(JsonFileAdapter(str(tmp_path / "source.json")))
        destination = EnvironmentStoreManager(JsonFileAdapter(str(tmp_path / "dest.json")))
        source.set_variable("ROOT", "r")
        source.set_variable("A", "1", organisation="acme")
        source.set_variable("B", "2", organisation="acme", project="web")
        source.set_variable("C", "3", organisation="acme", project="web", environment="dev")
        source.set_variable("E", "5", organisation="other")
        return source, destination

    def test_iter_levels_walks_parents_first_and_skips_empty_levels(self, stores):
        source, _ = stores
        assert [path for path, _ in source.iter_levels()] == [
            (),
            ("acme",),
            ("acme", "web"),
            ("acme", "web", "dev"),
            ("other",),
        ]
        assert [path for path, _ in source.iter_levels(organisation="acme", project="web")] == [
            ("acme", "web"),
            ("acme", "web", "dev"),
        ]

    def test_copies_everything_and_leaves_source_untouched(self, stores):
        source, destination = stores
        result = destination.import_from(source)
        assert (result.levels, result.created, result.skipped) == (5, 5, 0)
        assert (
            destination.get_variable("C", organisation="acme", project="web", environment="dev")
            == "3"
        )
        assert destination.get_variable("ROOT") == "r"
        assert source.count_level(organisation="acme") == (3, 2)

    def test_copies_only_a_subtree(self, stores):
        source, destination = stores
        result = destination.import_from(source, organisation="acme", project="web")
        assert result.created == 2
        assert destination.get_organisations() == ["acme"]
        assert destination.get_variables(organisation="acme") == []

    def test_existing_values_conflict_unless_overwrite(self, stores):
        source, destination = stores
        destination.set_variable("A", "other value", organisation="acme")
        destination.set_variable("ROOT", "r")
        result = destination.import_from(source)
        assert (result.created, result.unchanged, result.skipped) == (3, 1, 1)
        assert [(c.path, c.name) for c in result.conflicts] == [(["acme"], "A")]
        assert destination.get_variable("A", organisation="acme") == "other value"
        result = destination.import_from(source, overwrite=True)
        assert (result.updated, result.unchanged, result.skipped) == (1, 4, 0)
        assert destination.get_variable("A", organisation="acme") == "1"

    def test_dry_run_writes_nothing(self, stores):
        source, destination = stores
        result = destination.import_from(source, dry_run=True)
        assert result.created == 5
        assert destination.get_organisations() == []
        assert destination.get_variables() == []
