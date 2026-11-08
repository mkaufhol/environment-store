"""The CLI test harness, shared by the CLI tests.

How to use it
=============

`tests/cli/conftest.py` provides the fixtures:

- `cli`: a `CliHarness`, parametrised over a `json`, a `toml` and a `sqlite` backend in
  `tmp_path`. Use it for happy paths that must work on every backend.
- `cli_json`: the same on `json` only, for error cases where the backend does not matter.

Every CLI test also runs inside `tmp_path` (it is the working directory) with
`ENV_STORE_CONNECTION` and `ENV_STORE_ORDERED_OVERWRITE` removed from the environment.

Arrange and assert through the library, act through the CLI::

    def test_set_then_get(cli: CliHarness) -> None:
        cli.store().create_store("a")

        result = cli.invoke("set", "-s", "a", "HOST=localhost")

        assert_exit(result, 0)
        assert cli.store().get("a", "HOST") == "localhost"

- `invoke(*args)` runs the real `envs` app in-process with `-c <connection>` prepended
  (`connection=False` leaves it out, e.g. to test a missing connection or the project file).
  It returns typer's `Result`: `exit_code`, `stdout` / `stderr` (text, CRLF normalised) and
  `stdout_bytes` / `stderr_bytes` (exact). stdin is `input=` (str or bytes; bytes are passed
  through exactly).
- Terminal state is faked: `stdin_tty=True` makes the CLI interactive (it may prompt),
  `stdout_tty=True` makes `get` add a newline. CliRunner itself is never a TTY.
- Prompts go to a `RecordingPrompter`. By default it has no answers, so any prompt fails the
  test ("no prompt" is proven by passing). Script answers with
  `RecordingPrompter("s3cret", "yes", KeyboardInterrupt())` and read `prompter.prompts`
  afterwards. Answers are used in order by `secret`, `new_secret` (one answer covers both
  entries) and `confirm` (`True` / `False`, or a string where only y / yes is yes). An
  exception instance is raised instead (`EOFError()` becomes `typer.Abort`, exit 1, like the
  real prompter; `KeyboardInterrupt()` gives exit 130).
- `run` never replaces the test process: `exec_process` records `(file, argv, env)` in
  `cli.exec_calls` and raises `Executed` (the command exits 1 with `result.exception` being the
  `Executed`), or set `cli.exec_error` to raise e.g. `FileNotFoundError()` instead.
- Failures after or during a write: `opener=cli.hooked_opener(before=..., after=...)` wraps the
  first adapter the CLI opens in a `HookedAdapter`. Exit 5 (concurrent change)::

      opener = cli.hooked_opener(before={"write_store": lambda: cli.store().set("a", "X", "1")})

  A failure after the commit::

      opener = cli.hooked_opener(after={"write_store": raising(BackendError("connection lost"))})

- Keys: `cli.key_file()` writes a new key file (0600) in the harness root and returns its path;
  `cli.passphrase_file("pw")` writes a passphrase file; `cli.project_file("stores = ['a']")`
  writes `.envstore.toml` (the project file search stops at the harness root).
- Passphrase stores are cheap: the harness KDF is `CheapKdf`; the clock is a `FakeClock`.
- Stores from `cli.store()` are closed when the fixture ends.
- Hypothesis: function-scoped fixtures are not reset between examples, so create one backend
  per example inside the test with `temporary_cli("json")` (a context manager).
- A test-only app: `build_app()` plus your own `@app.command(cls=EnvsCommand)` and
  `cli.invoke(..., app=app)`.
"""

import os
import tempfile
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import TracebackType
from typing import Final, Literal, NoReturn, Self

import pytest
import typer
from typer.testing import CliRunner, Result

from environment_store.cli.app import app as envs
from environment_store.cli.runtime import Runtime
from environment_store.config.project import PROJECT_FILE_NAME
from environment_store.config.prompt import Prompter
from environment_store.core.adapter import Adapter, MigratableAdapter, MigrationReport, SetupMode
from environment_store.core.models import StoreInfo, StoreRecord
from environment_store.library.keys import generate_key_file
from environment_store.library.store import (
    AdapterOpener,
    EnvironmentStore,
    open_configured_adapter,
)
from tests.support.clock import FakeClock
from tests.support.kdf import CheapKdf

__all__ = [
    "SCHEMES",
    "Answer",
    "CliHarness",
    "Executed",
    "HookedAdapter",
    "HookedMigratableAdapter",
    "RecordingPrompter",
    "Scheme",
    "assert_exit",
    "cli_harness",
    "connection_for",
    "hooked",
    "raising",
    "temporary_cli",
]

type Scheme = Literal["json", "toml", "sqlite"]
SCHEMES: Final[tuple[Scheme, ...]] = ("json", "toml", "sqlite")

type Answer = str | bool | BaseException
"""A scripted prompt answer: text, a confirmation, or an exception to raise."""

type Hook = Callable[[], None]


def connection_for(root: Path, scheme: Scheme) -> str:
    """The connection string of a fresh backend below `root`."""
    if scheme == "sqlite":
        return f"sqlite:///{root / 'envs.db'}"
    return f"{scheme}://{root / 'stores'}"


def raising(error: BaseException) -> Hook:
    """A hook that raises `error`, e.g. `after={"write_store": raising(BackendError("x"))}`."""

    def hook() -> None:
        raise error

    return hook


def assert_exit(result: Result, code: int) -> None:
    """Assert the exit code; on a mismatch show stdout, stderr and any unexpected exception."""
    if result.exit_code == code:
        return
    details = [
        f"exit code {result.exit_code}, expected {code}",
        f"stdout: {result.stdout!r}",
        f"stderr: {result.stderr!r}",
    ]
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        details.append(f"exception: {result.exception!r}")
    pytest.fail("\n".join(details))


class Executed(Exception):  # noqa: N818 - it signals a successful exec, not an error
    """Raised by the harness's fake `exec_process` after recording the call."""

    file: str
    argv: list[str]
    env: dict[str, str]

    def __init__(self, file: str, argv: list[str], env: dict[str, str]) -> None:
        super().__init__(file)
        self.file = file
        self.argv = argv
        self.env = env


class RecordingPrompter:
    """A `Prompter` with scripted answers that records every prompt.

    Attributes:
        prompts: `(kind, text)` per prompt, kind is `secret`, `new_secret` or `confirm`.
    """

    prompts: list[tuple[str, str]]
    _answers: list[Answer]

    def __init__(self, *answers: Answer) -> None:
        self.prompts = []
        self._answers = list(answers)

    @property
    def remaining(self) -> int:
        """How many answers were not used."""
        return len(self._answers)

    def secret(self, prompt: str) -> str:
        return str(self._answer("secret", prompt))

    def new_secret(self, prompt: str) -> str:
        return str(self._answer("new_secret", prompt))

    def confirm(self, question: str) -> bool:
        answer = self._answer("confirm", question)
        if isinstance(answer, bool):
            return answer
        return answer.strip().lower() in {"y", "yes"}

    def _answer(self, kind: str, text: str) -> str | bool:
        self.prompts.append((kind, text))
        if not self._answers:
            pytest.fail(f"unexpected {kind} prompt: {text!r}")
        answer = self._answers.pop(0)
        if isinstance(answer, EOFError):
            raise typer.Abort from answer
        if isinstance(answer, BaseException):
            raise answer
        return answer


class HookedAdapter:
    """Delegates every `Adapter` method to `inner`; hooks run once around the first call.

    `before[method]` runs right before the first call of `method`, `after[method]` right after
    it returned; a hook may raise. State is per instance.
    """

    inner: Adapter
    _before: dict[str, Hook]
    _after: dict[str, Hook]

    def __init__(
        self, inner: Adapter, *, before: Mapping[str, Hook], after: Mapping[str, Hook]
    ) -> None:
        self.inner = inner
        self._before = dict(before)
        self._after = dict(after)

    def _run[T](self, method: str, call: Callable[[], T]) -> T:
        hook = self._before.pop(method, None)
        if hook is not None:
            hook()
        result = call()
        hook = self._after.pop(method, None)
        if hook is not None:
            hook()
        return result

    def list_stores(self) -> list[StoreInfo]:
        return self._run("list_stores", self.inner.list_stores)

    def create_store(self, record: StoreRecord) -> None:
        self._run("create_store", lambda: self.inner.create_store(record))

    def read_store(self, name: str) -> StoreRecord:
        return self._run("read_store", lambda: self.inner.read_store(name))

    def write_store(self, record: StoreRecord, *, expected_revision: int) -> None:
        self._run(
            "write_store",
            lambda: self.inner.write_store(record, expected_revision=expected_revision),
        )

    def delete_store(self, name: str) -> None:
        self._run("delete_store", lambda: self.inner.delete_store(name))

    def close(self) -> None:
        self.inner.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class HookedMigratableAdapter(HookedAdapter):
    """A `HookedAdapter` around a SQL adapter: also delegates `migrate`."""

    _migratable: MigratableAdapter

    def __init__(
        self,
        inner: MigratableAdapter,
        *,
        before: Mapping[str, Hook],
        after: Mapping[str, Hook],
    ) -> None:
        super().__init__(inner, before=before, after=after)
        self._migratable = inner

    def migrate(self) -> MigrationReport:
        return self._run("migrate", self._migratable.migrate)


def hooked(
    inner: Adapter,
    *,
    before: Mapping[str, Hook] | None = None,
    after: Mapping[str, Hook] | None = None,
) -> HookedAdapter:
    """Wrap an adapter; SQL adapters stay migratable."""
    if isinstance(inner, MigratableAdapter):
        return HookedMigratableAdapter(inner, before=before or {}, after=after or {})
    return HookedAdapter(inner, before=before or {}, after=after or {})


class _HookFirst:
    """An `AdapterOpener` that hooks the first adapter it opens and no later one."""

    _before: Mapping[str, Hook]
    _after: Mapping[str, Hook]
    _used: bool

    def __init__(self, *, before: Mapping[str, Hook], after: Mapping[str, Hook]) -> None:
        self._before = before
        self._after = after
        self._used = False

    def __call__(self, connection: str, setup: SetupMode) -> Adapter:
        adapter = open_configured_adapter(connection, setup)
        if self._used:
            return adapter
        self._used = True
        return hooked(adapter, before=self._before, after=self._after)


@dataclass
class CliHarness:
    """One backend, the CLI app and the faked boundaries of a CLI test (see the module doc).

    Attributes:
        root: The test directory (the backend, key files and the project file live here).
        connection: The backend's connection string, passed as `-c` by `invoke`.
        clock: The clock of the CLI and of `store()`.
        kdf: Cheap Argon2id parameters for the CLI and `store()`.
        app: The app `invoke` runs; `None` for the real `envs` app.
        exec_calls: What `run` tried to execute: `(file, argv, env)`.
        exec_error: Raised by the fake `exec_process` instead of `Executed`, e.g.
            `FileNotFoundError()` for exit code 127.
    """

    root: Path
    connection: str
    clock: FakeClock = field(default_factory=lambda: FakeClock(step=timedelta(seconds=1)))
    kdf: CheapKdf = field(default_factory=CheapKdf)
    app: typer.Typer | None = None
    exec_calls: list[tuple[str, list[str], dict[str, str]]] = field(default_factory=list)
    exec_error: BaseException | None = None
    _stores: list[EnvironmentStore] = field(default_factory=list)

    def runtime(
        self,
        *,
        stdin_tty: bool = False,
        stdout_tty: bool = False,
        prompter: Prompter | None = None,
        opener: AdapterOpener | None = None,
    ) -> Runtime:
        """The `Runtime` `invoke` passes; the project file search stops at `root`."""
        return Runtime(
            project_boundary=self.root,
            stdin_is_tty=lambda: stdin_tty,
            stdout_is_tty=lambda: stdout_tty,
            prompter=RecordingPrompter() if prompter is None else prompter,
            exec_process=self._exec,
            clock=self.clock,
            kdf_params_factory=self.kdf,
            adapter_opener=open_configured_adapter if opener is None else opener,
        )

    def invoke(  # noqa: PLR0913 - every boundary of a CLI run is a keyword
        self,
        *args: str,
        input: str | bytes | None = None,  # noqa: A002 - CliRunner's name
        env: Mapping[str, str] | None = None,
        stdin_tty: bool = False,
        stdout_tty: bool = False,
        connection: bool = True,
        prompter: Prompter | None = None,
        opener: AdapterOpener | None = None,
        app: typer.Typer | None = None,
    ) -> Result:
        """Run the CLI in-process; `-c <connection>` is prepended unless `connection=False`."""
        prefix = ("-c", self.connection) if connection else ()
        runtime = self.runtime(
            stdin_tty=stdin_tty, stdout_tty=stdout_tty, prompter=prompter, opener=opener
        )
        return CliRunner().invoke(
            self._app(app), [*prefix, *args], input=input, env=env, obj=runtime
        )

    def hooked_opener(
        self,
        *,
        before: Mapping[str, Hook] | None = None,
        after: Mapping[str, Hook] | None = None,
    ) -> AdapterOpener:
        """An opener whose first adapter is a `HookedAdapter`; later opens are plain."""
        return _HookFirst(before=before or {}, after=after or {})

    def store(self) -> EnvironmentStore:
        """A library store on the same backend, closed when the test ends."""
        store = EnvironmentStore(self.connection, clock=self.clock, kdf_params_factory=self.kdf)
        self._stores.append(store)
        return store

    def key_file(self, name: str = "a.key") -> Path:
        """Write a new key file (0600) in `root`."""
        path = self.root / name
        generate_key_file(path)
        return path

    def passphrase_file(self, text: str, name: str = "p.txt") -> Path:
        """Write a passphrase file in `root` (one trailing newline is stripped when read)."""
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def project_file(self, text: str, *, directory: Path | None = None) -> Path:
        """Write `.envstore.toml` in `directory` (default: `root`)."""
        path = (self.root if directory is None else directory) / PROJECT_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def close(self) -> None:
        """Close the stores opened by `store()`."""
        for store in self._stores:
            store.close()
        self._stores.clear()

    def _app(self, app: typer.Typer | None) -> typer.Typer:
        if app is not None:
            return app
        return envs if self.app is None else self.app

    def _exec(self, file: str, argv: list[str], env: Mapping[str, str]) -> NoReturn:
        self.exec_calls.append((file, list(argv), dict(env)))
        if self.exec_error is not None:
            raise self.exec_error
        raise Executed(file, list(argv), dict(env))


@contextmanager
def cli_harness(root: Path, scheme: Scheme) -> Generator[CliHarness]:
    """A harness on a fresh `scheme` backend below `root`; closes its stores on exit."""
    harness = CliHarness(root=root, connection=connection_for(root, scheme))
    try:
        yield harness
    finally:
        harness.close()


@contextmanager
def temporary_cli(scheme: Scheme = "json") -> Generator[CliHarness]:
    """A harness in its own temporary directory, for one Hypothesis example."""
    with (
        tempfile.TemporaryDirectory() as directory,
        cli_harness(Path(os.path.realpath(directory)), scheme) as harness,
    ):
        yield harness
