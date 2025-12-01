"""
Shared fixtures for ParameterStore tests.

This module contains pytest fixtures that are shared across all test modules
in the test_parameter_store package.
"""

import pytest
from moto import mock_aws

from aws_environment_store_manager.ssm_parameter_store import ParameterStore


@pytest.fixture
def aws_credentials(monkeypatch):
    """
    Set up fake AWS credentials for moto.

    This fixture ensures that boto3 doesn't try to use real AWS credentials
    during testing. Moto will intercept AWS API calls regardless of credentials,
    but setting this prevents any accidental real AWS calls if moto fails.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def parameter_store(aws_credentials):
    """
    Create a ParameterStore instance with mocked AWS SSM service.

    This fixture uses moto's mock_aws decorator as a context manager to mock
    the AWS Systems Manager service. The mock is active for the duration of
    each test that uses this fixture.

    Returns:
        ParameterStore: A ParameterStore instance configured for testing
    """
    with mock_aws():
        store = ParameterStore(region="us-east-1", clean_string=True)
        yield store
