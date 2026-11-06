"""Cheap Argon2id parameters, so that tests with passphrase stores stay fast."""

from environment_store.core.models import KdfParams

__all__ = ["CheapKdf"]


class CheapKdf:
    """A `kdf_params_factory` with the cheapest Argon2id parameters and a new salt per call."""

    calls: int

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> KdfParams:
        self.calls += 1
        return KdfParams(iterations=1, memory_kib=8, lanes=1, salt=self.calls.to_bytes(16, "big"))
