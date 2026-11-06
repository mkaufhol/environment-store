"""JSON and TOML file adapters: one file per store in a directory (D9, spec §3.2).

`open_json` and `open_toml` are the factories registered for the `json://` and `toml://`
schemes. Imports `environment_store.core` and the built-in TOML writer only.
"""

from environment_store.adapters.files.adapter import (
    DEFAULT_LOCK_TIMEOUT,
    FileAdapter,
    open_json,
    open_toml,
)
from environment_store.adapters.files.directories import make_private_directory
from environment_store.adapters.files.layout import (
    FILE_FORMAT_VERSION,
    document_to_info,
    document_to_record,
    record_to_document,
)
from environment_store.adapters.files.locking import exclusive_lock
from environment_store.adapters.files.serializers import (
    JSON_SERIALIZER,
    TOML_SERIALIZER,
    FileSerializer,
)
from environment_store.adapters.files.url import directory_from_url

__all__ = [
    "DEFAULT_LOCK_TIMEOUT",
    "FILE_FORMAT_VERSION",
    "JSON_SERIALIZER",
    "TOML_SERIALIZER",
    "FileAdapter",
    "FileSerializer",
    "directory_from_url",
    "document_to_info",
    "document_to_record",
    "exclusive_lock",
    "make_private_directory",
    "open_json",
    "open_toml",
    "record_to_document",
]
