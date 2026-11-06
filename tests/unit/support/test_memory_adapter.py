from contextlib import nullcontext
from typing import override

import pytest

from environment_store.core.adapter import SetupMode
from tests.contract.adapter_contract import AdapterContract, BackendFactory
from tests.support.memory_adapter import MemoryAdapter, MemoryBackend


class TestMemoryAdapterContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    @override
    def make_backend(cls) -> BackendFactory:
        return lambda: nullcontext(MemoryBackend())


@pytest.mark.parametrize("setup", list(SetupMode))
def test_memory_adapter_remembers_its_setup_mode(setup: SetupMode) -> None:
    with MemoryBackend().open(setup=setup) as adapter:
        assert adapter.setup is setup


def test_memory_adapter_defaults_to_a_fresh_backend_and_auto_setup() -> None:
    first = MemoryAdapter()
    second = MemoryAdapter()

    assert first.setup is SetupMode.AUTO
    assert first.backend is not second.backend
