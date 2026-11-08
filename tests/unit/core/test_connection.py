import importlib
import sys
import textwrap
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final

import pytest

from environment_store.core.adapter import SetupMode
from environment_store.core.connection import (
    ADAPTER_FACTORIES,
    AdapterEntry,
    open_adapter,
    scheme_of,
)
from environment_store.core.errors import BackendError, MissingExtraError, ValidationError
from tests.support.memory_adapter import MemoryAdapter

type ModuleWriter = Callable[[str], str]

_FACTORY_SOURCE: Final[str] = """
from environment_store.core.adapter import SetupMode
from tests.support.memory_adapter import MemoryAdapter

CALLS: list[tuple[str, SetupMode]] = []


def open_fake(url: str, *, setup: SetupMode = SetupMode.AUTO) -> MemoryAdapter:
    CALLS.append((url, setup))
    return MemoryAdapter(setup=setup)
"""


@pytest.fixture
def write_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleWriter]:
    """Write a uniquely named, importable module and return its name."""
    monkeypatch.syspath_prepend(str(tmp_path))
    written: list[str] = []

    def write(source: str) -> str:
        name = f"fake_adapter_{uuid.uuid4().hex}"
        (tmp_path / f"{name}.py").write_text(textwrap.dedent(source), encoding="utf-8")
        importlib.invalidate_caches()
        written.append(name)
        return name

    yield write
    for name in written:
        sys.modules.pop(name, None)


# --- scheme_of ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "scheme"),
    [
        ("json://envs", "json"),
        ("toml:///abs/dir", "toml"),
        ("sqlite:////abs/envs.db", "sqlite"),
        ("postgresql://user:pass@host:5432/db?schema=a", "postgresql"),
        ("PostgreSQL://host/db", "postgresql"),
        ("SQLITE:///envs.db", "sqlite"),
        ("git+ssh://host", "git+ssh"),
        ("x.y-z://", "x.y-z"),
    ],
)
def test_scheme_of_returns_the_lowercased_scheme(url: str, scheme: str) -> None:
    assert scheme_of(url) == scheme


@pytest.mark.parametrize(
    "url",
    [
        "",
        "envs",
        "./envs",
        "json:/envs",
        "json:envs",
        "://envs",
        "1json://envs",
        " json://envs",
        "js on://envs",
        "/abs/path",
        "C:\\envs",
    ],
)
def test_scheme_of_rejects_strings_without_scheme_and_slashes(url: str) -> None:
    with pytest.raises(ValidationError, match="scheme://"):
        scheme_of(url)


def test_scheme_of_never_echoes_the_connection_string() -> None:
    url = "postgresql:/admin:hunter2@db/app"

    with pytest.raises(ValidationError) as caught:
        scheme_of(url)

    assert "hunter2" not in str(caught.value)


# --- registry ----------------------------------------------------------------------------------


def test_every_v2_scheme_is_registered() -> None:
    postgres = AdapterEntry(
        target="environment_store.adapters.postgres:open_postgres",
        extra="postgres",
        requires=("psycopg",),
    )

    assert dict(ADAPTER_FACTORIES) == {
        "json": AdapterEntry(target="environment_store.adapters.files:open_json"),
        "toml": AdapterEntry(target="environment_store.adapters.files:open_toml"),
        "sqlite": AdapterEntry(target="environment_store.adapters.sqlite:open_sqlite"),
        "postgresql": postgres,
        "postgres": postgres,
    }


def test_registry_is_read_only() -> None:
    with pytest.raises(TypeError):
        # Asserting the runtime guard of the read-only mapping, which ty rightly rejects.
        ADAPTER_FACTORIES["memory"] = AdapterEntry(  # ty: ignore[invalid-assignment]
            target="tests.support.memory_adapter:MemoryAdapter"
        )


def test_adapter_entry_defaults_to_no_extra_and_no_requirements() -> None:
    entry = AdapterEntry(target="pkg.module:factory")

    assert (entry.extra, entry.requires) == (None, ())


@pytest.mark.parametrize(
    "target",
    ["", "pkg.module", "pkg.module:", ":factory", "pkg..module:factory", "pkg:fac:tory", "1x:f"],
)
def test_adapter_entry_rejects_a_target_that_is_not_module_colon_attribute(target: str) -> None:
    with pytest.raises(ValidationError, match="module:attribute"):
        AdapterEntry(target=target)


def test_adapter_entry_with_requirements_needs_an_extra() -> None:
    with pytest.raises(ValidationError, match="extra"):
        AdapterEntry(target="pkg.module:factory", requires=("psycopg",))


def test_adapter_entry_copies_requirements_into_a_tuple() -> None:
    requires = ["psycopg"]
    # A list on purpose: callers without a type checker may pass one.
    entry = AdapterEntry(
        target="pkg:f",
        extra="postgres",
        requires=requires,  # ty: ignore[invalid-argument-type] - a list on purpose
    )
    requires.append("other")

    assert entry.requires == ("psycopg",)


# --- open_adapter ------------------------------------------------------------------------------


@pytest.mark.parametrize("setup", list(SetupMode))
def test_open_adapter_calls_the_factory_with_the_full_url_and_setup_mode(
    write_module: ModuleWriter, setup: SetupMode
) -> None:
    module = write_module(_FACTORY_SOURCE)
    factories = {"fake": AdapterEntry(target=f"{module}:open_fake")}

    adapter = open_adapter("FAKE://user:pw@host/x?y=1", setup=setup, factories=factories)

    assert isinstance(adapter, MemoryAdapter)
    assert adapter.setup is setup
    calls = sys.modules[module].CALLS
    assert calls == [("FAKE://user:pw@host/x?y=1", setup)]


def test_open_adapter_defaults_to_auto_setup(write_module: ModuleWriter) -> None:
    module = write_module(_FACTORY_SOURCE)

    adapter = open_adapter(
        "fake://x", factories={"fake": AdapterEntry(target=f"{module}:open_fake")}
    )

    assert isinstance(adapter, MemoryAdapter)
    assert adapter.setup is SetupMode.AUTO


def test_open_adapter_rejects_an_unknown_scheme_listing_the_supported_ones() -> None:
    with pytest.raises(ValidationError) as caught:
        open_adapter("mysql://user:secret@host/db")

    message = str(caught.value)
    assert "'mysql'" in message
    assert "json, postgres, postgresql, sqlite, toml" in message
    assert "secret" not in message


def test_open_adapter_rejects_a_string_without_a_scheme() -> None:
    with pytest.raises(ValidationError, match="scheme://"):
        open_adapter("envs.db")


def _missing_package() -> str:
    return f"missing_pkg_{uuid.uuid4().hex}"


@pytest.mark.parametrize("submodule", ["", ".pq"])
def test_open_adapter_turns_a_missing_required_package_into_missing_extra(
    write_module: ModuleWriter, submodule: str
) -> None:
    package = _missing_package()
    module = write_module(f"import {package}{submodule}\n")
    entry = AdapterEntry(target=f"{module}:open_fake", extra="postgres", requires=(package,))

    with pytest.raises(MissingExtraError) as caught:
        open_adapter("fake://x", factories={"fake": entry})

    assert caught.value.extra == "postgres"
    assert "uv add 'environment-store[postgres]'" in str(caught.value)
    assert isinstance(caught.value.__cause__, ModuleNotFoundError)


def test_open_adapter_propagates_a_missing_package_that_is_not_required(
    write_module: ModuleWriter,
) -> None:
    package = _missing_package()
    module = write_module(f"import {package}\n")
    entry = AdapterEntry(target=f"{module}:open_fake", extra="postgres", requires=("psycopg",))

    with pytest.raises(ModuleNotFoundError) as caught:
        open_adapter("fake://x", factories={"fake": entry})

    assert caught.value.name == package


def test_open_adapter_propagates_a_missing_adapter_module() -> None:
    entry = AdapterEntry(
        target="environment_store.adapters.nowhere:open_nowhere",
        extra="postgres",
        requires=("psycopg",),
    )

    with pytest.raises(ModuleNotFoundError) as caught:
        open_adapter("fake://x", factories={"fake": entry})

    assert caught.value.name is not None
    assert caught.value.name.startswith("environment_store.adapters")


def test_open_adapter_propagates_a_module_not_found_error_without_a_name(
    write_module: ModuleWriter,
) -> None:
    module = write_module('raise ModuleNotFoundError("broken install")\n')
    entry = AdapterEntry(target=f"{module}:open_fake", extra="postgres", requires=("psycopg",))

    with pytest.raises(ModuleNotFoundError, match="broken install"):
        open_adapter("fake://x", factories={"fake": entry})


@pytest.mark.parametrize(
    ("source", "error"),
    [
        ("from os import does_not_exist\n", ImportError),
        ('raise RuntimeError("adapter module failed")\n', RuntimeError),
    ],
)
def test_open_adapter_propagates_other_import_failures_unchanged(
    write_module: ModuleWriter, source: str, error: type[Exception]
) -> None:
    module = write_module(source)
    entry = AdapterEntry(target=f"{module}:open_fake", extra="postgres", requires=("os",))

    with pytest.raises(error) as caught:
        open_adapter("fake://x", factories={"fake": entry})

    assert not isinstance(caught.value, MissingExtraError)


def test_open_adapter_propagates_a_missing_factory_attribute(write_module: ModuleWriter) -> None:
    module = write_module(_FACTORY_SOURCE)

    with pytest.raises(AttributeError, match="open_missing"):
        open_adapter("fake://x", factories={"fake": AdapterEntry(target=f"{module}:open_missing")})


def test_open_adapter_propagates_errors_raised_by_the_factory(write_module: ModuleWriter) -> None:
    module = write_module(
        """
        from typing import NoReturn

        from environment_store.core.adapter import SetupMode
        from environment_store.core.errors import BackendError

        def open_broken(url: str, *, setup: SetupMode) -> NoReturn:
            raise BackendError("cannot open")
        """
    )
    entry = AdapterEntry(target=f"{module}:open_broken")

    with pytest.raises(BackendError, match="cannot open"):
        open_adapter("fake://x", factories={"fake": entry})
