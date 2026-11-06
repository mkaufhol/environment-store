from typing import override

import pytest

from tests.adapters.files.backend import file_backend
from tests.contract.adapter_contract import AdapterContract, BackendFactory


class TestJsonContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    @override
    def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory:
        return lambda: file_backend(tmp_path_factory, scheme="json")


class TestTomlContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    @override
    def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory:
        return lambda: file_backend(tmp_path_factory, scheme="toml")
