"""Contract tests run against both AWS adapters using moto."""

import json

import boto3
import pytest
from moto import mock_aws

from environment_store.adapters.aws.secrets_manager import SecretsManagerAdapter
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


@pytest.fixture(params=["ssm", "ssm-prefix", "secrets"])
def adapter(request):
    with mock_aws():
        if request.param == "ssm":
            yield ParameterStoreAdapter(region="us-east-1")
        elif request.param == "ssm-prefix":
            yield ParameterStoreAdapter(region="us-east-1", prefix="/myapp/config")
        else:
            yield SecretsManagerAdapter(region="us-east-1")


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
