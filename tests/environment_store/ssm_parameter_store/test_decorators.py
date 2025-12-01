import pytest
from aws_environment_store_manager.ssm_parameter_store.decorators import (
    clean_and_validate_string,
)


class TestCleanAndValidateStringDecorator:
    """Test suite for clean_and_validate_string decorator."""

    # Tests for decorator with standalone functions (no self parameter)
    def test_decorator_on_function_with_valid_parameter(self):
        """Test decorator on a standalone function with valid parameter."""

        @clean_and_validate_string
        def test_func(parameter: str) -> str:
            return f"processed: {parameter}"

        result = test_func("/valid/parameter")
        assert result == "processed: /valid/parameter"

    def test_decorator_on_function_with_path_parameter(self):
        """Test decorator on a standalone function with 'path' parameter."""

        @clean_and_validate_string
        def test_func(path: str) -> str:
            return f"processed: {path}"

        result = test_func("/valid/path")
        assert result == "processed: /valid/path"

    def test_decorator_on_function_validates_parameter(self):
        """Test that decorator validates the parameter on standalone functions."""

        @clean_and_validate_string
        def test_func(parameter: str) -> str:
            return parameter

        # Valid parameter should work
        result = test_func("/valid/path")
        assert result == "/valid/path"

        # Invalid parameter should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            test_func("relative/path")
        assert "Invalid pathlike string" in str(exc_info.value)

    def test_decorator_on_function_with_illegal_characters(self):
        """Test that decorator catches illegal characters in standalone functions."""

        @clean_and_validate_string
        def test_func(parameter: str) -> str:
            return parameter

        with pytest.raises(ValueError) as exc_info:
            test_func("/path with spaces")
        assert "Illegal characters:" in str(exc_info.value)

    def test_decorator_on_function_without_parameter_argument(self):
        """Test decorator on function without 'parameter' argument does nothing."""

        @clean_and_validate_string
        def test_func(other_arg: str) -> str:
            return f"result: {other_arg}"

        # Should work fine since there's no 'parameter' argument to validate
        result = test_func("any value")
        assert result == "result: any value"

    def test_decorator_on_function_with_multiple_arguments(self):
        """Test decorator on function with multiple arguments."""

        @clean_and_validate_string
        def test_func(parameter: str, value: str, count: int = 1) -> str:
            return f"{parameter}={value}*{count}"

        result = test_func("/valid/param", "test_value", 3)
        assert result == "/valid/param=test_value*3"

    def test_decorator_on_function_with_kwargs(self):
        """Test decorator on function called with keyword arguments."""

        @clean_and_validate_string
        def test_func(parameter: str, value: str) -> str:
            return f"{parameter}={value}"

        result = test_func(parameter="/valid/param", value="test")
        assert result == "/valid/param=test"

    def test_decorator_on_function_with_mixed_args_kwargs(self):
        """Test decorator with mixed positional and keyword arguments."""

        @clean_and_validate_string
        def test_func(parameter: str, value: str, optional: str = "default") -> str:
            return f"{parameter}={value}:{optional}"

        result = test_func("/valid/param", value="test", optional="custom")
        assert result == "/valid/param=test:custom"

    # Tests for decorator with class methods (with self parameter)
    def test_decorator_on_method_with_clean_string_true(self):
        """Test decorator on method with clean_string=True cleans the parameter."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Relative path should be cleaned to absolute
        result = obj.test_method("relative/path")
        assert result == "/relative/path"

    def test_decorator_on_method_with_clean_string_false(self):
        """Test decorator on method with clean_string=False does not clean."""

        class TestClass:
            def __init__(self):
                self.clean_string = False

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Relative path should not be cleaned, so validation should fail
        with pytest.raises(ValueError) as exc_info:
            obj.test_method("relative/path")
        assert "Invalid pathlike string" in str(exc_info.value)

    def test_decorator_on_method_without_clean_string_attribute(self):
        """Test decorator on method without clean_string attribute (defaults to False)."""

        class TestClass:
            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Without clean_string attribute, should default to False (no cleaning)
        with pytest.raises(ValueError) as exc_info:
            obj.test_method("relative/path")
        assert "Invalid pathlike string" in str(exc_info.value)

    def test_decorator_on_method_cleans_only_strings(self):
        """Test that decorator only cleans string parameters."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter) -> str:
                return str(parameter)

        obj = TestClass()
        # Non-string parameter should not be cleaned, but validation will fail
        with pytest.raises(AttributeError):
            # validate_string expects a string, will fail on non-string with AttributeError (int has no isspace())
            obj.test_method(123)

    def test_decorator_on_method_with_valid_absolute_path(self):
        """Test decorator on method with valid absolute path."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        result = obj.test_method("/valid/absolute/path")
        assert result == "/valid/absolute/path"

    def test_decorator_on_method_cleans_relative_to_absolute(self):
        """Test that decorator cleans relative paths to absolute when clean_string=True."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Test various relative paths
        # Single-part paths are now returned unchanged
        assert obj.test_method("path") == "path"
        # Multi-part relative paths are converted to absolute
        assert obj.test_method("path/to/param") == "/path/to/param"
        assert obj.test_method("a/b/c") == "/a/b/c"

    def test_decorator_on_method_normalizes_paths(self):
        """Test that decorator normalizes paths when cleaning."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Double slashes should be normalized
        assert obj.test_method("path//double//slash") == "/path/double/slash"
        # Trailing slashes are removed by Path, "path/" becomes "path" (single part)
        assert obj.test_method("path/") == "path"

    def test_decorator_on_method_with_multiple_parameters(self):
        """Test decorator on method with multiple parameters."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str, value: str, count: int = 1) -> dict:
                return {"param": parameter, "value": value, "count": count}

        obj = TestClass()
        result = obj.test_method("param_name", "param_value", 5)
        # Single-part path "param_name" is returned unchanged
        assert result == {"param": "param_name", "value": "param_value", "count": 5}

    def test_decorator_preserves_function_name(self):
        """Test that decorator preserves the original function name."""

        @clean_and_validate_string
        def my_function(parameter: str) -> str:
            return parameter

        assert my_function.__name__ == "my_function"

    def test_decorator_preserves_function_docstring(self):
        """Test that decorator preserves the original function docstring."""

        @clean_and_validate_string
        def my_function(parameter: str) -> str:
            """This is a test docstring."""
            return parameter

        assert my_function.__doc__ == "This is a test docstring."

    def test_decorator_with_default_parameter_value(self):
        """Test decorator with function that has default parameter value."""

        @clean_and_validate_string
        def test_func(parameter: str = "/default/path") -> str:
            return parameter

        # Call without argument, should use default
        result = test_func()
        assert result == "/default/path"

        # Call with argument
        result = test_func("/custom/path")
        assert result == "/custom/path"

    def test_decorator_on_method_with_default_parameter(self):
        """Test decorator on method with default parameter value."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str = "default") -> str:
                return parameter

        obj = TestClass()
        # Default value "default" is a single-part path, returned unchanged
        result = obj.test_method()
        assert result == "default"

    def test_decorator_validates_after_cleaning(self):
        """Test that validation happens after cleaning."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Relative path with illegal characters should be cleaned first,
        # then validation should catch the illegal characters
        with pytest.raises(ValueError) as exc_info:
            obj.test_method("path with spaces")
        assert "Illegal characters:" in str(exc_info.value)

    def test_decorator_returns_function_return_value(self):
        """Test that decorator passes through the function's return value."""

        @clean_and_validate_string
        def test_func(parameter: str) -> dict:
            return {"status": "success", "param": parameter}

        result = test_func("/valid/path")
        assert result == {"status": "success", "param": "/valid/path"}

    def test_decorator_with_none_return_value(self):
        """Test decorator with function that returns None."""

        @clean_and_validate_string
        def test_func(parameter: str) -> None:
            pass

        result = test_func("/valid/path")
        assert result is None

    def test_decorator_on_method_with_additional_attributes(self):
        """Test decorator on method where class has additional attributes."""

        class TestClass:
            def __init__(self):
                self.clean_string = True
                self.other_attr = "value"
                self.count = 42

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return f"{parameter}:{self.other_attr}:{self.count}"

        obj = TestClass()
        result = obj.test_method("param")
        # Single-part path "param" is returned unchanged
        assert result == "param:value:42"

    def test_decorator_with_empty_string_parameter(self):
        """Test decorator with empty string parameter."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Empty string now raises ValueError during cleaning
        with pytest.raises(ValueError) as exc_info:
            obj.test_method("")
        assert "String cannot be empty" in str(exc_info.value)

    def test_decorator_with_special_characters_in_parameter(self):
        """Test decorator catches special characters in parameter."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Special characters should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            obj.test_method("path@with#special")
        assert "Illegal characters:" in str(exc_info.value)

    def test_decorator_on_method_with_clean_string_zero(self):
        """Test decorator treats clean_string=0 as False."""

        class TestClass:
            def __init__(self):
                self.clean_string = 0  # Falsy value

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Should not clean, so relative path fails validation
        with pytest.raises(ValueError) as exc_info:
            obj.test_method("relative/path")
        assert "Invalid pathlike string" in str(exc_info.value)

    def test_decorator_on_method_with_clean_string_one(self):
        """Test decorator treats clean_string=1 as True."""

        class TestClass:
            def __init__(self):
                self.clean_string = 1  # Truthy value

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Should clean the relative path
        result = obj.test_method("relative/path")
        assert result == "/relative/path"

    def test_decorator_on_method_with_clean_string_string_value(self):
        """Test decorator with clean_string as non-empty string (truthy)."""

        class TestClass:
            def __init__(self):
                self.clean_string = "yes"  # Truthy string

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Should clean the relative path
        result = obj.test_method("relative/path")
        assert result == "/relative/path"

    def test_decorator_on_method_with_clean_string_empty_string(self):
        """Test decorator with clean_string as empty string (falsy)."""

        class TestClass:
            def __init__(self):
                self.clean_string = ""  # Falsy string

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Should not clean, so relative path fails validation
        with pytest.raises(ValueError) as exc_info:
            obj.test_method("relative/path")
        assert "Invalid pathlike string" in str(exc_info.value)

    def test_decorator_on_method_with_clean_string_none(self):
        """Test decorator with clean_string=None (falsy)."""

        class TestClass:
            def __init__(self):
                self.clean_string = None  # Falsy value

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Should not clean, so relative path fails validation
        with pytest.raises(ValueError) as exc_info:
            obj.test_method("relative/path")
        assert "Invalid pathlike string" in str(exc_info.value)

    def test_decorator_with_already_absolute_path_no_cleaning_needed(self):
        """Test decorator with already absolute path when clean_string=True."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Already absolute path should remain unchanged
        result = obj.test_method("/already/absolute/path")
        assert result == "/already/absolute/path"

    def test_decorator_on_function_with_parameter_as_kwarg_only(self):
        """Test decorator on function with parameter as keyword-only argument."""

        @clean_and_validate_string
        def test_func(*, parameter: str) -> str:
            return parameter

        result = test_func(parameter="/valid/path")
        assert result == "/valid/path"

    def test_decorator_on_method_without_parameter_arg(self):
        """Test decorator on method without 'parameter' argument."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, other_arg: str) -> str:
                return other_arg

        obj = TestClass()
        # Should work fine, no validation happens
        result = obj.test_method("any value")
        assert result == "any value"

    def test_decorator_with_complex_return_type(self):
        """Test decorator with function returning complex types."""

        @clean_and_validate_string
        def test_func(parameter: str) -> list:
            return [parameter, parameter.upper(), len(parameter)]

        result = test_func("/valid/path")
        assert result == ["/valid/path", "/VALID/PATH", 11]

    def test_decorator_on_method_with_args_and_kwargs(self):
        """Test decorator on method with *args and **kwargs."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str, *args, **kwargs) -> dict:
                return {"parameter": parameter, "args": args, "kwargs": kwargs}

        obj = TestClass()
        result = obj.test_method("param", "extra1", "extra2", key1="value1", key2="value2")
        # Single-part path "param" is returned unchanged
        assert result["parameter"] == "param"
        assert result["args"] == ("extra1", "extra2")
        assert result["kwargs"] == {"key1": "value1", "key2": "value2"}

    def test_decorator_validates_cleaned_parameter(self):
        """Test that validation is performed on the cleaned parameter value."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # After cleaning "path/", Path normalizes it to "path" (single part), returned unchanged
        result = obj.test_method("path/")
        assert result == "path"

    def test_decorator_with_unicode_in_parameter(self):
        """Test decorator with unicode characters in parameter."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Unicode alphanumeric characters are allowed
        result = obj.test_method("path/café")
        assert result == "/path/café"

    def test_decorator_with_unicode_emoji_in_parameter(self):
        """Test decorator with unicode emoji in parameter (should fail)."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameter: str) -> str:
                return parameter

        obj = TestClass()
        # Unicode emoji should fail validation
        with pytest.raises(ValueError) as exc_info:
            obj.test_method("path/🚀")
        assert "Illegal characters:" in str(exc_info.value)

    def test_decorator_on_staticmethod(self):
        """Test decorator on static method (no self parameter)."""

        class TestClass:
            @staticmethod
            @clean_and_validate_string
            def test_method(parameter: str) -> str:
                return parameter

        # Static method has no self, so no cleaning happens
        with pytest.raises(ValueError) as exc_info:
            TestClass.test_method("relative/path")
        assert "Invalid pathlike string" in str(exc_info.value)

        # Valid absolute path should work
        result = TestClass.test_method("/valid/path")
        assert result == "/valid/path"

    def test_decorator_on_classmethod(self):
        """Test decorator on class method (cls parameter instead of self)."""

        class TestClass:
            clean_string = True

            @classmethod
            @clean_and_validate_string
            def test_method(cls, parameter: str) -> str:
                return parameter

        # Class method has 'cls' not 'self', so no cleaning happens
        with pytest.raises(ValueError) as exc_info:
            TestClass.test_method("relative/path")
        assert "Invalid pathlike string" in str(exc_info.value)

        # Valid absolute path should work
        result = TestClass.test_method("/valid/path")
        assert result == "/valid/path"


class TestCleanAndValidateStringDecoratorWithLists:
    """Test suite for clean_and_validate_string decorator with list parameters."""

    def test_decorator_cleans_list_of_parameters_with_clean_string_true(self):
        """Test that decorator cleans list of parameters when clean_string=True."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Test list with relative paths
        result = obj.test_method(["path/to/param1", "path/to/param2", "path/to/param3"])
        assert result == ["/path/to/param1", "/path/to/param2", "/path/to/param3"]

    def test_decorator_validates_list_of_parameters(self):
        """Test that decorator validates each parameter in the list."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Test list with invalid characters
        with pytest.raises(ValueError) as exc_info:
            obj.test_method(["/valid/path", "/invalid@path"])
        assert "Illegal characters:" in str(exc_info.value)

    def test_decorator_with_empty_list(self):
        """Test that decorator handles empty list correctly."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Empty list should work fine
        result = obj.test_method([])
        assert result == []

    def test_decorator_with_single_item_list(self):
        """Test that decorator handles single-item list correctly."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Single item list
        result = obj.test_method(["path/to/param"])
        assert result == ["/path/to/param"]

    def test_decorator_with_list_of_absolute_paths(self):
        """Test that decorator handles list of already absolute paths."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # List of absolute paths should remain unchanged
        result = obj.test_method(["/path/to/param1", "/path/to/param2"])
        assert result == ["/path/to/param1", "/path/to/param2"]

    def test_decorator_with_list_of_single_part_paths(self):
        """Test that decorator handles list of single-part paths (no slashes)."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Single-part paths should remain unchanged
        result = obj.test_method(["param1", "param2", "param3"])
        assert result == ["param1", "param2", "param3"]

    def test_decorator_with_list_mixed_path_types(self):
        """Test that decorator handles list with mixed path types."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Mix of absolute, relative, and single-part paths
        result = obj.test_method(["/absolute/path", "relative/path", "single"])
        assert result == ["/absolute/path", "/relative/path", "single"]

    def test_decorator_with_list_clean_string_false(self):
        """Test that decorator does not clean list when clean_string=False."""

        class TestClass:
            def __init__(self):
                self.clean_string = False

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Should not clean, so relative paths fail validation
        with pytest.raises(ValueError) as exc_info:
            obj.test_method(["relative/path"])
        assert "Invalid pathlike string" in str(exc_info.value)

    def test_decorator_with_list_containing_empty_string(self):
        """Test that decorator raises error for list containing empty string."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Empty string in list should raise error
        with pytest.raises(ValueError) as exc_info:
            obj.test_method(["/valid/path", ""])
        assert "String cannot be empty" in str(exc_info.value)

    def test_decorator_with_list_containing_whitespace_only(self):
        """Test that decorator raises error for list containing whitespace-only string."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Whitespace-only string in list should raise error
        with pytest.raises(ValueError) as exc_info:
            obj.test_method(["/valid/path", "   "])
        assert "String cannot be empty" in str(exc_info.value)

    def test_decorator_with_list_all_invalid_characters(self):
        """Test that decorator raises error when all items in list have invalid characters."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # All items with invalid characters
        with pytest.raises(ValueError) as exc_info:
            obj.test_method(["/invalid@path1", "/invalid#path2"])
        assert "Illegal characters:" in str(exc_info.value)

    def test_decorator_with_list_first_item_invalid(self):
        """Test that decorator catches invalid first item in list."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # First item invalid
        with pytest.raises(ValueError) as exc_info:
            obj.test_method(["/invalid@path", "/valid/path"])
        assert "Illegal characters:" in str(exc_info.value)

    def test_decorator_with_list_last_item_invalid(self):
        """Test that decorator catches invalid last item in list."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Last item invalid
        with pytest.raises(ValueError) as exc_info:
            obj.test_method(["/valid/path", "/invalid@path"])
        assert "Illegal characters:" in str(exc_info.value)

    def test_decorator_with_list_middle_item_invalid(self):
        """Test that decorator catches invalid middle item in list."""

        class TestClass:
            def __init__(self):
                self.clean_string = True

            @clean_and_validate_string
            def test_method(self, parameters: list[str]) -> list[str]:
                return parameters

        obj = TestClass()
        # Middle item invalid
        with pytest.raises(ValueError) as exc_info:
            obj.test_method(["/valid/path1", "/invalid@path", "/valid/path2"])
        assert "Illegal characters:" in str(exc_info.value)
