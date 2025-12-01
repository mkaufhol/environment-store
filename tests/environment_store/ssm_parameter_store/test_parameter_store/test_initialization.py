"""
Tests for ParameterStore initialization.

This module contains tests that verify the ParameterStore class initializes correctly
with various configurations including region settings and clean_string options.
"""

import pytest
from moto import mock_aws

from aws_environment_store_manager.ssm_parameter_store import ParameterStore


class TestParameterStoreInitialization:
    """Test suite for ParameterStore initialization."""

    def test_initialization_with_valid_region(self, aws_credentials):
        """Test that ParameterStore initializes with a valid region."""
        with mock_aws():
            store = ParameterStore(region="us-east-1")
        assert store.client.meta.region_name == "us-east-1"

    def test_initialization_with_empty_region(self, aws_credentials):
        """Test that ParameterStore raises ValueError with an invalid region."""
        with pytest.raises(ValueError):
            with mock_aws():
                ParameterStore(region="")

    def test_initialization_with_invalid_region(self, aws_credentials):
        """Test that ParameterStore raises ValueError with an invalid region."""
        with pytest.raises(KeyError):
            with mock_aws():
                store = ParameterStore(region="invalid-region")
                store.client.describe_parameters()

    def test_initialization_with_clean_string_false(self, aws_credentials):
        """Test that ParameterStore initializes with clean_string=False."""
        with mock_aws():
            store = ParameterStore(region="us-east-1", clean_string=False)
        assert store.clean_string is False

    def test_initialization_with_clean_string_true(self, aws_credentials):
        """Test that ParameterStore initializes with clean_string=True."""
        with mock_aws():
            store = ParameterStore(region="us-east-1", clean_string=True)
        assert store.clean_string is True

    def test_initialization_with_clean_string_default(self, aws_credentials):
        """Test that ParameterStore initializes with clean_string=True as default."""
        with mock_aws():
            store = ParameterStore(region="us-east-1")
        assert store.clean_string is True
