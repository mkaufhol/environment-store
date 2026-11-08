from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st
from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict

from environment_store.adapters.postgres.url import (
    DEFAULT_SCHEMA,
    SCHEMA_PATTERN,
    PostgresTarget,
    parse_url,
)
from environment_store.core.errors import ValidationError

_PASSWORD: Final = "s3cr3t-pw"  # noqa: S105 - test value that must never show


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
def test_every_name_matching_the_schema_rule_is_accepted(schema: str) -> None:
    assert parse_url(f"postgresql://host/db?schema={schema}").schema == schema


def test_schema_rule_is_pinned() -> None:
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
        (f"postgresql://host/db?sslpassword={_PASSWORD}", (_PASSWORD,)),
        ("postgresql://host/db?sslpassword=k%25ey", ("k%ey", "k%25ey")),
        ("postgresql://u:a@host/db?password=b&sslpassword=c", ("a", "b", "c")),
    ],
    ids=[
        "none",
        "user-only",
        "userinfo",
        "userinfo-escaped",
        "query",
        "query-escaped",
        "empty",
        "sslpassword",
        "sslpassword-escaped",
        "all-three",
    ],
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


def test_target_validates_the_schema_name_itself() -> None:
    with pytest.raises(ValidationError, match="schema"):
        PostgresTarget(
            conninfo="postgresql://h/db", schema="Bad Name; --", location="l", secrets=()
        )


def test_target_requires_a_tuple_of_secrets() -> None:
    with pytest.raises(ValidationError, match="secrets"):
        PostgresTarget(
            conninfo="postgresql://h/db",
            schema="s",
            location="l",
            secrets=["pw"],  # ty: ignore[invalid-argument-type] - the wrong type on purpose
        )


# --- malformed connection strings ----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        f"postgres://user:{_PASSWORD}@[::1/db",
        "postgresql://[bad/db",
        f"postgresql://u:{_PASSWORD}@h1,[::1/db",
        f"postgresql://u:{_PASSWORD}\x00x@h/db",
        f"postgresql://u:{_PASSWORD}@h/d\udcffb",
        f"postgresql://u:{_PASSWORD}/tail@h:1/db",
        f"postgresql://u:{_PASSWORD}@tail@h:1/db",
        f"postgresql://u:{_PASSWORD}?tail@h/db",
        "postgresql://host?application_name=a@b",
        f"postgresql://u:{_PASSWORD}%F2x@h/db",
        "postgresql://h/db?application_name=%C3%28",
    ],
    ids=[
        "unclosed-ipv6",
        "unclosed-ipv6-no-credentials",
        "unclosed-ipv6-second-host",
        "nul",
        "lone-surrogate",
        "unencoded-slash-in-password",
        "unencoded-at-in-password",
        "unencoded-question-mark-in-password",
        "at-in-query-without-path",
        "escape-not-utf8-in-password",
        "escape-not-utf8-in-query",
    ],
)
def test_malformed_urls_raise_validation_error_without_the_password(url: str) -> None:
    with pytest.raises(ValidationError) as caught:
        parse_url(url)

    assert _PASSWORD not in str(caught.value)
    assert _PASSWORD not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ("url", "password"),
    [
        (f"postgresql://u:{_PASSWORD}\uff03x@h.invalid/db", f"{_PASSWORD}\uff03x"),
        (f"postgresql://user:{_PASSWORD}@ho\uff0fst/db", _PASSWORD),
    ],
    ids=["fullwidth-hash-in-password", "fullwidth-slash-in-host"],
)
def test_non_ascii_credentials_and_hosts_are_left_to_libpq(url: str, password: str) -> None:
    # Characters that change under NFKC are fine for libpq; only urllib refuses them.
    target = parse_url(url)

    assert password in target.secrets
    assert _PASSWORD not in target.location


def test_unencoded_credentials_get_a_percent_encoding_hint() -> None:
    with pytest.raises(ValidationError, match="percent-encode"):
        parse_url(f"postgresql://u:{_PASSWORD}@tail@h/db")


@pytest.mark.parametrize(
    ("url", "password", "location"),
    [
        ("postgresql://u:p#ss@h/db", "p#ss", "schema 'environment_store' of database 'db'"),
        ("postgresql://u:pa[ss@h/db", "pa[ss", "schema 'environment_store' of database 'db'"),
        ("postgresql://u:a:b@h/db", "a:b", "schema 'environment_store' of database 'db'"),
        ("postgresql://u:p%2Fs@h/db", "p/s", "schema 'environment_store' of database 'db'"),
        ("postgresql://h/db#frag", None, "schema 'environment_store' of database 'db#frag'"),
        ("postgresql://h/db?dbname=other", None, "schema 'environment_store' of database 'other'"),
        (
            "postgresql://u:pw@h1,[::1]:5/db?schema=s",
            "pw",
            "schema 's' of database 'db'",
        ),
    ],
    ids=["hash", "bracket", "colon", "escaped-slash", "fragment", "dbname-param", "multi-host"],
)
def test_credentials_and_database_are_found_where_libpq_finds_them(
    url: str, password: str | None, location: str
) -> None:
    target = parse_url(url)

    assert target.location == location
    if password is not None:
        assert password in target.secrets
    assert "schema=" not in target.conninfo


_URL_PART: Final = st.text(alphabet="ab:/@?#[],=&%2F", max_size=12)


@given(userinfo=_URL_PART, rest=_URL_PART)
def test_password_and_database_agree_with_libpq(userinfo: str, rest: str) -> None:
    url = f"postgresql://{userinfo}@{rest}"
    try:
        target = parse_url(url)
    except ValidationError:
        return
    try:
        libpq = conninfo_to_dict(target.conninfo)
    except ProgrammingError:
        return

    password = libpq.get("password")
    if password:
        assert password in target.secrets
    database = libpq.get("dbname")
    if database:
        assert target.location.endswith(f"of database {database!r}")
    else:
        assert target.location.endswith("of the default database")
