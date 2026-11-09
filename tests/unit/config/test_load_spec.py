"""The `ENV_STORE_LOAD` value: building, encoding, decoding and reading it from the environment.

A load specification names the stores to load, in order, and the secret of every encrypted
one. Its text is one line, versioned and URL-safe; decoding refuses anything else and never
echoes the value.
"""

import base64
import json
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.config.load_spec import (
    ENV_LOAD,
    LOAD_SPEC_PREFIX,
    LoadSpec,
    decode_load_spec,
    load_spec_from_environment,
)
from environment_store.core.errors import ConfigurationError, ValidationError
from environment_store.core.secrets import KeyMaterial, Passphrase, Secret
from environment_store.crypto.keyfile import format_key
from tests.support.strategies import store_names

KEY: Final = KeyMaterial(key=b"\x07" * 32)
KEY_TEXT: Final = format_key(KEY).rstrip("\n")
PASSPHRASE: Final = Passphrase(text="correct horse battery staple")
CANARY: Final = "do-not-echo-this-value"


def _encoded(payload: object) -> str:
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return LOAD_SPEC_PREFIX + base64.urlsafe_b64encode(data).decode().rstrip("=")


def _secrets() -> st.SearchStrategy[Secret]:
    keys = st.binary(min_size=32, max_size=32).map(lambda raw: KeyMaterial(key=raw))
    texts = st.text(st.characters(exclude_categories=["Cs"]), min_size=1)
    return st.one_of(keys, texts.map(lambda text: Passphrase(text=text)))


@st.composite
def load_specs(draw: st.DrawFn) -> LoadSpec:
    stores = tuple(draw(st.lists(store_names(), min_size=1, max_size=6)))
    keyed = draw(st.lists(st.sampled_from(stores), unique=True))
    return LoadSpec(stores=stores, keys={name: draw(_secrets()) for name in keyed})


# --- building  ------------------------------------------------------------------------------------


def test_spec_keeps_the_store_order_and_repeats() -> None:
    spec = LoadSpec(stores=("base", "app", "base"))

    assert spec.stores == ("base", "app", "base")
    assert dict(spec.keys) == {}


def test_spec_keys_are_a_read_only_copy() -> None:
    keys: dict[str, Secret] = {"app": KEY}
    spec = LoadSpec(stores=("app",), keys=keys)
    keys["app"] = PASSPHRASE

    assert spec.keys["app"] == KEY
    with pytest.raises(TypeError):
        spec.keys["app"] = PASSPHRASE  # ty: ignore[invalid-assignment] - proves it is read-only


def test_spec_without_stores_is_refused() -> None:
    with pytest.raises(ValidationError, match="at least one store"):
        LoadSpec(stores=())


def test_spec_refuses_an_invalid_store_name() -> None:
    with pytest.raises(ValidationError, match="Bad"):
        LoadSpec(stores=("Bad",))


def test_spec_refuses_a_key_for_a_store_it_does_not_load() -> None:
    with pytest.raises(ValidationError, match="'other', which it does not load"):
        LoadSpec(stores=("app",), keys={"other": KEY})


def test_spec_refuses_a_key_that_is_not_a_secret() -> None:
    with pytest.raises(ValidationError, match="KeyMaterial or a Passphrase"):
        LoadSpec(stores=("app",), keys={"app": CANARY})  # ty: ignore[invalid-argument-type] - wrong type on purpose


def test_spec_repr_hides_the_secrets() -> None:
    spec = LoadSpec(stores=("app",), keys={"app": Passphrase(text=CANARY)})

    assert CANARY not in repr(spec)
    assert "app" in repr(spec)


# --- encoding  ------------------------------------------------------------------------------------


@given(load_specs())
def test_encoding_round_trips(spec: LoadSpec) -> None:
    assert LoadSpec.decode(spec.encode()) == spec


@given(load_specs())
def test_encoding_is_one_url_safe_line_without_padding(spec: LoadSpec) -> None:
    text = spec.encode()

    assert text.startswith(LOAD_SPEC_PREFIX)
    body = text.removeprefix(LOAD_SPEC_PREFIX)
    assert body
    assert set(body) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def test_passphrases_keep_every_character() -> None:
    passphrase = Passphrase(text=" two\nlines \r\n")
    spec = LoadSpec(stores=("app",), keys={"app": passphrase})

    assert LoadSpec.decode(spec.encode()).keys["app"] == passphrase


def test_encoding_is_deterministic() -> None:
    first = LoadSpec(stores=("a", "b"), keys={"b": KEY, "a": PASSPHRASE})
    second = LoadSpec(stores=("a", "b"), keys={"a": PASSPHRASE, "b": KEY})

    assert first.encode() == second.encode()


def test_encoding_stores_a_key_as_key_file_text() -> None:
    text = LoadSpec(stores=("app",), keys={"app": KEY}).encode()

    body = text.removeprefix(LOAD_SPEC_PREFIX)
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert payload == {"stores": ["app"], "keys": {"app": {"key": KEY_TEXT}}}


# --- decoding  ------------------------------------------------------------------------------------


def test_decoding_accepts_surrounding_whitespace() -> None:
    spec = LoadSpec(stores=("app",), keys={"app": KEY})

    assert LoadSpec.decode(f"  {spec.encode()}\n") == spec


_VALID: Final = {"stores": ["app"], "keys": {"app": {"passphrase": CANARY}}}


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "it must start with 'envstore-load-v1:'"),
        (CANARY, "it must start with 'envstore-load-v1:'"),
        ("envstore-load-v2:" + _encoded(_VALID)[17:], "it was made by a newer version"),
        ("envstore-load-v" + "9" * 5000 + ":x", "it was made by a newer version"),
        ("envstore-load-v01:x", "it must start with 'envstore-load-v1:'"),
        (LOAD_SPEC_PREFIX, "nothing follows"),
        (LOAD_SPEC_PREFIX + "ab+/", "not URL-safe base64"),
        (LOAD_SPEC_PREFIX + "abcd=", "not URL-safe base64"),
        (LOAD_SPEC_PREFIX + "abcde", "not URL-safe base64"),
        (LOAD_SPEC_PREFIX + "abd", "not URL-safe base64"),
        (_encoded(b"\xff\xfe"), "not UTF-8 JSON"),
        (_encoded(b"{not json"), "not UTF-8 JSON"),
        (_encoded(b"[" * 100_000), "not UTF-8 JSON"),
        (_encoded(b'{"stores": ["app"], "stores": ["app"], "keys": {}}'), "repeats 'stores'"),
        (
            _encoded(b'{"stores": ["app"], "keys": {"Bad Name": 1, "Bad Name": 2}}'),
            "it repeats a field",
        ),
        (_encoded(["app"]), "an object with 'stores' and 'keys'"),
        (_encoded({"stores": ["app"]}), "an object with 'stores' and 'keys'"),
        (_encoded({**_VALID, "extra": 1}), "an object with 'stores' and 'keys'"),
        (_encoded({"stores": "app", "keys": {}}), "'stores' must be a list of store names"),
        (_encoded({"stores": [1], "keys": {}}), "'stores' must be a list of store names"),
        (
            _encoded({"stores": ["Bad", CANARY], "keys": {}}),
            "'stores' must be a list of store names",
        ),
        (_encoded({"stores": [], "keys": {}}), "at least one store"),
        (_encoded({"stores": ["app"], "keys": []}), "'keys' must map store names to secrets"),
        (
            _encoded({"stores": ["app"], "keys": {"app": {"pass": CANARY}}}),
            'the secret of store \'app\' must be {"key": ...} or {"passphrase": ...}',
        ),
        (
            _encoded({"stores": ["app"], "keys": {"app": {"key": KEY_TEXT, "passphrase": "x"}}}),
            'the secret of store \'app\' must be {"key": ...} or {"passphrase": ...}',
        ),
        (
            _encoded({"stores": ["app"], "keys": {"app": {"passphrase": 1}}}),
            'the secret of store \'app\' must be {"key": ...} or {"passphrase": ...}',
        ),
        (
            _encoded({"stores": ["app"], "keys": {"app": CANARY}}),
            'the secret of store \'app\' must be {"key": ...} or {"passphrase": ...}',
        ),
        (
            _encoded({"stores": ["app"], "keys": {"app": {"key": CANARY}}}),
            "the key of store 'app' is not valid key text",
        ),
        (
            _encoded({"stores": ["app"], "keys": {"app": {"passphrase": ""}}}),
            "the passphrase of store 'app' is empty",
        ),
        (
            _encoded({"stores": ["app"], "keys": {"other": {"passphrase": CANARY}}}),
            "a key for 'other', which it does not load",
        ),
        (
            _encoded({"stores": ["app"], "keys": {CANARY.upper(): {"passphrase": "x"}}}),
            "a key for a name, which it does not load",
        ),
    ],
)
def test_decoding_refuses_a_malformed_value(text: str, reason: str) -> None:
    with pytest.raises(ConfigurationError) as caught:
        decode_load_spec(text, what=ENV_LOAD)

    message = str(caught.value)
    assert message.startswith("ENV_STORE_LOAD is not a valid load specification: ")
    assert reason in message
    assert CANARY not in message
    # Not chained: a JSON or base64 error would carry the whole value.
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ or caught.value.__context__ is None


def test_public_decode_names_the_specification() -> None:
    with pytest.raises(ConfigurationError, match=r"^the text is not a valid load specification: "):
        LoadSpec.decode(CANARY)


def test_decoding_refuses_a_passphrase_with_a_lone_surrogate() -> None:
    text = _encoded(b'{"stores": ["app"], "keys": {"app": {"passphrase": "\\ud800"}}}')

    with pytest.raises(ConfigurationError, match="the passphrase of store 'app' is not valid"):
        decode_load_spec(text, what=ENV_LOAD)


# --- the environment variable  --------------------------------------------------------------------


def test_variable_name() -> None:
    assert ENV_LOAD == "ENV_STORE_LOAD"


@pytest.mark.parametrize("environ", [{}, {"ENV_STORE_LOAD": ""}])
def test_unset_or_empty_variable_gives_no_spec(environ: dict[str, str]) -> None:
    assert load_spec_from_environment(environ) is None


def test_variable_is_decoded() -> None:
    spec = LoadSpec(stores=("base", "app"), keys={"app": KEY})

    assert load_spec_from_environment({"ENV_STORE_LOAD": spec.encode()}) == spec


def test_variable_that_is_not_utf8_is_refused_without_echoing_it() -> None:
    environ = {"ENV_STORE_LOAD": LOAD_SPEC_PREFIX + "\udcff" + CANARY}

    with pytest.raises(ConfigurationError, match=r"^ENV_STORE_LOAD is not valid UTF-8$") as caught:
        load_spec_from_environment(environ)

    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
