import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.adapters.postgres.url import (
    DEFAULT_SCHEMA,
    SCHEMA_PATTERN,
    PostgresTarget,
    parse_url,
)
from environment_store.core.errors import ValidationError

_PASSWORD = "s3cr3t-pw"  # noqa: S105 - test value that must never show


def test_default_schema_is_environment_store() -> None:
    assert DEFAULT_SCHEMA == "environment_store"
    assert parse_url("postgresql://host/db").schema == "environment_store"


@pytest.mark.parametrize(
    ("url", "schema", "conninfo"),
    [
        ("postgresql://host/db?schema=team_a", "team_a", "postgresql://host/db"),
        (
            "postgresql://u:p@host:5432/db?sslmode=require&schema=b&connect_timeout=3",
            "b",
            "postgresql://u:p@host:5432/db?sslmode=require&connect_timeout=3",
        ),
        ("postgres://host/db?schema=_x", "_x", "postgres://host/db"),
        ("PostgreSQL://host/db", DEFAULT_SCHEMA, "postgresql://host/db"),
        (
            "postgresql:///db?host=%2Ftmp%2Fs&port=5",
            DEFAULT_SCHEMA,
            "postgresql:///db?host=%2Ftmp%2Fs&port=5",
        ),
    ],
    ids=["only-schema", "schema-between-params", "postgres-scheme", "uppercase-scheme", "socket"],
)
def test_schema_parameter_is_removed_before_the_driver_sees_the_url(
    url: str, schema: str, conninfo: str
) -> None:
    target = parse_url(url)

    assert target.schema == schema
    assert target.conninfo == conninfo


def test_other_query_parameters_are_kept_byte_for_byte() -> None:
    # '+' and percent escapes mean something else to libpq than to HTML forms.
    target = parse_url("postgresql://host/db?password=a+b%2Bc&schema=s&options=-c%20x=1")

    assert target.conninfo == "postgresql://host/db?password=a+b%2Bc&options=-c%20x=1"


def test_schema_parameter_is_percent_decoded() -> None:
    assert parse_url("postgresql://host/db?schema=team%5Fa").schema == "team_a"


@pytest.mark.parametrize(
    "schema",
    [
        "",
        "A",
        "Team",
        "1abc",
        "a-b",
        "a.b",
        "public.x",
        'a"; DROP SCHEMA public CASCADE; --',
        "a%22b",
        "a%00",
        "a%0A",
        "x" * 64,
        "café",
        "a b",
        "a+b",
    ],
)
def test_invalid_schema_names_are_rejected(schema: str) -> None:
    with pytest.raises(ValidationError, match="schema"):
        parse_url(f"postgresql://host/db?schema={schema}")


@given(schema=st.from_regex(SCHEMA_PATTERN, fullmatch=True))
def test_every_name_matching_the_spec_rule_is_accepted(schema: str) -> None:
    assert parse_url(f"postgresql://host/db?schema={schema}").schema == schema


def test_schema_rule_is_the_spec_regex() -> None:
    assert SCHEMA_PATTERN.pattern == r"[a-z_][a-z0-9_]{0,62}"


def test_trailing_newline_in_schema_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_url("postgresql://host/db?schema=abc%0A")


def test_schema_given_twice_is_rejected() -> None:
    with pytest.raises(ValidationError, match="once"):
        parse_url("postgresql://host/db?schema=a&schema=b")


@pytest.mark.parametrize(
    "url", ["sqlite:///x.db", "json://dir", "postgresql:/host/db", "host=localhost dbname=x"]
)
def test_urls_that_are_not_postgresql_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError, match="postgresql://"):
        parse_url(url)


@pytest.mark.parametrize(
    "url",
    [
        f"postgresql://user:{_PASSWORD}@host/db?schema=BAD",
        f"postgresql://user:{_PASSWORD}@host/db?schema=a&schema=b",
        f"mysql://user:{_PASSWORD}@host/db",
    ],
)
def test_errors_never_repeat_the_password(url: str) -> None:
    with pytest.raises(ValidationError) as caught:
        parse_url(url)

    assert _PASSWORD not in str(caught.value)


@pytest.mark.parametrize(
    ("url", "secrets"),
    [
        ("postgresql://host/db", ()),
        ("postgresql://user@host/db", ()),
        (f"postgresql://user:{_PASSWORD}@host/db", (_PASSWORD,)),
        ("postgresql://user:p%40ss@host/db", ("p@ss", "p%40ss")),
        (f"postgresql://host/db?password={_PASSWORD}", (_PASSWORD,)),
        ("postgresql://host/db?password=a%2Bb", ("a+b", "a%2Bb")),
        ("postgresql://user:@host/db?password=", ()),
    ],
    ids=["none", "user-only", "userinfo", "userinfo-escaped", "query", "query-escaped", "empty"],
)
def test_target_knows_the_passwords_to_redact(url: str, secrets: tuple[str, ...]) -> None:
    assert set(parse_url(url).secrets) == set(secrets)


def test_redact_replaces_every_password_occurrence() -> None:
    target = parse_url(f"postgresql://user:{_PASSWORD}@host/db")

    assert target.redact(f"failed for {_PASSWORD}, again {_PASSWORD}") == (
        "failed for ***, again ***"
    )


def test_target_repr_hides_the_connection_string() -> None:
    target = parse_url(f"postgresql://user:{_PASSWORD}@host/db")

    assert _PASSWORD not in repr(target)
    assert "environment_store" in repr(target)


@pytest.mark.parametrize(
    ("url", "location"),
    [
        ("postgresql://host/app_db?schema=team_a", "schema 'team_a' of database 'app_db'"),
        ("postgresql://host?schema=s", "schema 's' of the default database"),
        ("postgresql://host/my%20db", "schema 'environment_store' of database 'my db'"),
    ],
)
def test_location_names_schema_and_database_but_no_credentials(url: str, location: str) -> None:
    assert parse_url(url).location == location


def test_target_is_a_value_object() -> None:
    target = parse_url("postgresql://host/db?schema=s")

    assert target == PostgresTarget(
        conninfo="postgresql://host/db", schema="s", location=target.location, secrets=()
    )
    with pytest.raises(AttributeError):
        target.schema = "other"  # ty: ignore[invalid-assignment] - frozen on purpose
