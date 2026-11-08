"""Storage backends: file adapters, SQLite and PostgreSQL, plus the shared SQL layer.

Adapters import `environment_store.core` (and `environment_store.adapters.sql`), never the service
or crypto layers: they store opaque records and know nothing about encryption.
"""
