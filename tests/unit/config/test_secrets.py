import stat
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.config.prompt import Prompter
from environment_store.config.secrets import (
    GenerateKeyFile,
    KeyFile,
    KeyStdin,
    NewKeyFile,
    NewPassphrase,
    NewSecret,
    SecretInput,
    SecretResolver,
    StoreInspector,
    no_stdin,
    read_secret_file,
    resolve_new_secret,
)
from environment_store.core.errors import (
    InvalidKeyFileError,
    KeyModeMismatchError,
    KeyRequiredError,
    KeySourceError,
    NotEncryptedError,
    StoreNotFoundError,
    ValidationError,
)
from environment_store.core.models import StoreInfo
from environment_store.core.secrets import KeyMaterial, Passphrase, Secret
from environment_store.crypto.keyfile import format_key
from environment_store.service import StoreService
from tests.support.kdf import CheapKdf
from tests.support.memory_adapter import MemoryAdapter

KEY: Final = KeyMaterial(key=b"\x07" * 32)
KEY_TEXT: Final = format_key(KEY)
PASSPHRASE: Final = Passphrase(text="correct horse battery staple")


class ServiceInspector:
    """A `StoreInspector` straight on a `StoreService` (the library's `EnvironmentStore` too)."""

    service: StoreService

    def __init__(self, service: StoreService) -> None:
        self.service = service

    def store_info(self, name: str) -> StoreInfo:
        return self.service.adapter.read_store(name).info

    def parse_secret(self, name: str, text: str) -> Secret:
        return self.service.parse_secret(name, text)


class RecordingPrompter:
    """A `Prompter` with queued answers that records every question."""

    answers: list[str]
    asked: list[str]

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.asked = []

    def secret(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self.answers.pop(0)

    def new_secret(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self.answers.pop(0)

    def confirm(self, question: str) -> bool:
        self.asked.append(question)
        return False


class Stdin:
    """A `read_stdin` callable that counts its calls."""

    data: bytes
    calls: int

    def __init__(self, data: bytes = b"") -> None:
        self.data = data
        self.calls = 0

    def __call__(self) -> bytes:
        self.calls += 1
        return self.data


@pytest.fixture
def inspector() -> ServiceInspector:
    service = StoreService(MemoryAdapter(), kdf_params_factory=CheapKdf())
    service.create_store("plain")
    service.create_store("keyed", secret=KEY)
    service.create_store("phrased", secret=PASSPHRASE)
    return ServiceInspector(service)


def _input(
    stdin: Stdin | None = None, *, tty: bool = False, prompter: Prompter | None = None
) -> SecretInput:
    return SecretInput(
        read_stdin=Stdin() if stdin is None else stdin, stdin_is_tty=tty, prompter=prompter
    )


def _resolver(
    inspector: StoreInspector,
    stdin: Stdin | None = None,
    *,
    tty: bool = False,
    prompter: Prompter | None = None,
) -> SecretResolver:
    return SecretResolver(inspector, _input(stdin, tty=tty, prompter=prompter))


def _file(tmp_path: Path, content: bytes | str, name: str = "secret") -> Path:
    path = tmp_path / name
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.write_bytes(content)
    return path


def test_service_inspector_is_a_store_inspector(inspector: ServiceInspector) -> None:
    checked: StoreInspector = inspector

    assert checked is inspector


# --- existing secrets --------------------------------------------------------------------------


def test_key_file_for_a_keyfile_store(inspector: ServiceInspector, tmp_path: Path) -> None:
    secret = _resolver(inspector).existing("keyed", KeyFile(_file(tmp_path, KEY_TEXT)))

    assert secret == KEY


def test_passphrase_file_for_a_passphrase_store_strips_one_newline(
    inspector: ServiceInspector, tmp_path: Path
) -> None:
    path = _file(tmp_path, f"{PASSPHRASE.text}\n")

    assert _resolver(inspector).existing("phrased", KeyFile(path)) == PASSPHRASE


def test_key_file_for_a_passphrase_store_is_a_key_mode_mismatch(
    inspector: ServiceInspector, tmp_path: Path
) -> None:
    with pytest.raises(KeyModeMismatchError):
        _resolver(inspector).existing("phrased", KeyFile(_file(tmp_path, KEY_TEXT)))


def test_passphrase_file_for_a_keyfile_store_is_not_a_key_file(
    inspector: ServiceInspector, tmp_path: Path
) -> None:
    with pytest.raises(InvalidKeyFileError):
        _resolver(inspector).existing("keyed", KeyFile(_file(tmp_path, "just words")))


@pytest.mark.parametrize("source", [KeyFile(Path("/nonexistent")), KeyStdin()])
def test_source_for_a_plaintext_store_is_refused(
    inspector: ServiceInspector, source: KeyFile | KeyStdin
) -> None:
    stdin = Stdin(KEY_TEXT.encode())

    with pytest.raises(NotEncryptedError):
        _resolver(inspector, stdin).existing("plain", source)
    assert stdin.calls == 0


def test_plaintext_store_without_source_needs_no_secret(inspector: ServiceInspector) -> None:
    prompter = RecordingPrompter()

    assert _resolver(inspector, tty=True, prompter=prompter).existing("plain", None) is None
    assert prompter.asked == []


def test_missing_store_is_reported_before_anything_is_read(inspector: ServiceInspector) -> None:
    prompter = RecordingPrompter("x")

    with pytest.raises(StoreNotFoundError):
        _resolver(inspector, tty=True, prompter=prompter).existing("missing", None)
    assert prompter.asked == []


@pytest.mark.parametrize("tty", [True, False])
def test_stdin_source_is_read_whatever_the_terminal_state(
    inspector: ServiceInspector,
    tty: bool,  # noqa: FBT001 - parametrised table column
) -> None:
    stdin = Stdin(KEY_TEXT.encode())

    assert _resolver(inspector, stdin, tty=tty).existing("keyed", KeyStdin()) == KEY
    assert stdin.calls == 1


def test_stdin_passphrase_keeps_crlf_handling(inspector: ServiceInspector) -> None:
    stdin = Stdin(f"{PASSPHRASE.text}\r\n".encode())

    assert _resolver(inspector, stdin).existing("phrased", KeyStdin()) == PASSPHRASE


def test_encrypted_store_without_source_is_prompted(inspector: ServiceInspector) -> None:
    prompter = RecordingPrompter(PASSPHRASE.text)

    secret = _resolver(inspector, tty=True, prompter=prompter).existing("phrased", None)

    assert secret == PASSPHRASE
    assert prompter.asked == ["Key or passphrase for store 'phrased': "]


def test_encrypted_store_without_source_and_prompter_needs_a_key(
    inspector: ServiceInspector,
) -> None:
    with pytest.raises(KeyRequiredError, match="-k"):
        _resolver(inspector, tty=True).existing("keyed", None)


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"", "is empty"),
        (b"\n", "is empty"),
        (b"\r\n", "is empty"),
        (b"\xff\xfe", "not valid UTF-8"),
    ],
)
def test_bad_secret_file_is_a_key_source_error(
    inspector: ServiceInspector, tmp_path: Path, content: bytes, reason: str
) -> None:
    path = _file(tmp_path, content)

    with pytest.raises(KeySourceError, match=reason) as caught:
        _resolver(inspector).existing("phrased", KeyFile(path))

    assert str(path) in str(caught.value)


def test_missing_secret_file_is_a_key_source_error(
    inspector: ServiceInspector, tmp_path: Path
) -> None:
    path = tmp_path / "missing.key"

    with pytest.raises(KeySourceError, match="cannot read") as caught:
        _resolver(inspector).existing("keyed", KeyFile(path))

    assert str(path) in str(caught.value)


def test_secret_file_that_is_a_directory_is_a_key_source_error(
    inspector: ServiceInspector, tmp_path: Path
) -> None:
    with pytest.raises(KeySourceError, match="cannot read"):
        _resolver(inspector).existing("keyed", KeyFile(tmp_path))


@pytest.mark.parametrize(("data", "reason"), [(b"", "is empty"), (b"\xff", "not valid UTF-8")])
def test_bad_stdin_secret_is_a_key_source_error(
    inspector: ServiceInspector, data: bytes, reason: str
) -> None:
    with pytest.raises(KeySourceError, match=f"stdin.*{reason}"):
        _resolver(inspector, Stdin(data)).existing("keyed", KeyStdin())


def test_empty_prompt_answer_is_a_key_source_error(inspector: ServiceInspector) -> None:
    with pytest.raises(KeySourceError, match="is empty"):
        _resolver(inspector, tty=True, prompter=RecordingPrompter("")).existing("phrased", None)


def test_read_secret_file_returns_the_text_unchanged(tmp_path: Path) -> None:
    assert read_secret_file(_file(tmp_path, "a\r\nb\n")) == "a\r\nb\n"


def test_no_stdin_refuses_to_read() -> None:
    with pytest.raises(ValidationError, match="stdin"):
        no_stdin()


# --- new secrets -------------------------------------------------------------------------------


def test_new_key_file_from_a_file(tmp_path: Path) -> None:
    new = resolve_new_secret(NewKeyFile(KeyFile(_file(tmp_path, KEY_TEXT))), _input())

    assert new.secret == KEY
    assert new.generated is None


def test_new_key_file_from_stdin() -> None:
    stdin = Stdin(KEY_TEXT.encode())

    new = resolve_new_secret(NewKeyFile(KeyStdin()), _input(stdin))

    assert new.secret == KEY
    assert stdin.calls == 1


def test_new_key_file_must_be_a_key_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidKeyFileError):
        resolve_new_secret(NewKeyFile(KeyFile(_file(tmp_path, "a passphrase"))), _input())


def test_new_key_file_that_is_missing_is_a_key_source_error(tmp_path: Path) -> None:
    with pytest.raises(KeySourceError):
        resolve_new_secret(NewKeyFile(KeyFile(tmp_path / "missing")), _input())


def test_generated_key_file_is_written_with_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "new.key"

    new = resolve_new_secret(GenerateKeyFile(path), _input())

    assert new.generated == path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert isinstance(new.secret, KeyMaterial)
    assert path.read_text(encoding="ascii") == format_key(new.secret)


def test_generated_key_file_refuses_an_existing_path(tmp_path: Path) -> None:
    path = _file(tmp_path, "keep me")

    with pytest.raises(ValidationError, match="already exists"):
        resolve_new_secret(GenerateKeyFile(path), _input())
    assert path.read_text(encoding="utf-8") == "keep me"


def test_discard_removes_a_generated_key_file(tmp_path: Path) -> None:
    path = tmp_path / "new.key"
    new = resolve_new_secret(GenerateKeyFile(path), _input())

    new.discard()
    new.discard()

    assert not path.exists()


def test_discard_keeps_a_given_key_file(tmp_path: Path) -> None:
    path = _file(tmp_path, KEY_TEXT)
    new = resolve_new_secret(NewKeyFile(KeyFile(path)), _input())

    new.discard()

    assert path.exists()


@pytest.mark.parametrize("data", [b"pass phrase\n", b"pass phrase\r\n", b"pass phrase"])
def test_new_passphrase_without_a_terminal_reads_stdin(data: bytes) -> None:
    stdin = Stdin(data)
    prompter = RecordingPrompter("never")

    new = resolve_new_secret(NewPassphrase(), _input(stdin, prompter=prompter))

    assert new.secret == Passphrase(text="pass phrase")
    assert new.generated is None
    assert stdin.calls == 1
    assert prompter.asked == []


def test_new_passphrase_on_a_terminal_is_prompted_twice_by_the_prompter() -> None:
    stdin = Stdin(b"never")
    prompter = RecordingPrompter("pass phrase")

    new = resolve_new_secret(NewPassphrase(), _input(stdin, tty=True, prompter=prompter))

    assert new.secret == Passphrase(text="pass phrase")
    assert prompter.asked == ["New passphrase: "]
    assert stdin.calls == 0


def test_new_passphrase_on_a_terminal_without_prompter_needs_a_key() -> None:
    stdin = Stdin(b"never")

    with pytest.raises(KeyRequiredError):
        resolve_new_secret(NewPassphrase(), _input(stdin, tty=True))
    assert stdin.calls == 0


@pytest.mark.parametrize("data", [b"", b"\n", b"\xff"])
def test_bad_piped_new_passphrase_is_a_key_source_error(data: bytes) -> None:
    with pytest.raises(KeySourceError):
        resolve_new_secret(NewPassphrase(), _input(Stdin(data)))


def test_empty_prompted_new_passphrase_is_a_key_source_error() -> None:
    with pytest.raises(KeySourceError):
        resolve_new_secret(NewPassphrase(), _input(tty=True, prompter=RecordingPrompter("")))


def test_new_secret_hides_the_secret_in_its_repr(tmp_path: Path) -> None:
    new = NewSecret(secret=PASSPHRASE, generated=None)

    assert PASSPHRASE.text not in repr(new)


# --- secrets never leak ------------------------------------------------------------------------

# Characters that no error message contains, so any occurrence would be a leak.
_SECRET_TEXT: Final = st.text(alphabet="#%&*~^!$äöüßéñ \n", min_size=4).filter(
    lambda text: bool(text.strip())
)


@given(text=_SECRET_TEXT)
def test_wrong_secret_text_never_appears_in_the_error(text: str) -> None:
    service = StoreService(MemoryAdapter(), kdf_params_factory=CheapKdf())
    service.create_store("keyed", secret=KEY)
    resolver = SecretResolver(ServiceInspector(service), _input(Stdin(text.encode())))

    with pytest.raises((InvalidKeyFileError, KeySourceError)) as caught:
        resolver.existing("keyed", KeyStdin())

    assert text.strip() not in str(caught.value)


_MAKERS: Final[list[Callable[[], object]]] = [KeyStdin, NewPassphrase]


@pytest.mark.parametrize("make", _MAKERS)
def test_marker_choices_are_value_objects(make: Callable[[], object]) -> None:
    assert make() == make()
