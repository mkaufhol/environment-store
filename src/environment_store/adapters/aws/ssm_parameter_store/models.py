import datetime

from pydantic import BaseModel


class AWSTag(BaseModel):
    Key: str
    Value: str


class Parameter(BaseModel):
    Name: str
    Type: str
    Value: str
    Version: int
    LastModifiedDate: datetime.datetime
    ARN: str
    DataType: str


class ParameterResponse(BaseModel):
    Parameter: Parameter


class ParametersByPathResponse(BaseModel):
    Parameters: list[Parameter]


class DeleteParametersResponse(BaseModel):
    DeletedParameters: list[str]
    InvalidParameters: list[str]
