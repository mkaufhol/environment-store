"""
This module provides a wrapper around the boto3 secrets manager client to make interactions with the AWS Secrets Manager easier.
"""

import boto3


class SecretsManager:
    """
    This is a wrapper around the boto3 secrets manager client to make interactions with the AWS Secrets Manager easier.
    """

    def __init__(self, region: str, clean_string: bool = True):
        """
        Initialize the SecretsManager class.

        :param region: The AWS region to use
        :param clean_string: If set to True, the secret name will be cleaned to be a valid pathlike string.
        """
        self.client = boto3.client("secretsmanager", region_name=region)
        self.clean_string = clean_string
