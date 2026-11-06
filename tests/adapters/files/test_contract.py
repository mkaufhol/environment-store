from typing import TYPE_CHECKING, override

import pytest
from hypothesis import given
from hypothesis.core import HypothesisHandle

from tests.adapters.files.backend import file_backend
from tests.contract.adapter_contract import AdapterContract, BackendFactory

if TYPE_CHECKING:
    from hypothesis.strategies import SearchStrategy


def _property_tests() -> dict[str, HypothesisHandle]:
    """The Hypothesis tests of the contract, by method name."""
    handles: dict[str, HypothesisHandle] = {}
    for name, test in vars(AdapterContract).items():
        handle = getattr(test, "hypothesis", None)
        if isinstance(handle, HypothesisHandle):
            handles[name] = handle
    return handles


def _own_property_tests[C: type[AdapterContract]](cls: C) -> C:
    """Give `cls` its own copy of every Hypothesis test of the contract.

    Hypothesis fails a `@given` method that runs on instances of several classes
    (`HealthCheck.differing_executors`), which happens as soon as one session runs more than
    one contract subclass. Re-wrapping the inner test per subclass is the fix Hypothesis asks
    for. It belongs in `AdapterContract.__init_subclass__` (reported as a shared issue); until
    then this reads the strategies from `_given_kwargs`, for which Hypothesis has no public
    accessor. `test_every_property_test_is_rewrapped_per_subclass` fails loudly if a Hypothesis
    release changes that.
    """
    for name, handle in _property_tests().items():
        strategies: dict[str, SearchStrategy[object]] = dict(handle._given_kwargs)
        setattr(cls, name, given(**strategies)(handle.inner_test))
    return cls


@_own_property_tests
class TestJsonContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    @override
    def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory:
        return lambda: file_backend(tmp_path_factory, scheme="json")


@_own_property_tests
class TestTomlContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    @override
    def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory:
        return lambda: file_backend(tmp_path_factory, scheme="toml")


def test_every_property_test_is_rewrapped_per_subclass() -> None:
    names = set(_property_tests())

    assert names  # the contract has property tests, and they are still recognised
    for cls in (TestJsonContract, TestTomlContract):
        for name in names:
            own = getattr(cls, name)
            assert own is not getattr(AdapterContract, name)
            assert isinstance(getattr(own, "hypothesis", None), HypothesisHandle)
    assert all(getattr(TestJsonContract, n) is not getattr(TestTomlContract, n) for n in names)
