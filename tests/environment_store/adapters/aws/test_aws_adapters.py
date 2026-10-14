"""Contract tests run against both AWS adapters using moto."""

import json

import boto3
import pytest
from moto import mock_aws

from environment_store.adapters.aws.secrets_manager import SecretsManagerAdapter
from environment_store.adapters.aws.ssm_parameter_store import ParameterStoreAdapter
from environment_store.core import EnvironmentStoreManager
from environment_store.core.exceptions import VariableExistsError, VariableNotFoundError
from environment_store.core.schemas import Variable

FULL = {
    "organisation": "acme",
    "project": "webapp",
    "environment": "dev",
    "service": "api",
}


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SECURITY_TOKEN",
        "AWS_SESSION_TOKEN",
    ):
        monkeypatch.setenv(key, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(params=["ssm", "ssm-prefix", "secrets"])
def adapter(request):
    with mock_aws():
        if request.param == "ssm":
            yield ParameterStoreAdapter(region="us-east-1")
        elif request.param == "ssm-prefix":
            yield ParameterStoreAdapter(region="us-east-1", prefix="/myapp/config")
        else:
            yield SecretsManagerAdapter(region="us-east-1")


class TestAdapterContract:
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

        assert adapter.get_organisations() == ["acme", "globex"]
        assert adapter.get_projects("acme") == ["webapp"]
        assert adapter.get_projects("globex") == ["p1"]
        assert adapter.get_environments("acme", "webapp") == ["dev", "prod"]
        assert adapter.get_services("acme", "webapp", "dev") == ["api", "worker"]
        assert adapter.get_services("acme", "webapp", "prod") == []
        assert adapter.get_projects("ghost") == []

    def test_hierarchy_listing_after_delete(self, adapter):
        adapter.set_variable("K", "v", organisation="acme", project="webapp")
        adapter.delete_variable("K", organisation="acme", project="webapp")
        assert adapter.get_projects("acme") == []

    def test_variable_exists(self, adapter):
        adapter.set_variable("KEY", "v")
        assert adapter.variable_exists("KEY") is True
        assert adapter.variable_exists("NOPE") is False

    def test_invalid_inputs(self, adapter):
        with pytest.raises(ValueError):
            adapter.set_variable("bad/name", "v")
        with pytest.raises(ValueError):
            adapter.set_variable("", "v")
        with pytest.raises(ValueError):
            adapter.set_variable("K", "v", organisation="bad org")
        with pytest.raises(ValueError):
            adapter.get_variable("K", project="webapp")
        with pytest.raises(ValueError):
            adapter.get_variables(organisation="acme", environment="dev")

    def test_works_through_manager(self, adapter):
        manager = EnvironmentStoreManager(adapter=adapter)
        manager.set_variables({"A": "1", "B": "2"}, organisation="acme")
        assert manager.get_variable("A", organisation="acme") == "1"

    def test_create_and_update_are_strict(self, adapter):
        with pytest.raises(VariableNotFoundError):
            adapter.update_variable("K", "v")
        adapter.create_variable("K", "v")
        with pytest.raises(VariableExistsError):
            adapter.create_variable("K", "v2")
        adapter.update_variable("K", "v3")
        assert adapter.get_variable("K") == "v3"


class TestParameterStoreAdapter:
    @pytest.fixture
    def adapter(self):
        with mock_aws():
            yield ParameterStoreAdapter(region="us-east-1", prefix="app")

    def test_requires_region_or_store(self):
        with pytest.raises(ValueError):
            ParameterStoreAdapter()

    def test_path_layout_and_secure_string(self, adapter):
        adapter.set_variable("DB_HOST", "h", **FULL)
        param = adapter.parameter_store.client.get_parameter(
            Name="/app/acme/webapp/dev/api/DB_HOST"
        )["Parameter"]
        assert param["Type"] == "SecureString"

    def test_string_type(self):
        with mock_aws():
            adapter = ParameterStoreAdapter(region="us-east-1", parameter_type="String")
            adapter.set_variable("K", "v")
            param = adapter.parameter_store.client.get_parameter(Name="/K")["Parameter"]
            assert param["Type"] == "String"

    def test_ignores_parameters_outside_prefix(self, adapter):
        adapter.parameter_store.client.put_parameter(Name="/other/X", Value="1", Type="String")
        adapter.set_variable("K", "v", organisation="acme")
        assert adapter.get_organisations() == ["acme"]


class TestSecretsManagerAdapter:
    @pytest.fixture
    def adapter(self):
        with mock_aws():
            yield SecretsManagerAdapter(region="us-east-1", prefix="app")

    def test_requires_region_or_manager_and_prefix(self):
        with pytest.raises(ValueError):
            SecretsManagerAdapter()
        with pytest.raises(ValueError):
            SecretsManagerAdapter(region="us-east-1", prefix="/")

    def test_one_json_secret_per_level(self, adapter):
        adapter.set_variables(
            [Variable(name="A", value="1"), Variable(name="B", value="2")], **FULL
        )
        client = adapter.secrets_manager.client
        names = [s["Name"] for s in client.list_secrets()["SecretList"]]
        assert names == ["app/acme/webapp/dev/api"]
        value = client.get_secret_value(SecretId="app/acme/webapp/dev/api")["SecretString"]
        assert json.loads(value) == {"A": "1", "B": "2"}

    def test_root_secret_name_is_prefix(self, adapter):
        adapter.set_variable("K", "v")
        names = [s["Name"] for s in adapter.secrets_manager.client.list_secrets()["SecretList"]]
        assert names == ["app"]

    def test_empty_level_secret_is_removed_and_name_reusable(self, adapter):
        adapter.set_variable("K", "v", organisation="acme")
        adapter.delete_variable("K", organisation="acme")
        assert adapter.secrets_manager.client.list_secrets()["SecretList"] == []
        adapter.set_variable("K", "again", organisation="acme")
        assert adapter.get_variable("K", organisation="acme") == "again"

    def test_non_object_secret_raises(self, adapter):
        adapter.secrets_manager.client.create_secret(Name="app/acme", SecretString='["x"]')
        with pytest.raises(TypeError):
            adapter.get_variables(organisation="acme")

    def test_ignores_secrets_outside_prefix(self, adapter):
        boto3.client("secretsmanager", region_name="us-east-1").create_secret(
            Name="app-other/x", SecretString="{}"
        )
        adapter.set_variable("K", "v", organisation="acme")
        assert adapter.get_organisations() == ["acme"]
