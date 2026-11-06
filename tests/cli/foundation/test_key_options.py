"""`-k` parsing for reading and writing commands (D3, D16, D33, PD 19)."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.cli.key_options import (
    parse_key_path,
    parse_reading_keys,
    parse_writing_key,
)
from environment_store.config.secrets import KeyFile, KeyStdin
from environment_store.core.errors import KeySourceError, ValidationError
from tests.support.strategies import store_names

# --- reading commands ------------------------------------------------------------------------


def test_no_keys_give_no_sources() -> None:
    assert parse_reading_keys([], ["a", "b"]) == {}


def test_store_bound_keys_map_each_store_to_its_file_or_stdin() -> None:
    sources = parse_reading_keys(["a=./a.key", "b=-"], ["a", "b", "c"])

    assert sources == {"a": KeyFile(Path("./a.key")), "b": KeyStdin()}


def test_path_after_the_first_equals_sign_may_contain_equals_signs() -> None:
    assert parse_reading_keys(["a=x=y.key"], ["a"]) == {"a": KeyFile(Path("x=y.key"))}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("./a.key", KeyFile(Path("./a.key"))),
        ("-", KeyStdin()),
        ("./a=b.key", KeyFile(Path("./a=b.key"))),
        ("C:\\keys\\a.key", KeyFile(Path("C:\\keys\\a.key"))),
        ("=x", KeyFile(Path("=x"))),
        ("Upper=x", KeyFile(Path("Upper=x"))),
        ("9lives=x", KeyFile(Path("9lives=x"))),
    ],
)
def test_bare_path_is_the_single_store_shorthand(value: str, expected: KeyFile | KeyStdin) -> None:
    # The text before the first '=' is not a valid store name, so it is a path (PD 19).
    assert parse_reading_keys([value], ["only"]) == {"only": expected}


def test_shorthand_counts_a_repeated_store_once() -> None:
    assert parse_reading_keys(["./a.key"], ["a", "a"]) == {"a": KeyFile(Path("./a.key"))}


def test_shorthand_with_several_stores_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"-k <store>=<path>$"):
        parse_reading_keys(["./a.key"], ["a", "b"])


def test_key_for_a_store_not_in_the_list_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"'x'.*not in the store list"):
        parse_reading_keys(["x=./x.key"], ["a", "b"])


def test_two_keys_for_one_store_are_refused() -> None:
    with pytest.raises(ValidationError, match="more than one -k for store 'a'"):
        parse_reading_keys(["a=./1.key", "a=./2.key"], ["a", "b"])


def test_shorthand_and_store_bound_key_for_the_same_store_are_refused() -> None:
    with pytest.raises(ValidationError, match="more than one -k for store 'a'"):
        parse_reading_keys(["./1.key", "a=./2.key"], ["a"])


@pytest.mark.parametrize("value", ["", "a="])
def test_empty_path_is_refused(value: str) -> None:
    with pytest.raises(ValidationError, match="empty"):
        parse_reading_keys([value], ["a"])


def test_more_than_one_stdin_key_is_refused() -> None:
    with pytest.raises(ValidationError, match="stdin"):
        parse_reading_keys(["a=-", "b=-"], ["a", "b"])


@given(
    stores=st.lists(store_names(), min_size=1, max_size=4, unique=True),
    # A leading '~' is expanded (tested below); every other path is kept as given.
    path=st.text(min_size=1).filter(lambda text: text != "-" and not text.startswith("~")),
    data=st.data(),
)
def test_any_store_name_binds_any_path_even_with_equals_signs(
    stores: list[str], path: str, data: st.DataObject
) -> None:
    store = data.draw(st.sampled_from(stores))

    assert parse_reading_keys([f"{store}={path}"], stores) == {store: KeyFile(Path(path))}


# --- writing commands ------------------------------------------------------------------------


def test_no_writing_key_gives_no_source() -> None:
    assert parse_writing_key(None) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("-", KeyStdin()),
        ("./a.key", KeyFile(Path("./a.key"))),
        # Writing commands take a path only; "store=path" is a file name (PD 19).
        ("a=./a.key", KeyFile(Path("a=./a.key"))),
    ],
)
def test_writing_key_is_a_path_or_stdin(value: str, expected: KeyFile | KeyStdin) -> None:
    assert parse_writing_key(value) == expected


def test_empty_writing_key_is_refused() -> None:
    with pytest.raises(ValidationError, match="empty"):
        parse_writing_key("")


@given(path=st.text(min_size=1).filter(lambda text: text != "-" and not text.startswith("~")))
def test_any_writing_key_path_is_kept_as_given(path: str) -> None:
    assert parse_writing_key(path) == KeyFile(Path(path))


def test_empty_key_path_names_the_option_it_came_from() -> None:
    with pytest.raises(ValidationError, match="the path of --new-key is empty"):
        parse_key_path("", option="--new-key")


def test_empty_key_path_names_k_by_default() -> None:
    with pytest.raises(ValidationError, match="the path of -k is empty"):
        parse_key_path("")


# --- home directory expansion ----------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_store_bound_key_path_expands_the_home_directory(home: Path) -> None:
    # zsh and quoting leave '~' after 'store=' literal; the TUI and [keys] expand it too.
    assert parse_reading_keys(["b=~/b.key"], ["a", "b"]) == {"b": KeyFile(home / "b.key")}


def test_shorthand_key_path_expands_the_home_directory(home: Path) -> None:
    assert parse_reading_keys(["~/a.key"], ["a"]) == {"a": KeyFile(home / "a.key")}


def test_writing_and_new_key_paths_expand_the_home_directory(home: Path) -> None:
    assert parse_writing_key("~/w.key") == KeyFile(home / "w.key")
    assert parse_key_path("~/n.key", option="--new-key") == KeyFile(home / "n.key")


@pytest.mark.usefixtures("home")
def test_tilde_inside_a_path_is_not_expanded() -> None:
    # Path("./~/a.key") normalises to Path("~/a.key"): the source stays unexpanded.
    assert parse_key_path("./~/a.key") == KeyFile(Path("~/a.key"))


def test_unknown_home_directory_is_a_key_source_error() -> None:
    with pytest.raises(KeySourceError, match="unknown home directory"):
        parse_key_path("~no-such-user-envs-test/a.key")
