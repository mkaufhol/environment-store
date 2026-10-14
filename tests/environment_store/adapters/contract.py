"""
Shared behavioural tests for storage adapters.

Every adapter has to behave the same way, because the manager, the CLI and the TUI rely on it. Subclass
``AdapterContract`` (and ``StrictCreateUpdateContract`` if the adapter implements ``create_variable``,
``update_variable`` and ``variable_exists``) in a ``Test...`` class and provide an ``adapter`` fixture.
"""

import pytest

from environment_store.core import EnvironmentStoreManager
from environment_store.core.exceptions import VariableExistsError, VariableNotFoundError
from environment_store.core.schemas import Variable

FULL = {
    "organisation": "acme",
    "project": "webapp",
    "environment": "dev",
    "service": "api",
}


class AdapterContract:
    """
    Behaviour every adapter must have. Subclass it in a ``Test...`` class and provide an ``adapter``
    fixture that yields a fresh, empty adapter. See docs/adding-an-adapter.md.
    """

    def test_set_and_get_at_every_level(self, adapter):
        levels = [
            {},
            {"organisation": "acme"},
            {"organisation": "acme", "project": "webapp"},
            {"organisation": "acme", "project": "webapp", "environment": "dev"},
            FULL,
        ]
        for i, level in enumerate(levels):
            adapter.set_variable("KEY", f"value{i}", **level)
        for i, level in enumerate(levels):
            assert adapter.get_variable("KEY", **level) == f"value{i}"

    def test_get_missing_returns_none(self, adapter):
        assert adapter.get_variable("NOPE") is None
        assert adapter.get_variable("NOPE", **FULL) is None

    def test_set_overwrites(self, adapter):
        adapter.set_variable("KEY", "a", organisation="acme")
        adapter.set_variable("KEY", "b", organisation="acme")
        assert adapter.get_variable("KEY", organisation="acme") == "b"

    def test_get_variables_is_exact_level_only(self, adapter):
        adapter.set_variable("ROOT", "r")
        adapter.set_variable("ORG", "o", organisation="acme")
        adapter.set_variable("PROJ", "p", organisation="acme", project="webapp")
        adapter.set_variable("A", "1", organisation="acme", project="webapp", environment="dev")
        adapter.set_variable("B", "2", organisation="acme", project="webapp", environment="dev")
        adapter.set_variable("SVC", "s", **FULL)

        def as_dict(**level):
            return {v.name: v.value for v in adapter.get_variables(**level)}

        assert as_dict() == {"ROOT": "r"}
        assert as_dict(organisation="acme") == {"ORG": "o"}
        assert as_dict(organisation="acme", project="webapp") == {"PROJ": "p"}
        assert as_dict(organisation="acme", project="webapp", environment="dev") == {
            "A": "1",
            "B": "2",
        }
        assert as_dict(**FULL) == {"SVC": "s"}

    def test_get_variables_empty_level(self, adapter):
        assert adapter.get_variables(organisation="ghost") == []

    def test_set_variables_batch_and_empty(self, adapter):
        adapter.set_variables([], **FULL)
        assert adapter.get_variables(**FULL) == []
        adapter.set_variables(
            [Variable(name="A", value="1"), Variable(name="B", value="2")], **FULL
        )
        assert {v.name: v.value for v in adapter.get_variables(**FULL)} == {"A": "1", "B": "2"}

    def test_many_variables_are_all_returned(self, adapter):
        """More than SSM's 10-per-page limit."""
        adapter.set_variables([Variable(name=f"V{i}", value=str(i)) for i in range(25)])
        assert len(adapter.get_variables()) == 25

    def test_delete_variable(self, adapter):
        adapter.set_variable("KEY", "v", **FULL)
        assert adapter.delete_variable("KEY", **FULL) is True
        assert adapter.get_variable("KEY", **FULL) is None
        assert adapter.delete_variable("KEY", **FULL) is False

    def test_delete_variable_keeps_siblings_and_same_name_elsewhere(self, adapter):
        adapter.set_variables([Variable(name="A", value="1"), Variable(name="B", value="2")])
        adapter.set_variable("A", "other", organisation="acme")
        adapter.delete_variable("A")
        assert adapter.get_variable("B") == "2"
        assert adapter.get_variable("A", organisation="acme") == "other"

    def test_delete_variables(self, adapter):
        adapter.set_variables([Variable(name=f"V{i}", value="x") for i in range(12)], **FULL)
        names = [f"V{i}" for i in range(12)] + ["MISSING"]
        result = adapter.delete_variables(names, **FULL)
        assert sorted(result["deleted"]) == sorted(names[:12])
        assert result["not_found"] == ["MISSING"]
        assert adapter.get_variables(**FULL) == []

    def test_delete_variables_empty_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.delete_variables([])

    def test_list_hierarchy(self, adapter):
        adapter.set_variable("ROOT", "x")
        adapter.set_variable("K", "v", organisation="acme")
        adapter.set_variable("K", "v", organisation="globex", project="p1")
        adapter.set_variable("K", "v", organisation="acme", project="webapp", environment="dev")
        adapter.set_variable(
            "K", "v", organisation="acme", project="webapp", environment="prod"
        )
        adapter.set_variable("K", "v", **FULL)
        adapter.set_variable("K", "v", **{**FULL, "service": "worker"})

        assert sorted(adapter.get_organisations()) == ["acme", "globex"]
        assert sorted(adapter.get_projects("acme")) == ["webapp"]
        assert sorted(adapter.get_projects("globex")) == ["p1"]
        assert sorted(adapter.get_environments("acme", "webapp")) == ["dev", "prod"]
        assert sorted(adapter.get_services("acme", "webapp", "dev")) == ["api", "worker"]
        assert sorted(adapter.get_services("acme", "webapp", "prod")) == []
        assert adapter.get_projects("ghost") == []

    def test_hierarchy_listing_after_delete(self, adapter):
        adapter.set_variable("K", "v", organisation="acme", project="webapp")
        adapter.delete_variable("K", organisation="acme", project="webapp")
        assert sorted(adapter.get_projects("acme")) == []

    @pytest.mark.parametrize(
        "value",
        [
            "line1\nline2\n",
            "päss wörd ✓",
            " \"quoted\" 'x' ",
            "  padded  ",
            "a=b#c $HOME \\n",
            "x" * 1000,
        ],
    )
    def test_values_round_trip_exactly(self, adapter, value):
        adapter.set_variable("KEY", value, organisation="acme")
        assert adapter.get_variable("KEY", organisation="acme") == value
        assert [v.value for v in adapter.get_variables(organisation="acme")] == [value]

    def test_empty_name_is_rejected(self, adapter):
        with pytest.raises(ValueError):
            adapter.set_variable("", "v")

    def test_works_through_manager(self, adapter):
        manager = EnvironmentStoreManager(adapter=adapter)
        manager.set_variables({"A": "1", "B": "2"}, organisation="acme")
        assert manager.get_variable("A", organisation="acme") == "1"
        assert manager.get_resolved_variables(organisation="acme") == manager.get_variables(
            organisation="acme"
        )
        assert manager.delete_level(organisation="acme", confirm="acme") == 2
        assert manager.get_organisations() == []

    def test_deleting_the_last_variable_removes_the_level(self, adapter):
        adapter.set_variable("K", "v", **FULL)
        adapter.delete_variable("K", **FULL)
        assert adapter.get_organisations() == []


class StrictCreateUpdateContract:
    """Extra behaviour for adapters that implement create_variable, update_variable, variable_exists."""

    def test_create_and_update_are_strict(self, adapter):
        with pytest.raises(VariableNotFoundError):
            adapter.update_variable("K", "v")
        adapter.create_variable("K", "v")
        with pytest.raises(VariableExistsError):
            adapter.create_variable("K", "v2")
        adapter.update_variable("K", "v3")
        assert adapter.get_variable("K") == "v3"

    def test_variable_exists(self, adapter):
        adapter.set_variable("KEY", "v")
        assert adapter.variable_exists("KEY") is True
        assert adapter.variable_exists("NOPE") is False
