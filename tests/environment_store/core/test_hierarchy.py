import pytest

from environment_store.core.hierarchy import (
    child_kind,
    describe,
    level_kind,
    to_kwargs,
    to_path,
)


def test_path_kwargs_round_trip():
    assert to_kwargs(()) == {
        "organisation": None,
        "project": None,
        "environment": None,
        "service": None,
    }
    assert to_path(**to_kwargs(("a", "b"))) == ("a", "b")


def test_to_kwargs_rejects_too_deep_paths():
    with pytest.raises(ValueError):
        to_kwargs(("a", "b", "c", "d", "e"))


def test_kinds_and_describe():
    assert level_kind(("a", "b")) == "project"
    assert child_kind(()) == "organisation"
    assert child_kind(("a", "b", "c", "d")) is None
    assert describe(()) == "root"
    assert describe(("a", "b")) == "a / b"
    with pytest.raises(ValueError):
        level_kind(())
