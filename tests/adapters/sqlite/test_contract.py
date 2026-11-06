from typing import override

import pytest

from tests.adapters.sqlite.backend import sqlite_backend
from tests.contract.adapter_contract import AdapterContract, BackendFactory


class TestSqliteAdapterContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    @override
    def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory:
        base = tmp_path_factory.mktemp("sqlite-contract")
        return lambda: sqlite_backend(base)
