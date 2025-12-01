"""
This module provides a wrapper around the boto3 ssm client to make interactions with the AWS Parameter Store easier.
"""

from __future__ import annotations

from typing import Optional, Literal

import boto3

from .decorators import clean_and_validate_string
from .exceptions import ParameterAlreadyExists, ParameterNotFoundError
from .models import (
    AWSTag,
    ParameterResponse,
    ParametersByPathResponse,
    DeleteParametersResponse,
)


class ParameterStore:
    """
    This is a wrapper around the boto3 ssm client to make interactions with the AWS Parameter Store easier.
    """

    def __init__(self, region: str, clean_string: bool = True):
        """
        Initialize the ParameterStore class.

        :param region: The AWS region to use
        :param clean_string: If set to True, the parameter name will be cleaned to be a valid pathlike string.
        """
        self.client = boto3.client("ssm", region_name=region)
        self.clean_string = clean_string

    ###################
    # Read operations #
    ###################

    @clean_and_validate_string
    def get_parameter(self, parameter: str) -> ParameterResponse | None:
        """
        Get the raw parameter response.

        AWS Docs: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ssm/client/get_parameter.html

        :param parameter: Parameter Name
        :return: The Value of the parameter of set group if exists, else None
        """
        try:
            response = self.client.get_parameter(Name=parameter, WithDecryption=True)
        except self.client.exceptions.ParameterNotFound:
            return None

        return ParameterResponse.model_validate(response)

    @clean_and_validate_string
    def get_parameter_value(self, parameter: str) -> str | None:
        """
        Get a parameter value.

        AWS Docs: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ssm/client/get_parameter.html

        :param parameter: Parameter Name
        :return: The Value of the parameter, else None
        """
        parameter_dict = self.get_parameter(parameter)
        if not parameter_dict:
            return None
        return parameter_dict.Parameter.Value

    @clean_and_validate_string
    def get_parameters_by_path(
        self, path: str, recursive: bool = False
    ) -> ParametersByPathResponse:
        """
        Get parameters by path.

        AWS Docs: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ssm/client/get_parameters_by_path.html

        :param path: Parameter Path
        :param recursive: If set to True, the path will be searched recursively and all parameters below the path will be returned.
        :return: The fetched parameters as a ParametersByPathResponse object.
        """
        response = self.client.get_parameters_by_path(
            Path=path, Recursive=recursive, WithDecryption=True
        )
        return ParametersByPathResponse.model_validate(response)

    @clean_and_validate_string
    def get_parameters_by_path_as_dict(
        self, path: str, recursive: bool = False
    ) -> dict[str, str]:
        """
        Get parameters by path as a dict.

        AWS Docs: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ssm/client/get_parameters_by_path.html

        :param path: Parameter Path
        :param recursive: If set to True, the path will be searched recursively and all parameters below the path will be returned.
        :return: The fetched parameters as a dict with the parameter name as key and the value as value.
        """
        response = self.get_parameters_by_path(path, recursive)
        return {param.Name: param.Value for param in response.Parameters}

    ####################
    # Write operations #
    ####################

    @clean_and_validate_string
    def _put_parameter(
        self,
        overwrite: bool,
        parameter: str,
        value: str,
        parameter_type: Literal["String", "StringList", "SecureString"] = "String",
        tier: Literal["Standard", "Advanced"] = "Standard",
        description: Optional[str] = None,
        encryption_key_id: Optional[str] = None,
        tags: Optional[list[AWSTag | dict[str, str]]] = None,
    ) -> dict[str, str]:
        """
        Wrapper around the boto3 ssm put_parameter function.

        AWS Docs: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ssm/client/put_parameter.html

        :param overwrite:
        :param parameter:
        :param value:
        :param parameter_type:
        :param tier:
        :param description:
        :param encryption_key_id:
        :param tags:
        :return:
        """
        request_params: dict[str, bool | str | list[AWSTag | dict[str, str]]] = {
            "Overwrite": overwrite,
            "Name": parameter,
            "Value": value,
            "Type": parameter_type,
            "Tier": tier,
        }
        if description:
            request_params["Description"] = description
        if tags:
            # Validate tag input
            tags = [
                AWSTag.model_validate(tag) if isinstance(tag, dict) else tag for tag in tags
            ]
            request_params["Tags"] = [tag.model_dump() for tag in tags]
        if encryption_key_id:
            request_params["KeyId"] = encryption_key_id

        try:
            self.client.put_parameter(**request_params)
        except self.client.exceptions.ParameterAlreadyExists:
            raise ParameterAlreadyExists(parameter)

        return {parameter: value}

    @clean_and_validate_string
    def create_parameter(
        self,
        parameter: str,
        value: str,
        parameter_type: Literal["String", "StringList", "SecureString"] = "String",
        tier: Literal["Standard", "Advanced"] = "Standard",
        description: Optional[str] = None,
        encryption_key_id: Optional[str] = None,
        tags: Optional[list[AWSTag | dict[str, str]]] = None,
    ) -> dict[str, str]:
        """
        Create a parameter store entry in AWS. This method ensures that the parameter does not already exist.

        :param parameter: The Manager will store the value under the set group and parameter, if a group is set upon initialization. Allowed characters: a-zA-Z0-9_.-
        :param value: The value that should be stored. Standard parameters have a value limit of 4 KB. Advanced parameters have a value limit of 8 KB.
        :param parameter_type: Set the parameter type. Options: "String" | "StringList" | "SecureString", default = "String"
        :param tier: Set the tier option for the parameter. Options: "Standard" | "Advanced", default = "Standard"
        :param description: (optional)
        :param encryption_key_id: (optional) Set the KMS id if using parameter_type "SecureString". If not set, the default key is used.
        :param tags: (optional) Set optional AWS tags. Use a list with dicts in the format of AWSTag {"Key": ..., "Value": ...}.
        :return: The created parameter as a dict with the parameter name as key and the value as value.
        """
        return self._put_parameter(
            overwrite=False,
            parameter=parameter,
            value=value,
            parameter_type=parameter_type,
            tier=tier,
            description=description,
            encryption_key_id=encryption_key_id,
            tags=tags,
        )

    @clean_and_validate_string
    def update_or_create_parameter(
        self,
        parameter: str,
        value: str,
        parameter_type: Literal["String", "StringList", "SecureString"] = "String",
        tier: Literal["Standard", "Advanced"] = "Standard",
        description: Optional[str] = None,
        encryption_key_id: Optional[str] = None,
        tags: Optional[list[AWSTag | dict[str, str]]] = None,
    ) -> dict[str, str]:
        """
        Update a parameter store entry in AWS. If the parameter does not exist, it will be created.

        :param parameter: The Manager will store the value under the set group and parameter, if a group is set upon initialization. Allowed characters: a-zA-Z0-9_.-
        :param value: The value that should be stored. Standard parameters have a value limit of 4 KB. Advanced parameters have a value limit of 8 KB.
        :param parameter_type: Set the parameter type. Options: "String" | "StringList" | "SecureString", default = "String"
        :param tier: Set the tier option for the parameter. Options: "Standard" | "Advanced", default = "Standard"
        :param description: (optional)
        :param encryption_key_id: (optional) Set the KMS id if using parameter_type "SecureString". If not set, the default key is used.
        :param tags: (optional) Set optional AWS tags. Use a list with dicts in the format of AWSTag {"Key": ..., "Value": ...}.
        :return: The created parameter as a dict with the parameter name as key and the value as value.
        """
        return self._put_parameter(
            overwrite=True,
            parameter=parameter,
            value=value,
            parameter_type=parameter_type,
            tier=tier,
            description=description,
            encryption_key_id=encryption_key_id,
            tags=tags,
        )

    @clean_and_validate_string
    def update_parameter(
        self,
        parameter: str,
        value: str,
        parameter_type: Literal["String", "StringList", "SecureString"] = "String",
        tier: Literal["Standard", "Advanced"] = "Standard",
        description: Optional[str] = None,
        encryption_key_id: Optional[str] = None,
        tags: Optional[list[AWSTag | dict[str, str]]] = None,
    ) -> dict[str, str]:
        """
        Update a parameter store entry in AWS only if it exists.

        :param parameter: The Manager will store the value under the set group and parameter, if a group is set upon initialization. Allowed characters: a-zA-Z0-9_.-
        :param value: The value that should be stored. Standard parameters have a value limit of 4 KB. Advanced parameters have a value limit of 8 KB.
        :param parameter_type: Set the parameter type. Options: "String" | "StringList" | "SecureString", default = "String"
        :param tier: Set the tier option for the parameter. Options: "Standard" | "Advanced", default = "Standard"
        :param description: (optional)
        :param encryption_key_id: (optional) Set the KMS id if using parameter_type "SecureString". If not set, the default key is used.
        :param tags: (optional) Set optional AWS tags. Use a list with dicts in the format of AWSTag {"Key": ..., "Value": ...}.
        :return: The created parameter as a dict with the parameter name as key and the value as value.
        """
        if self.get_parameter(parameter) is None:
            raise ParameterNotFoundError(parameter)

        return self._put_parameter(
            overwrite=True,
            parameter=parameter,
            value=value,
            parameter_type=parameter_type,
            tier=tier,
            description=description,
            encryption_key_id=encryption_key_id,
            tags=tags,
        )

    @clean_and_validate_string
    def delete_parameter(self, parameter: str) -> None:
        """
        Delete a parameter store entry in AWS.

        :param parameter: The Manager will store the value under the set group and parameter, if a group is set upon initialization. Allowed characters: a-zA-Z0-9_.-
        :return: None
        """
        try:
            self.client.delete_parameter(Name=parameter)
        except self.client.exceptions.ParameterNotFound:
            raise ParameterNotFoundError(parameter)

    @clean_and_validate_string
    def delete_parameters(self, parameters: list[str]) -> DeleteParametersResponse:
        """
        Delete multiple parameter store entries in AWS.

        :param parameters: The Manager will store the value under the set group and parameter, if a group is set upon initialization. Allowed characters: a-zA-Z0-9_.-
        :return: None
        """
        response = self.client.delete_parameters(Names=parameters)
        return DeleteParametersResponse.model_validate(response)
