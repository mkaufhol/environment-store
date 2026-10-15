"""Contract tests run against both AWS adapters using moto."""

import json

import boto3
import pytest
from moto import mock_aws

from environment_store.adapters.aws.secrets_manager import SecretsManagerAdapter
from environment_store.adapters.aws.secrets_manager.adapter import MAX_SECRET_SIZE
from environment_store.adapters.aws.ssm_parameter_store import ParameterStoreAdapter
from environment_store.core.schemas import Variable
from tests.environment_store.adapters.contract import (
    AdapterContract,
    StrictCreateUpdateContract,
)

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


@pytest.fixture(params=["ssm", "ssm-prefix", "secrets", "secrets-prefix"])
def adapter(request):
    with mock_aws():
        if request.param == "ssm":
            yield ParameterStoreAdapter(region="us-east-1")
        elif request.param == "ssm-prefix":
            yield ParameterStoreAdapter(region="us-east-1", prefix="/myapp/config")
        elif request.param == "secrets":
            yield SecretsManagerAdapter(region="us-east-1")
        else:
            yield SecretsManagerAdapter(region="us-east-1", prefix="myapp/config")


class TestAdapterContract(AdapterContract, StrictCreateUpdateContract):
    """The shared contract, run against every AWS adapter flavour."""

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

    def _secret_names(self, adapter):
        return [s["Name"] for s in adapter.secrets_manager.client.list_secrets()["SecretList"]]

    def _secret_data(self, adapter, name="app"):
        client = adapter.secrets_manager.client
        return json.loads(client.get_secret_value(SecretId=name)["SecretString"])

    def test_single_json_secret_for_all_levels(self, adapter):
        adapter.set_variable("ROOT", "r")
        adapter.set_variable("ORG", "o", organisation="acme")
        adapter.set_variables(
            [Variable(name="A", value="1"), Variable(name="B", value="2")], **FULL
        )
        assert self._secret_names(adapter) == ["app"]
        assert self._secret_data(adapter) == {
            "ROOT": "r",
            "acme/ORG": "o",
            "acme/webapp/dev/api/A": "1",
            "acme/webapp/dev/api/B": "2",
        }

    def test_default_prefix(self):
        with mock_aws():
            adapter = SecretsManagerAdapter(region="us-east-1")
            adapter.set_variable("K", "v", organisation="acme")
            assert self._secret_names(adapter) == ["environment-store"]
            assert self._secret_data(adapter, "environment-store") == {"acme/K": "v"}

    def test_nested_prefix_is_secret_name(self):
        with mock_aws():
            adapter = SecretsManagerAdapter(region="us-east-1", prefix="/myapp/config/")
            adapter.set_variable("K", "v", **FULL)
            assert self._secret_names(adapter) == ["myapp/config"]
            assert self._secret_data(adapter, "myapp/config") == {"acme/webapp/dev/api/K": "v"}

    def test_prefixes_are_separate_stores(self, adapter):
        other = SecretsManagerAdapter(prefix="other", secrets_manager=adapter.secrets_manager)
        adapter.set_variable("K", "app", organisation="acme")
        other.set_variable("K", "other", organisation="globex")
        assert adapter.get_organisations() == ["acme"]
        assert other.get_organisations() == ["globex"]
        assert other.get_variable("K", organisation="acme") is None

    def test_empty_store_secret_is_removed_and_name_reusable(self, adapter):
        adapter.set_variable("K", "v", organisation="acme")
        adapter.set_variable("K", "v", organisation="globex")
        adapter.delete_variable("K", organisation="acme")
        assert self._secret_names(adapter) == ["app"]
        adapter.delete_variable("K", organisation="globex")
        assert self._secret_names(adapter) == []
        adapter.set_variable("K", "again", organisation="acme")
        assert adapter.get_variable("K", organisation="acme") == "again"

    def test_delete_duplicate_names(self, adapter):
        adapter.set_variable("K", "v")
        assert adapter.delete_variables(["K", "K"]) == {"deleted": ["K", "K"], "not_found": []}
        assert adapter.get_variable("K") is None

    def test_non_object_secret_raises(self, adapter):
        adapter.secrets_manager.client.create_secret(Name="app", SecretString='["x"]')
        with pytest.raises(TypeError):
            adapter.get_variables(organisation="acme")

    def test_too_large_store_raises_and_keeps_data(self, adapter):
        adapter.set_variable("K", "v")
        with pytest.raises(ValueError, match="65536 bytes"):
            adapter.set_variable("BIG", "x" * MAX_SECRET_SIZE)
        assert self._secret_data(adapter) == {"K": "v"}

    def test_ignores_other_secrets(self, adapter):
        client = boto3.client("secretsmanager", region_name="us-east-1")
        client.create_secret(Name="app-other", SecretString='{"x/K": "1"}')
        client.create_secret(Name="app/legacy", SecretString='{"K": "1"}')
        adapter.set_variable("K", "v", organisation="acme")
        assert adapter.get_organisations() == ["acme"]
