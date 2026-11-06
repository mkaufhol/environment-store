from contextlib import nullcontext

import pytest

from tests.contract.adapter_contract import AdapterContract, BackendFactory
from tests.support.memory_adapter import MemoryBackend

_PROPERTY_TESTS = sorted(
    name for name, member in vars(AdapterContract).items() if hasattr(member, "hypothesis")
)


def _memory_backends() -> BackendFactory:
    return lambda: nullcontext(MemoryBackend())


def test_the_contract_has_property_tests() -> None:
    assert _PROPERTY_TESTS == [
        "test_create_then_read_round_trips_any_record",
        "test_listing_any_names_is_sorted",
        "test_write_then_read_round_trips_any_record",
    ]


@pytest.mark.parametrize("name", _PROPERTY_TESTS)
def test_property_tests_run_on_several_contract_subclasses_in_one_session(name: str) -> None:
    # Every adapter subclasses the contract, so one session runs each inherited `@given` test on
    # instances of several classes; Hypothesis must not reject that as differing executors.
    class FirstContract(AdapterContract):
        pass

    class SecondContract(AdapterContract):
        pass

    for contract in (FirstContract, SecondContract):
        getattr(contract(), name)(make_backend=_memory_backends())
