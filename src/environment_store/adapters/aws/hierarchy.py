"""
Helpers shared by the AWS adapters to translate the organisation > project > environment >
service hierarchy into path segments.
"""

import re

_SEGMENT_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")


def validate_segment(value: str, label: str) -> str:
    """Ensure a hierarchy name or variable name is non-empty and only uses a-zA-Z0-9_.-"""
    if not isinstance(value, str) or not _SEGMENT_PATTERN.fullmatch(value):
        raise ValueError(
            f"Invalid {label} {value!r}. Names must be non-empty and may only contain "
            "the characters a-zA-Z0-9_.-"
        )
    return value


def level_segments(
    organisation: str | None = None,
    project: str | None = None,
    environment: str | None = None,
    service: str | None = None,
) -> list[str]:
    """Validate the hierarchy rules and return the path segments of the given level."""
    levels = [
        ("organisation", organisation),
        ("project", project),
        ("environment", environment),
        ("service", service),
    ]
    segments: list[str] = []
    missing: str | None = None
    for label, value in levels:
        if value is None:
            missing = missing or label
            continue
        if missing:
            raise ValueError(f"{label} requires {missing} to be specified")
        segments.append(validate_segment(value, label))
    return segments


def child_names(prefix: list[str], full_segments: list[list[str]]) -> list[str]:
    """Return the sorted unique names directly below ``prefix`` seen in ``full_segments``."""
    depth = len(prefix)
    return sorted(
        {
            segments[depth]
            for segments in full_segments
            if len(segments) > depth and segments[:depth] == prefix
        }
    )
