from collections.abc import Callable

import pytest
from hypothesis import given, settings

from tests.adapters.sqlite.backend import sqlite_backend
from tests.contract.adapter_contract import AdapterContract, BackendFactory

# Hypothesis fails a `@given` method that runs on instances of two classes
# (HealthCheck.differing_executors), which happens as soon as a second AdapterContract subclass
# runs in the same session. Until the contract suppresses that check (reported as a shared
# issue), this class gets its own `@given` test for each of the contract's: the same body, the
# same strategy objects and the same settings, taken from the contract test itself, so the
# input space cannot drift from the contract's.


def _contract_hypothesis_tests() -> dict[str, object]:
    return {
        name: member
        for name, member in vars(AdapterContract).items()
        if hasattr(member, "hypothesis")
    }


def _own_given_test(test: object) -> Callable[..., None]:
    # `inner_test` is public; the strategies (`_given_kwargs`) and the settings have no public
    # handle (and `given` is typed as returning a plain callable, so they are looked up
    # dynamically). Every example builds a fresh backend, so sharing the body is safe.
    handle = getattr(test, "hypothesis")  # noqa: B009
    own = given(**handle._given_kwargs)(handle.inner_test)
    return settings(getattr(test, "_hypothesis_internal_use_settings"))(own)  # noqa: B009


class TestSqliteAdapterContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory:
        base = tmp_path_factory.mktemp("sqlite-contract")
        return lambda: sqlite_backend(base)


for _name, _test in _contract_hypothesis_tests().items():
    setattr(TestSqliteAdapterContract, _name, _own_given_test(_test))


@pytest.mark.parametrize(
    "name",
    sorted(_contract_hypothesis_tests()),
)
def test_wrapped_tests_draw_from_exactly_the_contract_strategies(name: str) -> None:
    contract = getattr(AdapterContract, name).hypothesis
    wrapped = vars(TestSqliteAdapterContract)[name].hypothesis

    assert wrapped is not contract
    assert wrapped.inner_test is contract.inner_test
    assert wrapped._given_kwargs.keys() == contract._given_kwargs.keys()
    for argument, strategy in contract._given_kwargs.items():
        assert wrapped._given_kwargs[argument] is strategy
