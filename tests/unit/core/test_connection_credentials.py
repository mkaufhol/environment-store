import pytest

from environment_store.core.connection import CREDENTIAL_PARAMETERS, connection_has_credentials


def test_credential_parameters_are_the_libpq_secrets() -> None:
    assert frozenset({"password", "sslpassword"}) == CREDENTIAL_PARAMETERS


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:secret@host/db",
        "postgres://:secret@host/db",
        "postgresql://user@host/db?password=secret",
        "postgresql://host/db?sslmode=require&sslpassword=secret",
        "postgresql://host/db?pass%77ord=secret",
        "postgresql://host/db?%73slpassword=secret",
        "postgresql://host/db?password",
        "POSTGRESQL://user:secret@host/db",
        "postgresql://host/db?password=secret#fragment",
    ],
)
def test_connection_with_a_password_has_credentials(url: str) -> None:
    assert connection_has_credentials(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user@host/db",
        "postgresql://user:@host/db",
        "postgresql://host/db?sslmode=require&user=me",
        "postgresql://host/db?passwords=x",
        "postgresql://host/path:with@colon",
        "postgresql://host/db#password=x",
        "sqlite:///envs.db",
        "json://envs",
        "toml:///abs/dir",
        "",
        "host=db password=secret",
        "user:secret@host",
    ],
)
def test_connection_without_a_password_has_no_credentials(url: str) -> None:
    assert not connection_has_credentials(url)
