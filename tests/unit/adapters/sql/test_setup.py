from collections.abc import Mapping

import pytest

from environment_store.adapters.sql.schema import META_APP, SCHEMA_VERSION
from environment_store.adapters.sql.setup import (
    DatabaseInspection,
    SetupAction,
    SetupState,
    classify,
    decide,
    stored_version,
)
from environment_store.core.errors import (
    BackendError,
    DatabaseNotCleanError,
    SchemaOutdatedError,
    SchemaTooNewError,
    ValidationError,
)

_OURS = frozenset({"meta", "stores"})


def _ours(version: str = str(SCHEMA_VERSION), **extra: str) -> DatabaseInspection:
    return DatabaseInspection(
        tables=_OURS, meta={"app": META_APP, "schema_version": version, **extra}
    )


# --- DatabaseInspection ------------------------------------------------------------------------


def test_inspection_copies_tables_and_meta() -> None:
    tables = {"meta", "stores"}
    meta = {"app": META_APP, "schema_version": "1"}

    inspection = DatabaseInspection(tables=tables, meta=meta)  # ty: ignore[invalid-argument-type] - a set on purpose
    tables.add("other")
    meta["app"] = "other"

    assert inspection.tables == frozenset({"meta", "stores"})
    assert inspection.meta == {"app": META_APP, "schema_version": "1"}


def test_inspection_meta_is_read_only() -> None:
    inspection = _ours()

    assert isinstance(inspection.meta, Mapping)
    with pytest.raises(TypeError):
        inspection.meta["app"] = "other"  # ty: ignore[invalid-assignment] - read-only on purpose


def test_inspection_without_meta_keeps_none() -> None:
    assert DatabaseInspection(tables=frozenset({"other"}), meta=None).meta is None


def test_inspection_with_meta_requires_the_meta_table() -> None:
    with pytest.raises(ValidationError, match="meta"):
        DatabaseInspection(tables=frozenset({"stores"}), meta={"app": META_APP})


@pytest.mark.parametrize(
    "tables", ["meta", None, frozenset({1})], ids=["string", "none", "non-string-name"]
)
def test_inspection_rejects_tables_that_are_not_a_set_of_names(tables: object) -> None:
    with pytest.raises(ValidationError, match="tables"):
        DatabaseInspection(tables=tables, meta=None)  # ty: ignore[invalid-argument-type] - invalid on purpose


def test_inspection_rejects_meta_that_is_not_a_mapping() -> None:
    with pytest.raises(ValidationError, match="meta"):
        DatabaseInspection(tables=_OURS, meta=[("app", META_APP)])  # ty: ignore[invalid-argument-type] - invalid on purpose


# --- classify ----------------------------------------------------------------------------------


@pytest.mark.parametrize("tables", [frozenset(), set()], ids=["frozenset", "set"])
def test_classify_database_without_tables_is_empty(tables: frozenset[str]) -> None:
    assert classify(DatabaseInspection(tables=tables, meta=None)) is SetupState.EMPTY


def test_classify_our_schema_with_the_client_version_is_current() -> None:
    assert classify(_ours()) is SetupState.CURRENT


def test_classify_ignores_extra_meta_keys_and_extra_tables() -> None:
    inspection = DatabaseInspection(
        tables=_OURS | {"sqlite_stat1"},
        meta={"app": META_APP, "schema_version": "1", "note": "x"},
    )

    assert classify(inspection) is SetupState.CURRENT


def test_classify_our_schema_with_an_older_version_is_outdated() -> None:
    assert classify(_ours("1"), client_version=2) is SetupState.OUTDATED


def test_classify_our_schema_with_a_newer_version_is_newer() -> None:
    assert classify(_ours(str(SCHEMA_VERSION + 1))) is SetupState.NEWER


@pytest.mark.parametrize(
    "inspection",
    [
        pytest.param(DatabaseInspection(tables=frozenset({"users"}), meta=None), id="no-meta"),
        pytest.param(
            DatabaseInspection(tables=frozenset({"meta"}), meta={}), id="empty-meta-table"
        ),
        pytest.param(
            DatabaseInspection(tables=_OURS, meta={"app": "other-tool", "schema_version": "1"}),
            id="other-app",
        ),
        pytest.param(DatabaseInspection(tables=_OURS, meta={"schema_version": "1"}), id="no-app"),
        pytest.param(DatabaseInspection(tables=_OURS, meta={"app": META_APP}), id="no-version"),
    ],
)
def test_classify_tables_without_a_valid_meta_are_foreign(
    inspection: DatabaseInspection,
) -> None:
    assert classify(inspection) is SetupState.FOREIGN


@pytest.mark.parametrize(
    "version",
    ["", "x", "1.0", "0", "-1", "+1", " 1", "1 ", "01", "1_0", "\u0661", "1\n", "9" * 19],
)
def test_classify_a_non_integer_or_invalid_version_is_foreign(version: str) -> None:
    assert classify(_ours(version)) is SetupState.FOREIGN


def test_classify_a_non_string_version_is_foreign() -> None:
    inspection = DatabaseInspection(tables=_OURS, meta={"app": META_APP, "schema_version": 1})  # ty: ignore[invalid-argument-type] - a driver may return anything

    assert classify(inspection) is SetupState.FOREIGN


# --- stored_version ----------------------------------------------------------------------------


def test_stored_version_of_our_schema_is_the_meta_version() -> None:
    assert stored_version(_ours("7")) == 7


@pytest.mark.parametrize(
    "inspection",
    [
        DatabaseInspection(tables=frozenset(), meta=None),
        DatabaseInspection(tables=_OURS, meta={"app": "other", "schema_version": "1"}),
        DatabaseInspection(tables=_OURS, meta={"app": META_APP, "schema_version": "x"}),
    ],
    ids=["empty", "foreign", "invalid-version"],
)
def test_stored_version_is_none_unless_the_schema_is_ours(
    inspection: DatabaseInspection,
) -> None:
    assert stored_version(inspection) is None


# --- decide ------------------------------------------------------------------------------------


@pytest.mark.parametrize("auto_upgrade", [True, False])
@pytest.mark.parametrize(
    ("state", "action"),
    [(SetupState.EMPTY, SetupAction.CREATE), (SetupState.CURRENT, SetupAction.USE)],
)
def test_decide_creates_an_empty_and_uses_a_current_database(
    state: SetupState, action: SetupAction, *, auto_upgrade: bool
) -> None:
    assert decide(state, auto_upgrade=auto_upgrade) is action


def test_decide_upgrades_an_outdated_database_with_auto_upgrade() -> None:
    assert decide(SetupState.OUTDATED, auto_upgrade=True) is SetupAction.UPGRADE


def test_decide_refuses_an_outdated_database_without_auto_upgrade_with_migrate_hint() -> None:
    with pytest.raises(SchemaOutdatedError, match="environment-store migrate"):
        decide(SetupState.OUTDATED, auto_upgrade=False)


@pytest.mark.parametrize("auto_upgrade", [True, False])
def test_decide_refuses_a_newer_database_with_upgrade_hint(*, auto_upgrade: bool) -> None:
    with pytest.raises(SchemaTooNewError, match="upgrade environment-store"):
        decide(SetupState.NEWER, auto_upgrade=auto_upgrade)


@pytest.mark.parametrize("auto_upgrade", [True, False])
def test_decide_refuses_a_foreign_database_and_changes_nothing(*, auto_upgrade: bool) -> None:
    with pytest.raises(DatabaseNotCleanError, match="nothing was created or changed"):
        decide(SetupState.FOREIGN, auto_upgrade=auto_upgrade)


@pytest.mark.parametrize("state", [SetupState.OUTDATED, SetupState.NEWER, SetupState.FOREIGN])
def test_decide_errors_name_the_location_and_are_backend_errors(state: SetupState) -> None:
    with pytest.raises(BackendError, match="schema 'team_a'"):
        decide(state, auto_upgrade=False, location="schema 'team_a'")


def test_setup_enums_have_the_planned_members() -> None:
    assert [state.value for state in SetupState] == [
        "empty",
        "current",
        "outdated",
        "newer",
        "foreign",
    ]
    assert [action.value for action in SetupAction] == ["create", "use", "upgrade"]
