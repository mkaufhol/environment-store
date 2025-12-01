"""
Tests for ParameterStore read operations.

This module contains tests that verify the ParameterStore class correctly handles
read operations including get_parameter, get_parameter_value, get_parameters_by_path,
and get_parameters_by_path_as_dict methods.
"""

import pytest

from aws_environment_store_manager.ssm_parameter_store.models import (
    ParameterResponse,
    Parameter,
    ParametersByPathResponse,
)


class TestParameterStoreReadOperations:
    """Test suite for ParameterStore read operations."""

    def test_get_parameter_returns_parameter_dict_when_parameter_exists(self, parameter_store):
        """
        Test that get_parameter returns the correct parameter dict when the parameter exists.

        This test demonstrates:
        - How to create a parameter in the mocked Parameter Store
        - How to retrieve and verify the parameter dict
        - Basic read operation testing pattern
        """
        # Arrange: Create a parameter in the mocked Parameter Store
        parameter_name = "/test/database/HOST"
        expected_value = "localhost"
        parameter_store.create_parameter(parameter=parameter_name, value=expected_value)

        # Act: Retrieve the parameter
        parameter_dict = parameter_store.get_parameter(parameter_name)

        # Assert: Verify the retrieved parameter matches what was stored
        assert parameter_dict is not None
        assert isinstance(parameter_dict, ParameterResponse)
        assert parameter_dict.Parameter.Value == expected_value
        assert parameter_dict.Parameter.Name == parameter_name
        assert parameter_dict.Parameter.Type == "String"
        assert parameter_dict.Parameter.Version == 1
        assert parameter_dict.Parameter.DataType == "text"

    def test_get_parameter_value_returns_value_when_parameter_exists(self, parameter_store):
        """
        Test that get_parameter_value returns the correct value for an existing parameter.

        This test demonstrates:
        - How to create a parameter in the mocked Parameter Store
        - How to retrieve and verify the parameter value
        - Basic read operation testing pattern
        """
        # Arrange: Create a parameter in the mocked Parameter Store
        parameter_name = "/test/database/host"
        expected_value = "localhost"
        parameter_store.create_parameter(parameter=parameter_name, value=expected_value)

        # Act: Retrieve the parameter value
        actual_value = parameter_store.get_parameter_value(parameter_name)

        # Assert: Verify the retrieved value matches what was stored
        assert actual_value == expected_value

    def test_get_parameter_returns_none_when_parameter_does_not_exist(self, parameter_store):
        """
        Test that get_parameter returns None for a non-existent parameter.

        This test demonstrates:
        - How the wrapper handles missing parameters gracefully
        - Testing error handling without raising exceptions
        """
        # Act: Try to retrieve a parameter that doesn't exist
        result = parameter_store.get_parameter("/nonexistent/parameter")

        # Assert: Verify that None is returned
        assert result is None

    def test_get_parameters_by_path_returns_list_of_parameters(self, parameter_store):
        """
        Test that get_parameters_by_path returns a list of parameters under a path.

        This test demonstrates:
        - How to create multiple parameters in the mocked Parameter Store
        - How to retrieve and verify a list of parameters
        - Basic read operation testing pattern
        """
        # Arrange: Create parameters in the mocked Parameter Store
        parameter_store.create_parameter(parameter="/test/database/host", value="localhost")
        parameter_store.create_parameter(parameter="/test/database/port", value="5432")
        parameter_store.create_parameter(parameter="/test/database/user", value="admin")
        parameter_store.create_parameter(
            parameter="/test/api/key", value="secret-api-key-12345"
        )

        # Act: Retrieve parameters under the path
        parameters = parameter_store.get_parameters_by_path(path="/test/database")

        # Assert: Verify the retrieved parameters
        assert isinstance(parameters, ParametersByPathResponse)
        assert len(parameters.Parameters) == 3
        assert all(isinstance(param, Parameter) for param in parameters.Parameters)

    def test_get_parameters_by_path_returns_none_when_path_does_not_exist(
        self, parameter_store
    ):
        """
        Test that get_parameters_by_path returns None for a non-existent path.

        This test demonstrates:
        - How the wrapper handles missing paths gracefully
        - Testing error handling without raising exceptions
        """
        # Act: Try to retrieve parameters from a non-existent path
        parameters = parameter_store.get_parameters_by_path(path="/nonexistent/path")

        # Assert: Verify that None is returned
        assert isinstance(parameters, ParametersByPathResponse)
        assert len(parameters.Parameters) == 0

    def test_get_parameters_by_path_returns_list_of_parameters_recursively(
        self, parameter_store
    ):
        """
        Test that get_parameters_by_path returns a list of parameters under a path recursively.

        This test demonstrates:
        - How to create a hierarchy of parameters in the mocked Parameter Store
        - How to retrieve and verify a list of parameters recursively
        - Basic read operation testing pattern
        """
        # Arrange: Create a hierarchy of parameters in the mocked Parameter Store
        parameter_store.create_parameter(parameter="/test/database/host", value="localhost")
        parameter_store.create_parameter(parameter="/test/database/port", value="5432")
        parameter_store.create_parameter(parameter="/test/database/user", value="admin")
        parameter_store.create_parameter(
            parameter="/test/api/key", value="secret-api-key-12345"
        )

        # Act: Retrieve parameters under the path recursively
        parameters = parameter_store.get_parameters_by_path(path="/test", recursive=True)

        # Assert: Verify the retrieved parameters
        assert isinstance(parameters, ParametersByPathResponse)
        assert len(parameters.Parameters) == 4
        assert all(isinstance(param, Parameter) for param in parameters.Parameters)

    def test_get_parameters_by_path_empty_path(self, parameter_store):
        """Test that get_parameters_by_path raises ValueError for empty path."""
        with pytest.raises(ValueError):
            parameter_store.get_parameters_by_path(path="")

    def test_get_parameters_by_path_without_clean_string(self, parameter_store):
        """Test that get_parameters_by_path does not clean the path when clean_string=False."""
        parameter_store.clean_string = False
        with pytest.raises(ValueError):
            parameter_store.get_parameters_by_path(path="relative/path")

    def test_get_parameters_by_path_as_dict_returns_list_of_parameters(self, parameter_store):
        """Test that get_parameters_by_path_as_dict returns a dict of parameters under a path."""
        # Arrange: Create parameters in the mocked Parameter Store
        parameter_store.create_parameter(parameter="/test/database/host", value="localhost")
        parameter_store.create_parameter(parameter="/test/database/port", value="5432")
        parameter_store.create_parameter(parameter="/test/database/user", value="admin")
        parameter_store.create_parameter(
            parameter="/test/api/key", value="secret-api-key-12345"
        )

        # Act: Retrieve parameters under the path as a dict
        parameters = parameter_store.get_parameters_by_path_as_dict(path="/test/database")

        # Assert: Verify the retrieved parameters
        assert isinstance(parameters, dict)
        assert len(parameters) == 3
        assert all(
            isinstance(key, str) and isinstance(value, str) for key, value in parameters.items()
        )
        assert parameters == {
            "/test/database/host": "localhost",
            "/test/database/port": "5432",
            "/test/database/user": "admin",
        }

    def test_get_parameters_by_path_as_dict_returns_list_of_parameters_recursively(
        self, parameter_store
    ):
        """Test that get_parameters_by_path_as_dict returns a dict of parameters under a path recursively."""
        # Arrange: Create a hierarchy of parameters in the mocked Parameter Store
        parameter_store.create_parameter(parameter="/test/database/host", value="localhost")
        parameter_store.create_parameter(parameter="/test/database/port", value="5432")
        parameter_store.create_parameter(parameter="/test/database/user", value="admin")
        parameter_store.create_parameter(
            parameter="/test/api/key", value="secret-api-key-12345"
        )

        # Act: Retrieve parameters under the path as a dict recursively
        parameters = parameter_store.get_parameters_by_path_as_dict(
            path="/test", recursive=True
        )

        # Assert: Verify the retrieved parameters
        assert isinstance(parameters, dict)
        assert len(parameters) == 4
        assert all(
            isinstance(key, str) and isinstance(value, str) for key, value in parameters.items()
        )
        assert parameters == {
            "/test/database/host": "localhost",
            "/test/database/port": "5432",
            "/test/database/user": "admin",
            "/test/api/key": "secret-api-key-12345",
        }

    def test_get_parameters_by_path_as_dict_returns_empty_dict_when_path_does_not_exist(
        self, parameter_store
    ):
        """Test that get_parameters_by_path_as_dict returns an empty dict for a non-existent path."""
        # Act: Retrieve parameters from a non-existent path as a dict
        parameters = parameter_store.get_parameters_by_path_as_dict(path="/nonexistent/path")

        # Assert: Verify that an empty dict is returned
        assert isinstance(parameters, dict)
        assert len(parameters) == 0

    def test_get_parameters_by_path_as_dict_empty_path(self, parameter_store):
        """Test that get_parameters_by_path_as_dict raises ValueError for empty path."""
        with pytest.raises(ValueError):
            parameter_store.get_parameters_by_path_as_dict(path="")

    def test_get_parameter_value_returns_none_when_parameter_does_not_exist(
        self, parameter_store
    ):
        """
        Test that get_parameter_value returns None for a non-existent parameter.

        This test demonstrates:
        - How the wrapper handles missing parameters gracefully in get_parameter_value
        - Testing error handling without raising exceptions
        """
        # Act: Try to retrieve a parameter value that doesn't exist
        result = parameter_store.get_parameter_value("/nonexistent/parameter")

        # Assert: Verify that None is returned
        assert result is None

    def test_get_parameter_with_illegal_characters_raises_error(self, parameter_store):
        """Test that get_parameter raises ValueError for parameter names with illegal characters."""
        # Act & Assert: Try to get a parameter with illegal characters
        with pytest.raises(ValueError) as exc_info:
            parameter_store.get_parameter("/test/param@invalid")

        # Assert: Verify the exception message mentions illegal characters
        assert "Illegal characters" in str(exc_info.value)

    def test_get_parameter_with_whitespace_only_raises_error(self, parameter_store):
        """Test that get_parameter raises ValueError for whitespace-only parameter names."""
        # Act & Assert: Try to get a parameter with only whitespace
        with pytest.raises(ValueError) as exc_info:
            parameter_store.get_parameter("   ")

        # Assert: Verify the exception message
        assert "String cannot be empty" in str(exc_info.value)

    def test_get_parameters_by_path_with_illegal_characters_raises_error(self, parameter_store):
        """Test that get_parameters_by_path raises ValueError for paths with illegal characters."""
        # Act & Assert: Try to get parameters with illegal characters in path
        with pytest.raises(ValueError) as exc_info:
            parameter_store.get_parameters_by_path("/test/path@invalid")

        # Assert: Verify the exception message mentions illegal characters
        assert "Illegal characters" in str(exc_info.value)
