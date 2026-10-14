"""The variable hierarchy: organisation > project > environment > service."""

LEVELS = ("organisation", "project", "environment", "service")

Path = tuple[str, ...]


def to_kwargs(path: Path) -> dict[str, str | None]:
    """Turn a path like ``("acme", "web")`` into manager keyword arguments."""
    if len(path) > len(LEVELS):
        raise ValueError(f"A path has at most {len(LEVELS)} levels, got {len(path)}")
    return {level: (path[i] if i < len(path) else None) for i, level in enumerate(LEVELS)}


def to_path(
    organisation: str | None = None,
    project: str | None = None,
    environment: str | None = None,
    service: str | None = None,
) -> Path:
    """Turn manager keyword arguments into a path. The root level is the empty path."""
    return tuple(
        value for value in (organisation, project, environment, service) if value is not None
    )


def level_kind(path: Path) -> str:
    """The kind of level a non-empty path points to, e.g. ``"project"``."""
    if not path:
        raise ValueError("The root level has no kind")
    return LEVELS[len(path) - 1]


def child_kind(path: Path) -> str | None:
    """The kind of level below ``path``, or ``None`` if ``path`` is a service."""
    return LEVELS[len(path)] if len(path) < len(LEVELS) else None


def describe(path: Path) -> str:
    return " / ".join(path) if path else "root"
