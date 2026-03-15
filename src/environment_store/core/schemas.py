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
