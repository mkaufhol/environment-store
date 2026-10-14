from pydantic import BaseModel


class Variable(BaseModel):
    name: str
    value: str


class Service(BaseModel):
    name: str
    variables: list[Variable]


class Environment(BaseModel):
    name: str
    variables: list[Variable]
    services: list[Service]


class Project(BaseModel):
    name: str
    variables: list[Variable]
    environments: list[Environment]


class Organization(BaseModel):
    name: str
    variables: list[Variable]
    projects: list[Project]


class TransferConflict(BaseModel):
    """A variable that exists in the destination with a different value."""

    path: list[str]
    name: str


class TransferResult(BaseModel):
    """What ``EnvironmentStoreManager.import_from`` did (or would do when run as a dry run)."""

    levels: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    conflicts: list[TransferConflict] = []
