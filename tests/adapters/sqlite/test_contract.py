from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.models import StoreRecord
from tests.adapters.sqlite.backend import sqlite_backend
from tests.contract.adapter_contract import AdapterContract, BackendFactory
from tests.support.strategies import plain_records, sealed_records, store_names


def _first_revision_records() -> st.SearchStrategy[StoreRecord]:
    return st.one_of(plain_records(revisions=st.just(1)), sealed_records(revisions=st.just(1)))


def _any_records() -> st.SearchStrategy[StoreRecord]:
    return st.one_of(plain_records(), sealed_records())


def _contract_body(test: object) -> Callable[..., None]:
    # The undecorated body of a contract `@given` test, through Hypothesis' public handle
    # (`given` is typed as returning a plain callable, so the handle is looked up dynamically).
    body = getattr(getattr(test, "hypothesis", None), "inner_test", None)
    assert callable(body), f"{test!r} is not a Hypothesis test"
    return body


class TestSqliteAdapterContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory:
        base = tmp_path_factory.mktemp("sqlite-contract")
        return lambda: sqlite_backend(base)

    # Hypothesis fails a `@given` method that runs on instances of two classes
    # (HealthCheck.differing_executors), which happens as soon as a second AdapterContract
    # subclass runs in the same session. Until the contract suite handles that, this class
    # runs the contract's test bodies in its own `@given` tests with the contract's strategies.

    @given(names=st.sets(store_names(), max_size=6))
    def test_listing_any_names_is_sorted(
        self, make_backend: BackendFactory, names: set[str]
    ) -> None:
        body = _contract_body(AdapterContract.test_listing_any_names_is_sorted)
        body(self, make_backend, names)

    @given(record=_first_revision_records())
    def test_create_then_read_round_trips_any_record(
        self, make_backend: BackendFactory, record: StoreRecord
    ) -> None:
        body = _contract_body(AdapterContract.test_create_then_read_round_trips_any_record)
        body(self, make_backend, record)

    @given(initial=_first_revision_records(), replacement=_any_records())
    def test_write_then_read_round_trips_any_record(
        self, make_backend: BackendFactory, initial: StoreRecord, replacement: StoreRecord
    ) -> None:
        body = _contract_body(AdapterContract.test_write_then_read_round_trips_any_record)
        body(self, make_backend, initial, replacement)


def test_every_hypothesis_test_of_the_contract_is_wrapped() -> None:
    contract = {
        name for name, member in vars(AdapterContract).items() if hasattr(member, "hypothesis")
    }
    wrapped = {name for name in vars(TestSqliteAdapterContract) if name.startswith("test_")}

    assert contract == wrapped
