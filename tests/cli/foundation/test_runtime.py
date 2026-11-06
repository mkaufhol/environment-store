"""`Runtime`: every terminal and OS boundary of the CLI, injectable."""

import io
import os
import sys
from pathlib import Path

import pytest

from environment_store.cli import runtime
from environment_store.cli.runtime import Runtime
from environment_store.core.clock import utc_now
from environment_store.library.store import open_configured_adapter


class _Stream(io.StringIO):
    def __init__(self, *, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_default_runtime_uses_the_real_process_boundaries() -> None:
    defaults = Runtime()

    assert defaults.environ() is os.environ
    assert defaults.cwd() == Path.cwd()
    assert defaults.project_boundary is None
    assert defaults.uid is None
    assert defaults.prompter is None
    assert defaults.exec_process is os.execvpe
    assert defaults.clock is utc_now
    assert defaults.kdf_params_factory is None
    assert defaults.adapter_opener is open_configured_adapter


@pytest.mark.parametrize("tty", [True, False])
def test_default_stdin_check_asks_the_current_stdin(
    monkeypatch: pytest.MonkeyPatch, *, tty: bool
) -> None:
    monkeypatch.setattr(sys, "stdin", _Stream(tty=tty))

    assert Runtime().stdin_is_tty() is tty


@pytest.mark.parametrize("tty", [True, False])
def test_default_stdout_check_asks_the_current_stdout(
    monkeypatch: pytest.MonkeyPatch, *, tty: bool
) -> None:
    monkeypatch.setattr(sys, "stdout", _Stream(tty=tty))

    assert Runtime().stdout_is_tty() is tty


def test_default_stdout_check_of_a_closed_stdout_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)

    assert Runtime().stdout_is_tty() is False


def test_runtime_is_immutable() -> None:
    with pytest.raises(AttributeError):
        Runtime().uid = 1  # ty: ignore[invalid-assignment] - the point of the test


def test_default_callables_are_named_module_functions() -> None:
    defaults = Runtime()

    assert defaults.environ is runtime.environ
    assert defaults.stdin_is_tty is runtime.stdin_is_tty
    assert defaults.stdout_is_tty is runtime.stdout_is_tty
