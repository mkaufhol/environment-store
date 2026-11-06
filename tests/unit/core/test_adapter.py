import dataclasses
from datetime import UTC, datetime
from typing import Final

import pytest

from environment_store.core.adapter import (
    Adapter,
    MigratableAdapter,
    MigrationReport,
    SetupMode,
    check_create,
    check_write,
)
from environment_store.core.errors import ValidationError
from environment_store.core.models import MAX_REVISION, StoreRecord
from tests.support.memory_adapter import MemoryAdapter, MemoryBackend

_T0: Final[datetime] = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)


def _record(*, name: str = "base", revision: int = 1) -> StoreRecord:
    return StoreRecord.plain(name=name, variables={"A": "1"}, created_at=_T0, revision=revision)


def _forge_name(record: StoreRecord, name: str) -> StoreRecord:
    # Bypasses the model's own validation, as a buggy or malicious caller could.
    object.__setattr__(record, "name", name)
    return record


def test_setup_modes_are_auto_and_none() -> None:
    assert [mode.value for mode in SetupMode] == ["auto", "none"]


def test_memory_adapter_satisfies_the_adapter_protocol_but_is_not_migratable() -> None:
    adapter = MemoryAdapter(MemoryBackend())

    assert isinstance(adapter, Adapter)
    assert not isinstance(adapter, MigratableAdapter)


@pytest.mark.parametrize(
    ("from_version", "to_version", "created"),
    [(None, 1, True), (1, 1, False), (1, 3, False)],
)
def test_migration_report_accepts_create_noop_and_upgrade(
    from_version: int | None, to_version: int, *, created: bool
) -> None:
    report = MigrationReport(from_version=from_version, to_version=to_version, created=created)

    assert (report.from_version, report.to_version, report.created) == (
        from_version,
        to_version,
        created,
    )


@pytest.mark.parametrize(
    ("from_version", "to_version", "created"),
    [
        (None, 1, False),
        (1, 1, True),
        (2, 1, False),
        (0, 1, False),
        (None, 0, True),
        (True, 1, False),
        (None, True, True),
    ],
)
def test_migration_report_rejects_inconsistent_versions(
    from_version: int | None, to_version: int, *, created: bool
) -> None:
    with pytest.raises(ValidationError):
        MigrationReport(from_version=from_version, to_version=to_version, created=created)


def test_migration_report_is_immutable() -> None:
    report = MigrationReport(from_version=None, to_version=1, created=True)

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.to_version = 2  # ty: ignore[invalid-assignment] - asserting immutability


def test_check_create_accepts_a_first_revision_record() -> None:
    check_create(_record())


@pytest.mark.parametrize("revision", [2, 7])
def test_check_create_rejects_a_record_that_is_not_at_revision_one(revision: int) -> None:
    with pytest.raises(ValidationError, match="revision 1"):
        check_create(_record(revision=revision))


@pytest.mark.parametrize("name", ["../x", "A", ""])
def test_check_create_rejects_a_forged_store_name(name: str) -> None:
    with pytest.raises(ValidationError, match="store name"):
        check_create(_forge_name(_record(), name))


@pytest.mark.parametrize("expected_revision", [1, 41])
def test_check_write_accepts_the_next_revision(expected_revision: int) -> None:
    check_write(_record(revision=expected_revision + 1), expected_revision=expected_revision)


@pytest.mark.parametrize(
    ("record_revision", "expected_revision"),
    [(2, 2), (3, 1), (1, 2), (1, 0)],
)
def test_check_write_rejects_a_record_revision_other_than_expected_plus_one(
    record_revision: int, expected_revision: int
) -> None:
    with pytest.raises(ValidationError, match="revision"):
        check_write(_record(revision=record_revision), expected_revision=expected_revision)


@pytest.mark.parametrize("expected_revision", [MAX_REVISION, MAX_REVISION + 1, 2**63 - 1, 2**64])
def test_check_write_rejects_an_expected_revision_that_cannot_be_incremented(
    expected_revision: int,
) -> None:
    with pytest.raises(ValidationError, match="cannot be incremented"):
        check_write(_record(revision=MAX_REVISION), expected_revision=expected_revision)


def test_check_write_accepts_the_largest_revision_as_the_new_one() -> None:
    check_write(_record(revision=MAX_REVISION), expected_revision=MAX_REVISION - 1)


@pytest.mark.parametrize("expected_revision", [0, -1, True])
def test_check_write_rejects_an_expected_revision_below_one_or_not_an_int(
    expected_revision: int,
) -> None:
    with pytest.raises(ValidationError, match="expected_revision"):
        check_write(_record(revision=2), expected_revision=expected_revision)


@pytest.mark.parametrize("name", ["../x", "A", ""])
def test_check_write_rejects_a_forged_store_name(name: str) -> None:
    with pytest.raises(ValidationError, match="store name"):
        check_write(_forge_name(_record(revision=2), name), expected_revision=1)
