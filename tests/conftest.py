import os

from hypothesis import settings

# Adapter tests touch disks and databases, so per-example deadlines would only cause flakiness.
settings.register_profile("default", deadline=None)
# CI runs a fixed, reproducible set of examples.
settings.register_profile("ci", deadline=None, max_examples=200, derandomize=True, database=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
