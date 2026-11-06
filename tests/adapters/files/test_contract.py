from typing import Any

import pytest
from hypothesis import given

from tests.adapters.files.backend import file_backend
from tests.contract.adapter_contract import AdapterContract, BackendFactory


def _own_property_tests[C: type[AdapterContract]](cls: C) -> C:
    """Give `cls` its own copy of every Hypothesis test of the contract.

    Hypothesis fails a `@given` method that runs on instances of several classes
    (`HealthCheck.differing_executors`), which happens as soon as one session runs more than
    one contract subclass. Re-wrapping the inner test per subclass is the fix Hypothesis asks
    for; it belongs in `AdapterContract.__init_subclass__` (reported as a shared issue).
    """
    for name, test in vars(AdapterContract).items():
        handle: Any = getattr(test, "hypothesis", None)
        if handle is not None:
            setattr(cls, name, given(**handle._given_kwargs)(handle.inner_test))
    return cls


@_own_property_tests
class TestJsonContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory:
        return lambda: file_backend(tmp_path_factory, scheme="json")


@_own_property_tests
class TestTomlContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory:
        return lambda: file_backend(tmp_path_factory, scheme="toml")
