import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from environment_store.adapters.postgresql import PostgreSQLAdapter
from environment_store.core.exceptions import VariableExistsError, VariableNotFoundError
from environment_store.core.schemas import Variable

LEVELS = [
    {},
    {"organisation": "acme"},
    {"organisation": "acme", "project": "webapp"},
    {"organisation": "acme", "project": "webapp", "environment": "dev"},
    {"organisation": "acme", "project": "webapp", "environment": "dev", "service": "api"},
]


class TestPostgreSQLAdapter:
    def test_accepts_database_url(self, engine):
        adapter = PostgreSQLAdapter(engine.url.render_as_string(hide_password=False))
        adapter.set_variable("A", "1")
        assert adapter.get_variable("A") == "1"
        adapter.engine.dispose()

    @pytest.mark.parametrize("level", LEVELS)
    def test_set_and_get_variable_at_every_level(self, adapter, level):
        adapter.set_variable("KEY", "value", **level)
        assert adapter.get_variable("KEY", **level) == "value"
        assert adapter.variable_exists("KEY", **level)

    def test_get_variable_missing_returns_none(self, adapter):
        assert adapter.get_variable("NOPE") is None
        assert adapter.get_variable("NOPE", organisation="acme") is None
        assert not adapter.variable_exists("NOPE")

    def test_levels_are_isolated(self, adapter):
        for i, level in enumerate(LEVELS):
            adapter.set_variable("KEY", str(i), **level)
        for i, level in enumerate(LEVELS):
            assert adapter.get_variable("KEY", **level) == str(i)
            assert adapter.get_variables(**level) == [Variable(name="KEY", value=str(i))]

    def test_set_variable_overwrites_without_duplicating(self, adapter):
        adapter.set_variable("KEY", "one")
        adapter.set_variable("KEY", "two")
        adapter.set_variable("KEY", "one", organisation="acme")
        adapter.set_variable("KEY", "two", organisation="acme")
        assert adapter.get_variables() == [Variable(name="KEY", value="two")]
        assert adapter.get_variables(organisation="acme") == [Variable(name="KEY", value="two")]

    def test_set_variables_and_get_variables_sorted(self, adapter):
        adapter.set_variables(
            [Variable(name="B", value="2"), Variable(name="A", value="1")],
            organisation="acme",
            project="webapp",
        )
        assert adapter.get_variables(organisation="acme", project="webapp") == [
            Variable(name="A", value="1"),
            Variable(name="B", value="2"),
        ]

    def test_set_variables_is_atomic(self, adapter):
        with pytest.raises(ValueError):
            adapter.set_variables(
                [Variable(name="A", value="1"), Variable(name=" ", value="2")]
            )
        assert adapter.get_variables() == []

    @pytest.mark.parametrize("name", ["", "   "])
    def test_empty_name_rejected(self, adapter, name):
        with pytest.raises(ValueError):
            adapter.set_variable(name, "x")
        with pytest.raises(ValueError):
            adapter.create_variable(name, "x")
        with pytest.raises(ValueError):
            adapter.update_variable(name, "x")

    def test_get_variables_empty(self, adapter):
        assert adapter.get_variables() == []
        assert adapter.get_variables(organisation="missing") == []

    def test_variable_without_value_row_is_skipped(self, adapter, engine):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO environment_store (organization) VALUES ('acme')"))
        assert adapter.get_variables(organisation="acme") == []

    def test_delete_variable(self, adapter):
        adapter.set_variable("KEY", "root")
        adapter.set_variable("KEY", "org", organisation="acme")
        assert adapter.delete_variable("KEY", organisation="acme") is True
        assert adapter.delete_variable("KEY", organisation="acme") is False
        assert adapter.get_variable("KEY") == "root"

    def test_delete_variable_only_deletes_exact_name(self, adapter):
        adapter.set_variables(
            [Variable(name="A", value="1"), Variable(name="B", value="2")], organisation="acme"
        )
        assert adapter.delete_variable("A", organisation="acme")
        assert adapter.get_variables(organisation="acme") == [Variable(name="B", value="2")]

    def test_delete_variables(self, adapter):
        adapter.set_variables(
            [Variable(name="A", value="1"), Variable(name="B", value="2")], organisation="acme"
        )
        result = adapter.delete_variables(["A", "C", "B"], organisation="acme")
        assert result == {"deleted": ["A", "B"], "not_found": ["C"]}
        assert adapter.get_variables(organisation="acme") == []

    def test_delete_variables_empty_list(self, adapter):
        assert adapter.delete_variables([]) == {"deleted": [], "not_found": []}

    def test_hierarchy_listing(self, adapter):
        adapter.set_variable("A", "1", organisation="zeta")
        adapter.set_variable("A", "1", organisation="acme", project="web")
        adapter.set_variable("A", "1", organisation="acme", project="api")
        adapter.set_variable("A", "1", organisation="acme", project="web", environment="prod")
        adapter.set_variable("A", "1", organisation="acme", project="web", environment="dev")
        adapter.set_variable(
            "A", "1", organisation="acme", project="web", environment="dev", service="worker"
        )
        adapter.set_variable(
            "A", "1", organisation="acme", project="web", environment="dev", service="api"
        )
        assert adapter.get_organisations() == ["acme", "zeta"]
        assert adapter.get_projects("acme") == ["api", "web"]
        assert adapter.get_environments("acme", "web") == ["dev", "prod"]
        assert adapter.get_services("acme", "web", "dev") == ["api", "worker"]

    def test_hierarchy_listing_empty(self, adapter):
        assert adapter.get_organisations() == []
        assert adapter.get_projects("acme") == []
        assert adapter.get_environments("acme", "web") == []
        assert adapter.get_services("acme", "web", "dev") == []

    def test_listing_does_not_leak_between_parents(self, adapter):
        adapter.set_variable("A", "1", organisation="acme", project="web")
        adapter.set_variable("A", "1", organisation="other", project="shop")
        assert adapter.get_projects("acme") == ["web"]
        assert adapter.get_projects("other") == ["shop"]

    def test_create_variable(self, adapter):
        adapter.create_variable("KEY", "value", organisation="acme")
        assert adapter.get_variable("KEY", organisation="acme") == "value"

    @pytest.mark.parametrize("level", LEVELS)
    def test_create_variable_existing_raises(self, adapter, level):
        adapter.create_variable("KEY", "value", **level)
        with pytest.raises(VariableExistsError):
            adapter.create_variable("KEY", "other", **level)
        assert adapter.get_variable("KEY", **level) == "value"

    def test_create_variable_invalid_hierarchy_reraises(self, adapter):
        with pytest.raises(IntegrityError):
            adapter.create_variable("KEY", "value", project="webapp")

    def test_update_variable(self, adapter):
        adapter.set_variable("KEY", "old", organisation="acme")
        adapter.update_variable("KEY", "new", organisation="acme")
        assert adapter.get_variable("KEY", organisation="acme") == "new"

    def test_update_variable_missing_raises(self, adapter):
        with pytest.raises(VariableNotFoundError):
            adapter.update_variable("KEY", "new", organisation="acme")

    def test_update_variable_does_not_touch_other_levels(self, adapter):
        adapter.set_variable("KEY", "root")
        adapter.set_variable("KEY", "org", organisation="acme")
        adapter.update_variable("KEY", "changed", organisation="acme")
        assert adapter.get_variable("KEY") == "root"

    def test_secret_flag_is_preserved_on_upsert(self, adapter, engine):
        adapter.set_variable("KEY", "one")
        with engine.begin() as conn:
            conn.execute(text("UPDATE environment_store SET is_secret = true"))
        adapter.set_variable("KEY", "two")
        with engine.connect() as conn:
            row = conn.execute(text("SELECT var_value, is_secret FROM environment_store")).one()
        assert tuple(row) == ("two", True)
