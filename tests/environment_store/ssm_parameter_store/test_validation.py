import pytest
from aws_environment_store_manager.ssm_parameter_store.validation import (
    make_string_parameter_store_compatible,
    validate_string,
)


class TestMakeStringPathlike:
    """Test suite for make_string_pathlike function."""

    def test_absolute_path_unchanged(self):
        """Test that absolute paths remain unchanged."""
        # Absolute paths starting with / should remain as-is
        assert make_string_parameter_store_compatible("/absolute/path") == "/absolute/path"
        assert make_string_parameter_store_compatible("/") == "/"
        assert make_string_parameter_store_compatible("/single") == "/single"

    def test_relative_path_becomes_absolute(self):
        """Test that multi-part relative paths are converted to absolute paths."""
        # Multi-part relative paths should get a leading /
        assert make_string_parameter_store_compatible("relative/path") == "/relative/path"
        assert make_string_parameter_store_compatible("a/b/c") == "/a/b/c"

    def test_single_part_path_unchanged(self):
        """Test that single-part paths (no slashes) are returned unchanged."""
        # Single-part paths should not get a leading /
        assert make_string_parameter_store_compatible("single") == "single"
        assert make_string_parameter_store_compatible("parameter") == "parameter"
        assert make_string_parameter_store_compatible("test123") == "test123"

    def test_path_with_dots(self):
        """Test paths containing dots are handled correctly."""
        # Dots in paths should be preserved
        assert make_string_parameter_store_compatible("/path/with.dots") == "/path/with.dots"
        assert make_string_parameter_store_compatible("path/with.dots") == "/path/with.dots"
        assert make_string_parameter_store_compatible("/path/.hidden") == "/path/.hidden"

    def test_path_with_underscores(self):
        """Test paths containing underscores are handled correctly."""
        assert (
            make_string_parameter_store_compatible("/path/with_underscores")
            == "/path/with_underscores"
        )
        assert (
            make_string_parameter_store_compatible("path/with_underscores")
            == "/path/with_underscores"
        )

    def test_path_with_hyphens(self):
        """Test paths containing hyphens are handled correctly."""
        assert (
            make_string_parameter_store_compatible("/path/with-hyphens") == "/path/with-hyphens"
        )
        assert (
            make_string_parameter_store_compatible("path/with-hyphens") == "/path/with-hyphens"
        )

    def test_path_with_numbers(self):
        """Test paths containing numbers are handled correctly."""
        assert make_string_parameter_store_compatible("/path123/456") == "/path123/456"
        assert make_string_parameter_store_compatible("path123/456") == "/path123/456"

    def test_path_with_mixed_characters(self):
        """Test paths with mixed valid characters."""
        assert (
            make_string_parameter_store_compatible("/path_123/test-456.txt")
            == "/path_123/test-456.txt"
        )
        assert (
            make_string_parameter_store_compatible("path_123/test-456.txt")
            == "/path_123/test-456.txt"
        )

    def test_empty_string_raises_error(self):
        """Test empty string raises ValueError."""
        # Empty strings are not allowed
        with pytest.raises(ValueError) as exc_info:
            make_string_parameter_store_compatible("")
        assert "String cannot be empty" in str(exc_info.value)

    def test_path_normalization(self):
        """Test that Path normalization occurs (e.g., removing redundant slashes)."""
        # Path class normalizes multiple slashes
        assert (
            make_string_parameter_store_compatible("/path//double//slash")
            == "/path/double/slash"
        )
        assert (
            make_string_parameter_store_compatible("path//double//slash")
            == "/path/double/slash"
        )

    def test_path_with_trailing_slash(self):
        """Test paths with trailing slashes."""
        # Path class removes trailing slashes
        assert make_string_parameter_store_compatible("/path/") == "/path"
        # Path normalizes "path/" to "path" (single part), returned unchanged
        assert make_string_parameter_store_compatible("path/") == "path"

    def test_single_character_paths(self):
        """Test single character paths."""
        # Absolute single character paths remain unchanged
        assert make_string_parameter_store_compatible("/a") == "/a"
        assert make_string_parameter_store_compatible("/1") == "/1"
        # Single character paths without slash are returned as-is (single part)
        assert make_string_parameter_store_compatible("a") == "a"
        assert make_string_parameter_store_compatible("1") == "1"

    def test_path_with_special_aws_characters(self):
        """Test paths with characters allowed in AWS Parameter Store."""
        # AWS allows: a-zA-Z0-9_.-/
        assert (
            make_string_parameter_store_compatible("/aws/param_store-test.123")
            == "/aws/param_store-test.123"
        )
        assert (
            make_string_parameter_store_compatible("aws/param_store-test.123")
            == "/aws/param_store-test.123"
        )


class TestValidateString:
    """Test suite for validate_string function."""

    # Tests for valid strings (should return True)
    def test_valid_absolute_path_with_alphanumeric(self):
        """Test valid absolute path with alphanumeric characters."""
        assert validate_string("/path/to/parameter") is True
        assert validate_string("/abc123/def456") is True

    def test_valid_path_with_underscores(self):
        """Test valid path with underscores."""
        assert validate_string("/path_with_underscores") is True
        assert validate_string("/my_param_store_key") is True

    def test_valid_path_with_hyphens(self):
        """Test valid path with hyphens."""
        assert validate_string("/path-with-hyphens") is True
        assert validate_string("/my-param-store-key") is True

    def test_valid_path_with_dots(self):
        """Test valid path with dots."""
        assert validate_string("/path.with.dots") is True
        assert validate_string("/config.production.db") is True

    def test_valid_path_with_all_allowed_characters(self):
        """Test valid path with all allowed special characters."""
        assert validate_string("/path_with-all.allowed/characters123") is True
        assert validate_string("/AWS_Param-Store.Test/123") is True

    def test_valid_single_level_path(self):
        """Test valid single level path."""
        assert validate_string("/parameter") is True
        assert validate_string("/a") is True

    def test_valid_deep_nested_path(self):
        """Test valid deeply nested path."""
        assert validate_string("/level1/level2/level3/level4/parameter") is True

    def test_valid_path_with_numbers_only(self):
        """Test valid path with numbers."""
        assert validate_string("/123/456/789") is True

    # Tests for invalid pathlike strings (not absolute)
    def test_invalid_relative_path_raises_error(self):
        """Test that relative paths raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("relative/path")

        assert "Invalid pathlike string" in str(exc_info.value)
        assert "Original: relative/path" in str(exc_info.value)
        assert "Valid: /relative/path" in str(exc_info.value)

    def test_invalid_relative_path_returns_false(self):
        """Test that relative paths return False when raises=False."""
        assert validate_string("relative/path", raises=False) is False
        assert validate_string("no/leading/slash", raises=False) is False

    def test_valid_single_word(self):
        """Test that single word (no slashes) is now valid."""
        # Single-part paths are returned unchanged and are valid
        assert validate_string("parameter") is True
        assert validate_string("test123") is True
        assert validate_string("my_param") is True

    # Tests for illegal characters
    def test_invalid_space_character_raises_error(self):
        """Test that spaces raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path with spaces")

        assert "Illegal characters:" in str(exc_info.value)
        assert "/path with spaces" in str(exc_info.value)
        # Each space is marked with ^ individually
        assert "^" in str(exc_info.value)  # Markers for spaces
        assert "Allowed characters:" in str(exc_info.value)

    def test_invalid_space_character_returns_false(self):
        """Test that spaces return False when raises=False."""
        assert validate_string("/path with spaces", raises=False) is False

    def test_invalid_special_characters_raises_error(self):
        """Test that special characters raise ValueError when raises=True."""
        # Test various special characters
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path@with#special")
        assert "Illegal characters:" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            validate_string("/path$with%special")
        assert "Illegal characters:" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            validate_string("/path&with*special")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_special_characters_returns_false(self):
        """Test that special characters return False when raises=False."""
        assert validate_string("/path@with#special", raises=False) is False
        assert validate_string("/path$with%special", raises=False) is False
        assert validate_string("/path&with*special", raises=False) is False
        assert validate_string("/path!with?special", raises=False) is False

    def test_invalid_parentheses_raises_error(self):
        """Test that parentheses raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path(with)parentheses")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_parentheses_returns_false(self):
        """Test that parentheses return False when raises=False."""
        assert validate_string("/path(with)parentheses", raises=False) is False

    def test_invalid_brackets_raises_error(self):
        """Test that brackets raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path[with]brackets")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_brackets_returns_false(self):
        """Test that brackets return False when raises=False."""
        assert validate_string("/path[with]brackets", raises=False) is False
        assert validate_string("/path{with}braces", raises=False) is False

    def test_invalid_quotes_raises_error(self):
        """Test that quotes raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path'with'quotes")
        assert "Illegal characters:" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            validate_string('/path"with"quotes')
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_quotes_returns_false(self):
        """Test that quotes return False when raises=False."""
        assert validate_string("/path'with'quotes", raises=False) is False
        assert validate_string('/path"with"quotes', raises=False) is False

    def test_invalid_backslash_raises_error(self):
        """Test that backslashes raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path\\with\\backslash")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_backslash_returns_false(self):
        """Test that backslashes return False when raises=False."""
        assert validate_string("/path\\with\\backslash", raises=False) is False

    def test_invalid_pipe_raises_error(self):
        """Test that pipe characters raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path|with|pipe")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_pipe_returns_false(self):
        """Test that pipe characters return False when raises=False."""
        assert validate_string("/path|with|pipe", raises=False) is False

    def test_invalid_semicolon_raises_error(self):
        """Test that semicolons raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path;with;semicolon")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_semicolon_returns_false(self):
        """Test that semicolons return False when raises=False."""
        assert validate_string("/path;with;semicolon", raises=False) is False

    def test_invalid_colon_raises_error(self):
        """Test that colons raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path:with:colon")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_colon_returns_false(self):
        """Test that colons return False when raises=False."""
        assert validate_string("/path:with:colon", raises=False) is False

    def test_invalid_comma_raises_error(self):
        """Test that commas raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path,with,comma")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_comma_returns_false(self):
        """Test that commas return False when raises=False."""
        assert validate_string("/path,with,comma", raises=False) is False

    def test_invalid_less_than_greater_than_raises_error(self):
        """Test that < and > raise ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path<with>symbols")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_less_than_greater_than_returns_false(self):
        """Test that < and > return False when raises=False."""
        assert validate_string("/path<with>symbols", raises=False) is False

    def test_invalid_equals_raises_error(self):
        """Test that equals sign raises ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path=with=equals")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_equals_returns_false(self):
        """Test that equals sign returns False when raises=False."""
        assert validate_string("/path=with=equals", raises=False) is False

    def test_invalid_plus_raises_error(self):
        """Test that plus sign raises ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path+with+plus")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_plus_returns_false(self):
        """Test that plus sign returns False when raises=False."""
        assert validate_string("/path+with+plus", raises=False) is False

    def test_invalid_tilde_raises_error(self):
        """Test that tilde raises ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path~with~tilde")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_tilde_returns_false(self):
        """Test that tilde returns False when raises=False."""
        assert validate_string("/path~with~tilde", raises=False) is False

    def test_invalid_backtick_raises_error(self):
        """Test that backtick raises ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path`with`backtick")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_backtick_returns_false(self):
        """Test that backtick returns False when raises=False."""
        assert validate_string("/path`with`backtick", raises=False) is False

    def test_invalid_exclamation_raises_error(self):
        """Test that exclamation mark raises ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path!with!exclamation")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_exclamation_returns_false(self):
        """Test that exclamation mark returns False when raises=False."""
        assert validate_string("/path!with!exclamation", raises=False) is False

    def test_invalid_question_mark_raises_error(self):
        """Test that question mark raises ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path?with?question")
        assert "Illegal characters:" in str(exc_info.value)

    def test_invalid_question_mark_returns_false(self):
        """Test that question mark returns False when raises=False."""
        assert validate_string("/path?with?question", raises=False) is False

    # Edge cases and boundary conditions
    def test_root_path_only(self):
        """Test that root path '/' is valid."""
        assert validate_string("/") is True

    def test_multiple_consecutive_slashes_not_valid(self):
        """Test that multiple consecutive slashes are not valid (not normalized before validation)."""
        # The validation checks the original string, not the normalized version
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path//double//slash")
        assert "Invalid pathlike string" in str(exc_info.value)
        assert "Valid: /path/double/slash" in str(exc_info.value)

    def test_multiple_consecutive_slashes_returns_false(self):
        """Test that multiple consecutive slashes return False when raises=False."""
        assert validate_string("/path//double//slash", raises=False) is False

    def test_path_with_trailing_slash_not_valid(self):
        """Test that trailing slashes are not valid (not normalized before validation)."""
        # The validation checks the original string, not the normalized version
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path/")
        assert "Invalid pathlike string" in str(exc_info.value)
        assert "Valid: /path" in str(exc_info.value)

    def test_path_with_trailing_slash_returns_false(self):
        """Test that trailing slashes return False when raises=False."""
        assert validate_string("/path/", raises=False) is False

    def test_very_long_valid_path(self):
        """Test very long but valid path."""
        long_path = "/" + "/".join([f"level{i}" for i in range(100)])
        assert validate_string(long_path) is True

    def test_path_with_uppercase_letters(self):
        """Test path with uppercase letters (should be valid)."""
        assert validate_string("/PATH/WITH/UPPERCASE") is True
        assert validate_string("/MixedCase/Path") is True

    def test_path_with_mixed_case_and_numbers(self):
        """Test path with mixed case and numbers."""
        assert validate_string("/Path123/Test456/ABC") is True

    def test_single_character_at_each_level(self):
        """Test path with single characters at each level."""
        assert validate_string("/a/b/c/d/e") is True

    def test_path_starting_with_number(self):
        """Test path starting with number."""
        assert validate_string("/123/path") is True
        assert validate_string("/1") is True

    def test_path_with_only_allowed_special_chars(self):
        """Test path with only allowed special_chars."""
        assert validate_string("/_") is True
        assert validate_string("/-") is True
        # "/." gets normalized to "/" by Path, so it's different from original and invalid
        with pytest.raises(ValueError) as exc_info:
            validate_string("/.")
        assert "Invalid pathlike string" in str(exc_info.value)
        assert validate_string("/_-./test") is True

    def test_error_message_format_for_illegal_chars(self):
        """Test that error message correctly marks illegal characters."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/test@param")

        error_msg = str(exc_info.value)
        assert "/test@param" in error_msg
        # The @ should be marked with ^
        assert "^" in error_msg
        # Check that allowed characters are listed
        assert "/" in error_msg or "Allowed characters:" in error_msg

    def test_error_message_marks_multiple_illegal_chars(self):
        """Test that error message marks multiple illegal characters correctly."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/test@param#value")

        error_msg = str(exc_info.value)
        # Both @ and # should be marked
        lines = error_msg.split("\n")
        # Find the line with the original string and the marker line
        assert any("@" in line and "#" in line for line in lines)

    def test_empty_string_raises_error(self):
        """Test empty string raises ValueError when raises=True."""
        # Empty strings are not allowed
        with pytest.raises(ValueError) as exc_info:
            validate_string("")
        assert "String cannot be empty" in str(exc_info.value)

    def test_empty_string_returns_false_no_raise(self):
        """Test empty string returns False when raises=False."""
        assert validate_string("", raises=False) is False

    def test_none_string_raises_error(self):
        """Test None string raises ValueError when raises=True."""
        # None is treated as falsy and not allowed
        with pytest.raises(ValueError) as exc_info:
            validate_string(None)
        assert "String cannot be empty" in str(exc_info.value)

    def test_none_string_returns_false_no_raise(self):
        """Test None string returns False when raises=False."""
        assert validate_string(None, raises=False) is False

    def test_whitespace_only_string_raises_error(self):
        """Test string with only whitespace raises error."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("   ")
        # Whitespace-only strings are caught by the empty string check
        assert "String cannot be empty" in str(exc_info.value)

    def test_whitespace_only_string_returns_false(self):
        """Test string with only whitespace returns False when raises=False."""
        assert validate_string("   ", raises=False) is False

    def test_tab_character_raises_error(self):
        """Test that tab character raises ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path\twith\ttab")
        assert "Illegal characters:" in str(exc_info.value)

    def test_tab_character_returns_false(self):
        """Test that tab character returns False when raises=False."""
        assert validate_string("/path\twith\ttab", raises=False) is False

    def test_newline_character_raises_error(self):
        """Test that newline character raises ValueError when raises=True."""
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path\nwith\nnewline")
        assert "Illegal characters:" in str(exc_info.value)

    def test_newline_character_returns_false(self):
        """Test that newline character returns False when raises=False."""
        assert validate_string("/path\nwith\nnewline", raises=False) is False

    def test_unicode_alphanumeric_characters_allowed(self):
        """Test that unicode alphanumeric characters are allowed by isalnum()."""
        # Python's isalnum() returns True for unicode letters like é, ñ, etc.
        # These are considered valid by the validation function
        assert validate_string("/path/with/émojis") is True
        assert validate_string("/path/with/café") is True
        # Chinese characters are also alphanumeric
        assert validate_string("/path/with/中文") is True

    def test_unicode_emoji_characters_raise_error(self):
        """Test that unicode emoji characters raise ValueError when raises=True."""
        # Emojis are not alphanumeric, so they should fail
        with pytest.raises(ValueError) as exc_info:
            validate_string("/path/with/🚀")
        assert "Illegal characters:" in str(exc_info.value)

    def test_unicode_emoji_characters_return_false(self):
        """Test that unicode emoji characters return False when raises=False."""
        assert validate_string("/path/with/🚀", raises=False) is False
        assert validate_string("/path/with/😀", raises=False) is False

    def test_raises_parameter_default_is_true(self):
        """Test that raises parameter defaults to True."""
        # When raises is not specified, it should default to True and raise
        with pytest.raises(ValueError):
            validate_string("relative/path")  # No raises parameter

    def test_combination_invalid_pathlike_and_illegal_chars(self):
        """Test string that is both non-pathlike and has illegal characters."""
        # Multi-part relative path with illegal characters
        # Should fail on pathlike check first
        with pytest.raises(ValueError) as exc_info:
            validate_string("relative/path@test")
        assert "Invalid pathlike string" in str(exc_info.value)

        # Single-part path with illegal characters
        # Now fails on illegal characters check (since single parts are returned unchanged)
        with pytest.raises(ValueError) as exc_info:
            validate_string("relative@path")
        assert "Illegal characters" in str(exc_info.value)

    def test_combination_invalid_pathlike_and_illegal_chars_no_raise(self):
        """Test string with both issues returns False when raises=False."""
        assert validate_string("relative/path@test", raises=False) is False
        assert validate_string("relative@path", raises=False) is False

    def test_path_with_dots_in_middle(self):
        """Test path with dots in the middle of segments."""
        assert validate_string("/path/to/file.name.ext") is True
        assert validate_string("/config.prod.db.backup") is True

    def test_path_with_consecutive_dots(self):
        """Test path with consecutive dots."""
        assert validate_string("/path/to/file..name") is True
        assert validate_string("/path.../test") is True

    def test_path_with_consecutive_underscores(self):
        """Test path with consecutive underscores."""
        assert validate_string("/path__with__underscores") is True

    def test_path_with_consecutive_hyphens(self):
        """Test path with consecutive hyphens."""
        assert validate_string("/path--with--hyphens") is True

    def test_all_alphanumeric_lowercase(self):
        """Test path with all lowercase alphanumeric."""
        assert validate_string("/abcdefghijklmnopqrstuvwxyz0123456789") is True

    def test_all_alphanumeric_uppercase(self):
        """Test path with all uppercase alphanumeric."""
        assert validate_string("/ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") is True

    def test_path_ending_with_allowed_special_char(self):
        """Test path ending with allowed special characters."""
        assert validate_string("/path/to/param_") is True
        assert validate_string("/path/to/param-") is True
        assert validate_string("/path/to/param.") is True

    def test_path_starting_with_allowed_special_char_after_slash(self):
        """Test path segments starting with allowed special characters."""
        assert validate_string("/_underscore") is True
        assert validate_string("/-hyphen") is True
        assert validate_string("/.dot") is True
