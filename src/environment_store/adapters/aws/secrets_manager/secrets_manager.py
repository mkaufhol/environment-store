"""
This module provides a wrapper around the boto3 secrets manager client to make interactions with the AWS Secrets Manager easier.
"""

import boto3


class SecretsManager:
    """
    This is a wrapper around the boto3 secrets manager client to make interactions with the AWS Secrets Manager easier.

    It only implements the functionality needed by the SecretsManagerAdapter. For everything else
    use the underlying boto3 client via the ``client`` attribute.
    """

    def __init__(self, region: str, clean_string: bool = True):
        """
        Initialize the SecretsManager class.

        :param region: The AWS region to use
        :param clean_string: If set to True, the secret name will be cleaned to be a valid pathlike string.
        """
        self.client = boto3.client("secretsmanager", region_name=region)
        self.clean_string = clean_string

    def get_secret_string(self, name: str) -> str | None:
        """Get the string value of a secret, or None if the secret does not exist."""
        try:
            response = self.client.get_secret_value(SecretId=name)
        except self.client.exceptions.ResourceNotFoundException:
            return None
        return response.get("SecretString")

    def put_secret_string(self, name: str, value: str) -> None:
        """Create the secret, or store a new version if it already exists."""
        try:
            self.client.put_secret_value(SecretId=name, SecretString=value)
        except self.client.exceptions.ResourceNotFoundException:
            self.client.create_secret(Name=name, SecretString=value)

    def delete_secret(self, name: str) -> bool:
        """
        Permanently delete a secret without a recovery window so the name can be reused
        immediately. Returns False if the secret does not exist.
        """
        try:
            self.client.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        except self.client.exceptions.ResourceNotFoundException:
            return False
        return True

    def list_secret_names(self, prefix: str) -> list[str]:
        """List the names of all secrets starting with ``prefix``."""
        paginator = self.client.get_paginator("list_secrets")
        names: list[str] = []
        for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
            names += [s["Name"] for s in page["SecretList"]]
        # The name filter matches words, not only prefixes
        return [n for n in names if n.startswith(prefix)]
