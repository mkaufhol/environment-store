"""
Tests for ParameterStore write operations.

This module contains tests that verify the ParameterStore class correctly handles
write operations including create_parameter, update_parameter, and update_or_create_parameter methods.
"""

import pytest


class TestParameterStoreWriteOperations:
    """Test suite for ParameterStore write operations."""

    def test_create_parameter_stores_value_successfully(self, parameter_store):
        """
        Test that create_parameter successfully stores a parameter.

        This test demonstrates:
        - How to test write operations
        - How to verify the operation by reading back the value
        - Testing the complete write-read cycle
        """
        # Arrange: Define parameter details
        parameter_name = "/test/api/key"
        parameter_value = "secret-api-key-12345"

        # Act: Create the parameter
        result = parameter_store.create_parameter(
            parameter=parameter_name, value=parameter_value
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was actually stored by reading it back
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == parameter_value

    def test_update_or_create_parameter_creates_new_parameter(self, parameter_store):
        """
        Test that update_or_create_parameter creates a parameter when it doesn't exist.

        This test demonstrates:
        - Testing upsert operations (create path)
        - Verifying parameter creation through read-back
        """
        # Arrange: Define parameter details for a new parameter
        parameter_name = "/test/config/timeout"
        parameter_value = "30"

        # Act: Call update_or_create on a non-existent parameter
        result = parameter_store.update_or_create_parameter(
            parameter=parameter_name, value=parameter_value
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was created
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == parameter_value

    def test_update_or_create_parameter_updates_existing_parameter(self, parameter_store):
        """
        Test that update_or_create_parameter updates an existing parameter.

        This test demonstrates:
        - Testing upsert operations (update path)
        - Verifying parameter updates by comparing old and new values
        - Testing state changes in the mocked service
        """
        # Arrange: Create an initial parameter
        parameter_name = "/test/config/max_retries"
        initial_value = "3"
        updated_value = "5"

        parameter_store.create_parameter(parameter=parameter_name, value=initial_value)

        # Act: Update the parameter using update_or_create
        result = parameter_store.update_or_create_parameter(
            parameter=parameter_name, value=updated_value
        )

        # Assert: Verify the return value1
        assert result == {parameter_name: updated_value}

        # Assert: Verify the parameter was updated
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == updated_value
        assert stored_value != initial_value

    def test_create_parameter_with_secure_string_type(self, parameter_store):
        """Test that create_parameter successfully stores a SecureString parameter."""
        # Arrange: Define parameter details
        parameter_name = "/test/secure/password"
        parameter_value = "super-secret-password"

        # Act: Create the parameter with SecureString type
        result = parameter_store.create_parameter(
            parameter=parameter_name, value=parameter_value, parameter_type="SecureString"
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was stored with correct type
        parameter_dict = parameter_store.get_parameter(parameter_name)
        assert parameter_dict.Parameter.Value == parameter_value
        assert parameter_dict.Parameter.Type == "SecureString"

    def test_create_parameter_with_string_list_type(self, parameter_store):
        """Test that create_parameter successfully stores a StringList parameter."""
        # Arrange: Define parameter details
        parameter_name = "/test/config/allowed_ips"
        parameter_value = "192.168.1.1,192.168.1.2,192.168.1.3"

        # Act: Create the parameter with StringList type
        result = parameter_store.create_parameter(
            parameter=parameter_name, value=parameter_value, parameter_type="StringList"
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was stored with correct type
        parameter_dict = parameter_store.get_parameter(parameter_name)
        assert parameter_dict.Parameter.Value == parameter_value
        assert parameter_dict.Parameter.Type == "StringList"

    def test_create_parameter_with_advanced_tier(self, parameter_store):
        """Test that create_parameter successfully stores a parameter with Advanced tier."""
        # Arrange: Define parameter details
        parameter_name = "/test/large/data"
        parameter_value = "x" * 5000  # More than 4KB to require Advanced tier

        # Act: Create the parameter with Advanced tier
        result = parameter_store.create_parameter(
            parameter=parameter_name, value=parameter_value, tier="Advanced"
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was stored
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == parameter_value

    def test_create_parameter_with_description(self, parameter_store):
        """Test that create_parameter successfully stores a parameter with description."""
        # Arrange: Define parameter details
        parameter_name = "/test/config/api_endpoint"
        parameter_value = "https://api.example.com"
        description = "API endpoint for external service"

        # Act: Create the parameter with description
        result = parameter_store.create_parameter(
            parameter=parameter_name, value=parameter_value, description=description
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was stored
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == parameter_value

    def test_create_parameter_with_encryption_key_id(self, parameter_store):
        """Test that create_parameter successfully stores a SecureString parameter with custom KMS key."""
        # Arrange: Define parameter details
        parameter_name = "/test/secure/api_key"
        parameter_value = "secret-key-12345"
        encryption_key_id = "alias/aws/ssm"  # Using default AWS managed key

        # Act: Create the parameter with encryption key
        result = parameter_store.create_parameter(
            parameter=parameter_name,
            value=parameter_value,
            parameter_type="SecureString",
            encryption_key_id=encryption_key_id,
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was stored
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == parameter_value

    def test_create_parameter_with_tags_as_dict(self, parameter_store):
        """Test that create_parameter successfully stores a parameter with tags as dict."""
        # Arrange: Define parameter details
        parameter_name = "/test/tagged/resource"
        parameter_value = "tagged-value"
        tags = [{"Key": "Environment", "Value": "Test"}, {"Key": "Owner", "Value": "TestUser"}]

        # Act: Create the parameter with tags
        result = parameter_store.create_parameter(
            parameter=parameter_name, value=parameter_value, tags=tags
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was stored
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == parameter_value

    def test_create_parameter_with_tags_as_awstag(self, parameter_store):
        """Test that create_parameter successfully stores a parameter with tags as AWSTag objects."""
        from aws_environment_store_manager.ssm_parameter_store.models import AWSTag

        # Arrange: Define parameter details
        parameter_name = "/test/tagged/resource2"
        parameter_value = "tagged-value-2"
        tags = [
            AWSTag(Key="Environment", Value="Production"),
            AWSTag(Key="Team", Value="DevOps"),
        ]

        # Act: Create the parameter with AWSTag objects
        result = parameter_store.create_parameter(
            parameter=parameter_name, value=parameter_value, tags=tags
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was stored
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == parameter_value

    def test_create_parameter_with_all_optional_parameters(self, parameter_store):
        """Test that create_parameter successfully stores a parameter with all optional parameters."""
        # Arrange: Define parameter details
        parameter_name = "/test/complete/parameter"
        parameter_value = "complete-value"
        description = "A parameter with all options"
        tags = [{"Key": "Project", "Value": "TestProject"}]

        # Act: Create the parameter with all optional parameters
        result = parameter_store.create_parameter(
            parameter=parameter_name,
            value=parameter_value,
            parameter_type="SecureString",
            tier="Standard",
            description=description,
            encryption_key_id="alias/aws/ssm",
            tags=tags,
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was stored
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == parameter_value

    def test_create_parameter_raises_exception_when_parameter_already_exists(
        self, parameter_store
    ):
        """
        Test that create_parameter raises ParameterAlreadyExists when trying to create an existing parameter.

        This test demonstrates:
        - Testing exception handling for duplicate parameter creation
        - Verifying that the wrapper properly propagates AWS exceptions
        """
        from aws_environment_store_manager.ssm_parameter_store.exceptions import (
            ParameterAlreadyExists,
        )

        # Arrange: Create an initial parameter
        parameter_name = "/test/duplicate/parameter"
        parameter_value = "initial-value"
        parameter_store.create_parameter(parameter=parameter_name, value=parameter_value)

        # Act & Assert: Try to create the same parameter again
        with pytest.raises(ParameterAlreadyExists) as exc_info:
            parameter_store.create_parameter(parameter=parameter_name, value="new-value")

        # Assert: Verify the exception message contains the parameter name
        assert parameter_name in str(exc_info.value)

    def test_update_parameter_updates_existing_parameter(self, parameter_store):
        """
        Test that update_parameter successfully updates an existing parameter.

        This test demonstrates:
        - Testing update operations that require the parameter to exist
        - Verifying parameter updates by comparing old and new values
        """
        # Arrange: Create an initial parameter
        parameter_name = "/test/update/config"
        initial_value = "initial-config"
        updated_value = "updated-config"

        parameter_store.create_parameter(parameter=parameter_name, value=initial_value)

        # Act: Update the parameter
        result = parameter_store.update_parameter(parameter=parameter_name, value=updated_value)

        # Assert: Verify the return value
        assert result == {parameter_name: updated_value}

        # Assert: Verify the parameter was updated
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == updated_value
        assert stored_value != initial_value

    def test_update_parameter_raises_exception_when_parameter_not_found(self, parameter_store):
        """
        Test that update_parameter raises ParameterNotFoundError when parameter doesn't exist.

        This test demonstrates:
        - Testing exception handling for updating non-existent parameters
        - Verifying that update_parameter enforces parameter existence
        """
        from aws_environment_store_manager.ssm_parameter_store.exceptions import (
            ParameterNotFoundError,
        )

        # Arrange: Define a non-existent parameter
        parameter_name = "/test/nonexistent/parameter"
        parameter_value = "some-value"

        # Act & Assert: Try to update a non-existent parameter
        with pytest.raises(ParameterNotFoundError) as exc_info:
            parameter_store.update_parameter(parameter=parameter_name, value=parameter_value)

        # Assert: Verify the exception message contains the parameter name
        assert parameter_name in str(exc_info.value)

    def test_update_parameter_with_optional_parameters_without_tags(self, parameter_store):
        """Test that update_parameter successfully updates a parameter with optional parameters (no tags).

        Note: AWS SSM API doesn't allow tags and overwrite=True together, so we test without tags.
        """
        # Arrange: Create an initial parameter
        parameter_name = "/test/update/complete"
        initial_value = "initial-value"
        updated_value = "updated-value"
        description = "Updated parameter with options"

        parameter_store.create_parameter(parameter=parameter_name, value=initial_value)

        # Act: Update the parameter with optional parameters (no tags due to AWS API limitation)
        result = parameter_store.update_parameter(
            parameter=parameter_name,
            value=updated_value,
            parameter_type="SecureString",
            tier="Standard",
            description=description,
            encryption_key_id="alias/aws/ssm",
        )

        # Assert: Verify the return value
        assert result == {parameter_name: updated_value}

        # Assert: Verify the parameter was updated
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == updated_value

    def test_update_or_create_parameter_with_optional_parameters_without_tags(
        self, parameter_store
    ):
        """Test that update_or_create_parameter works with optional parameters (no tags).

        Note: AWS SSM API doesn't allow tags and overwrite=True together, so we test without tags.
        """
        # Arrange: Define parameter details
        parameter_name = "/test/upsert/complete"
        parameter_value = "upsert-value"
        description = "Upsert parameter with options"

        # Act: Create/update the parameter with optional parameters (no tags due to AWS API limitation)
        result = parameter_store.update_or_create_parameter(
            parameter=parameter_name,
            value=parameter_value,
            parameter_type="String",
            tier="Standard",
            description=description,
        )

        # Assert: Verify the return value
        assert result == {parameter_name: parameter_value}

        # Assert: Verify the parameter was created
        stored_value = parameter_store.get_parameter_value(parameter_name)
        assert stored_value == parameter_value

    def test_create_parameter_with_illegal_characters_raises_error(self, parameter_store):
        """Test that create_parameter raises ValueError for parameter names with illegal characters."""
        # Act & Assert: Try to create a parameter with illegal characters
        with pytest.raises(ValueError) as exc_info:
            parameter_store.create_parameter(parameter="/test/param@invalid", value="value")

        # Assert: Verify the exception message mentions illegal characters
        assert "Illegal characters" in str(exc_info.value)

    def test_create_parameter_with_empty_name_raises_error(self, parameter_store):
        """Test that create_parameter raises ValueError for empty parameter names."""
        # Act & Assert: Try to create a parameter with empty name
        with pytest.raises(ValueError) as exc_info:
            parameter_store.create_parameter(parameter="", value="value")

        # Assert: Verify the exception message
        assert "String cannot be empty" in str(exc_info.value)

    def test_update_parameter_with_illegal_characters_raises_error(self, parameter_store):
        """Test that update_parameter raises ValueError for parameter names with illegal characters."""
        # Act & Assert: Try to update a parameter with illegal characters
        with pytest.raises(ValueError) as exc_info:
            parameter_store.update_parameter(parameter="/test/param@invalid", value="value")

        # Assert: Verify the exception message mentions illegal characters
        assert "Illegal characters" in str(exc_info.value)

    def test_update_or_create_parameter_with_illegal_characters_raises_error(
        self, parameter_store
    ):
        """Test that update_or_create_parameter raises ValueError for parameter names with illegal characters."""
        # Act & Assert: Try to update/create a parameter with illegal characters
        with pytest.raises(ValueError) as exc_info:
            parameter_store.update_or_create_parameter(
                parameter="/test/param@invalid", value="value"
            )

        # Assert: Verify the exception message mentions illegal characters
        assert "Illegal characters" in str(exc_info.value)

    def test_create_parameter_with_clean_string_converts_relative_path(self, parameter_store):
        """Test that create_parameter with clean_string=True converts relative paths to absolute."""
        # Arrange: Define a relative path parameter
        parameter_name = "test/relative/path"
        parameter_value = "test-value"

        # Act: Create the parameter (clean_string is True by default in fixture)
        result = parameter_store.create_parameter(
            parameter=parameter_name, value=parameter_value
        )

        # Assert: Verify the parameter was created with absolute path
        assert "/test/relative/path" in result
        stored_value = parameter_store.get_parameter_value("/test/relative/path")
        assert stored_value == parameter_value

    def test_get_parameter_with_clean_string_converts_relative_path(self, parameter_store):
        """Test that get_parameter with clean_string=True converts relative paths to absolute."""
        # Arrange: Create a parameter with absolute path
        parameter_name = "/test/clean/param"
        parameter_value = "clean-value"
        parameter_store.create_parameter(parameter=parameter_name, value=parameter_value)

        # Act: Retrieve using relative path (clean_string will convert it)
        result = parameter_store.get_parameter("test/clean/param")

        # Assert: Verify the parameter was retrieved
        assert result is not None
        assert result.Parameter.Value == parameter_value

    def test_get_parameters_by_path_with_clean_string_converts_relative_path(
        self, parameter_store
    ):
        """Test that get_parameters_by_path with clean_string=True converts relative paths to absolute."""
        # Arrange: Create parameters with absolute paths
        parameter_store.create_parameter(parameter="/test/clean/path/param1", value="value1")
        parameter_store.create_parameter(parameter="/test/clean/path/param2", value="value2")

        # Act: Retrieve using relative path (clean_string will convert it)
        result = parameter_store.get_parameters_by_path("test/clean/path")

        # Assert: Verify the parameters were retrieved
        assert len(result.Parameters) == 2

    # Delete operations tests

    def test_delete_parameter_successfully_deletes_existing_parameter(self, parameter_store):
        """
        Test that delete_parameter successfully deletes an existing parameter.

        This test demonstrates:
        - How to test delete operations
        - How to verify deletion by attempting to read the parameter
        - Testing the complete create-delete-verify cycle
        """
        # Arrange: Create a parameter
        parameter_name = "/test/delete/param1"
        parameter_value = "value-to-delete"
        parameter_store.create_parameter(parameter=parameter_name, value=parameter_value)

        # Verify parameter exists
        assert parameter_store.get_parameter_value(parameter_name) == parameter_value

        # Act: Delete the parameter
        result = parameter_store.delete_parameter(parameter_name)

        # Assert: Verify the method returns None
        assert result is None

        # Assert: Verify the parameter was deleted
        assert parameter_store.get_parameter(parameter_name) is None

    def test_delete_parameter_raises_exception_when_parameter_not_found(self, parameter_store):
        """
        Test that delete_parameter raises ParameterNotFoundError when parameter doesn't exist.

        This test demonstrates:
        - Testing exception handling for deleting non-existent parameters
        - Verifying that delete_parameter enforces parameter existence
        """
        from aws_environment_store_manager.ssm_parameter_store.exceptions import (
            ParameterNotFoundError,
        )

        # Arrange: Define a non-existent parameter
        parameter_name = "/test/nonexistent/delete"

        # Act & Assert: Try to delete a non-existent parameter
        with pytest.raises(ParameterNotFoundError) as exc_info:
            parameter_store.delete_parameter(parameter_name)

        # Assert: Verify the exception message contains the parameter name
        assert parameter_name in str(exc_info.value)

    def test_delete_parameter_with_illegal_characters_raises_error(self, parameter_store):
        """Test that delete_parameter raises ValueError for parameter names with illegal characters."""
        # Act & Assert: Try to delete a parameter with illegal characters
        with pytest.raises(ValueError) as exc_info:
            parameter_store.delete_parameter("/test/param@invalid")

        # Assert: Verify the exception message mentions illegal characters
        assert "Illegal characters" in str(exc_info.value)

    def test_delete_parameter_with_empty_name_raises_error(self, parameter_store):
        """Test that delete_parameter raises ValueError for empty parameter names."""
        # Act & Assert: Try to delete a parameter with empty name
        with pytest.raises(ValueError) as exc_info:
            parameter_store.delete_parameter("")

        # Assert: Verify the exception message
        assert "String cannot be empty" in str(exc_info.value)

    def test_delete_parameter_with_clean_string_converts_relative_path(self, parameter_store):
        """Test that delete_parameter with clean_string=True converts relative paths to absolute."""
        # Arrange: Create a parameter with absolute path
        parameter_name = "/test/delete/relative"
        parameter_value = "relative-value"
        parameter_store.create_parameter(parameter=parameter_name, value=parameter_value)

        # Act: Delete using relative path (clean_string will convert it)
        parameter_store.delete_parameter("test/delete/relative")

        # Assert: Verify the parameter was deleted
        assert parameter_store.get_parameter(parameter_name) is None

    def test_delete_parameters_successfully_deletes_multiple_parameters(self, parameter_store):
        """
        Test that delete_parameters successfully deletes multiple existing parameters.

        This test demonstrates:
        - How to test batch delete operations
        - How to verify deletion of multiple parameters
        - Testing the DeleteParametersResponse model
        """
        from aws_environment_store_manager.ssm_parameter_store.models import (
            DeleteParametersResponse,
        )

        # Arrange: Create multiple parameters
        param1 = "/test/batch/delete/param1"
        param2 = "/test/batch/delete/param2"
        param3 = "/test/batch/delete/param3"
        parameter_store.create_parameter(parameter=param1, value="value1")
        parameter_store.create_parameter(parameter=param2, value="value2")
        parameter_store.create_parameter(parameter=param3, value="value3")

        # Verify parameters exist
        assert parameter_store.get_parameter_value(param1) == "value1"
        assert parameter_store.get_parameter_value(param2) == "value2"
        assert parameter_store.get_parameter_value(param3) == "value3"

        # Act: Delete multiple parameters
        result = parameter_store.delete_parameters([param1, param2, param3])

        # Assert: Verify the response type
        assert isinstance(result, DeleteParametersResponse)

        # Assert: Verify all parameters were deleted
        assert len(result.DeletedParameters) == 3
        assert param1 in result.DeletedParameters
        assert param2 in result.DeletedParameters
        assert param3 in result.DeletedParameters

        # Assert: Verify no invalid parameters
        assert len(result.InvalidParameters) == 0

        # Assert: Verify parameters no longer exist
        assert parameter_store.get_parameter(param1) is None
        assert parameter_store.get_parameter(param2) is None
        assert parameter_store.get_parameter(param3) is None

    def test_delete_parameters_handles_invalid_parameters(self, parameter_store):
        """
        Test that delete_parameters handles invalid (non-existent) parameters correctly.

        This test demonstrates:
        - How the batch delete handles non-existent parameters
        - How to verify the InvalidParameters list in the response
        """
        from aws_environment_store_manager.ssm_parameter_store.models import (
            DeleteParametersResponse,
        )

        # Arrange: Create one parameter, leave others non-existent
        param1 = "/test/batch/exists"
        param2 = "/test/batch/nonexistent1"
        param3 = "/test/batch/nonexistent2"
        parameter_store.create_parameter(parameter=param1, value="value1")

        # Act: Try to delete mix of existing and non-existent parameters
        result = parameter_store.delete_parameters([param1, param2, param3])

        # Assert: Verify the response type
        assert isinstance(result, DeleteParametersResponse)

        # Assert: Verify the existing parameter was deleted
        assert param1 in result.DeletedParameters

        # Assert: Verify non-existent parameters are in InvalidParameters
        assert param2 in result.InvalidParameters
        assert param3 in result.InvalidParameters

        # Assert: Verify the existing parameter no longer exists
        assert parameter_store.get_parameter(param1) is None

    def test_delete_parameters_with_empty_list(self, parameter_store):
        """Test that delete_parameters raises error with empty list (AWS API requirement)."""
        # AWS API requires at least one parameter name
        # Act & Assert: Try to delete with empty list
        with pytest.raises(Exception):  # AWS will raise ParamValidationError
            parameter_store.delete_parameters([])

    def test_delete_parameters_with_single_parameter(self, parameter_store):
        """Test that delete_parameters works with a single parameter in the list."""
        from aws_environment_store_manager.ssm_parameter_store.models import (
            DeleteParametersResponse,
        )

        # Arrange: Create a parameter
        param1 = "/test/batch/single"
        parameter_store.create_parameter(parameter=param1, value="value1")

        # Act: Delete with single parameter in list
        result = parameter_store.delete_parameters([param1])

        # Assert: Verify the response
        assert isinstance(result, DeleteParametersResponse)
        assert len(result.DeletedParameters) == 1
        assert param1 in result.DeletedParameters
        assert len(result.InvalidParameters) == 0

        # Assert: Verify parameter was deleted
        assert parameter_store.get_parameter(param1) is None

    def test_delete_parameters_with_illegal_characters_raises_error(self, parameter_store):
        """Test that delete_parameters raises ValueError when list contains parameter with illegal characters."""
        # Act & Assert: Try to delete parameters with illegal characters
        with pytest.raises(ValueError) as exc_info:
            parameter_store.delete_parameters(["/test/valid", "/test/param@invalid"])

        # Assert: Verify the exception message mentions illegal characters
        assert "Illegal characters" in str(exc_info.value)

    def test_delete_parameters_with_clean_string_converts_relative_paths(self, parameter_store):
        """Test that delete_parameters with clean_string=True converts relative paths to absolute."""
        from aws_environment_store_manager.ssm_parameter_store.models import (
            DeleteParametersResponse,
        )

        # Arrange: Create parameters with absolute paths
        param1 = "/test/batch/relative1"
        param2 = "/test/batch/relative2"
        parameter_store.create_parameter(parameter=param1, value="value1")
        parameter_store.create_parameter(parameter=param2, value="value2")

        # Act: Delete using relative paths (clean_string will convert them)
        result = parameter_store.delete_parameters(
            ["test/batch/relative1", "test/batch/relative2"]
        )

        # Assert: Verify the response
        assert isinstance(result, DeleteParametersResponse)
        assert len(result.DeletedParameters) == 2
        assert param1 in result.DeletedParameters
        assert param2 in result.DeletedParameters

        # Assert: Verify parameters were deleted
        assert parameter_store.get_parameter(param1) is None
        assert parameter_store.get_parameter(param2) is None

    def test_create_and_verify_with_get_parameter_value(self, parameter_store):
        """Test create operation and verify using get_parameter_value method."""
        # Arrange: Define parameter details
        parameter_name = "/test/coverage/param_value"
        parameter_value = "test-value-for-coverage"

        # Act: Create the parameter
        parameter_store.create_parameter(parameter=parameter_name, value=parameter_value)

        # Assert: Verify using get_parameter_value (covers line 60)
        retrieved_value = parameter_store.get_parameter_value(parameter_name)
        assert retrieved_value == parameter_value

    def test_create_and_verify_with_get_parameters_by_path_as_dict(self, parameter_store):
        """Test create operation and verify using get_parameters_by_path_as_dict method."""
        # Arrange: Create multiple parameters under a path
        parameter_store.create_parameter(parameter="/test/coverage/dict/param1", value="value1")
        parameter_store.create_parameter(parameter="/test/coverage/dict/param2", value="value2")
        parameter_store.create_parameter(parameter="/test/coverage/dict/param3", value="value3")

        # Act: Retrieve parameters as dict (covers lines 94-95)
        result_dict = parameter_store.get_parameters_by_path_as_dict("/test/coverage/dict")

        # Assert: Verify the dict contains all parameters
        assert isinstance(result_dict, dict)
        assert len(result_dict) == 3
        assert result_dict["/test/coverage/dict/param1"] == "value1"
        assert result_dict["/test/coverage/dict/param2"] == "value2"
        assert result_dict["/test/coverage/dict/param3"] == "value3"
