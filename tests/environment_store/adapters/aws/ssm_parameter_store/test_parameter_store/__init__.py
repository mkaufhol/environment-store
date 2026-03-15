"""
Test suite for ParameterStore class.

This module demonstrates best practices for testing AWS wrapper classes using moto
to mock AWS Systems Manager Parameter Store operations.

The test suite is organized into separate modules:
- test_initialization.py: Tests for ParameterStore initialization
- test_read_operations.py: Tests for read operations (get_parameter, get_parameters_by_path, etc.)
- test_write_operations.py: Tests for write operations (create_parameter, update_parameter, etc.)

Shared fixtures are defined in conftest.py and are automatically available to all test modules.
"""
