import pytest
from environment_store.environment_store_manager.decorators import validate_hierarchy


class TestValidateHierarchyDecorator:
    """Test suite for validate_hierarchy decorator."""

    # Valid hierarchy tests
    def test_all_levels_provided(self):
        """Test with all hierarchy levels provided."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        result = test_func(organisation="org", project="proj", environment="env", service="svc")
        assert result == "success"

    def test_organisation_project_environment_only(self):
        """Test with organisation, project, and environment (no service)."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        result = test_func(organisation="org", project="proj", environment="env")
        assert result == "success"

    def test_organisation_project_only(self):
        """Test with organisation and project only."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        result = test_func(organisation="org", project="proj")
        assert result == "success"

    def test_organisation_only(self):
        """Test with organisation only."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        result = test_func(organisation="org")
        assert result == "success"

    def test_no_levels_provided(self):
        """Test with no hierarchy levels provided."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        result = test_func()
        assert result == "success"

    # Invalid hierarchy tests - skipping levels
    def test_service_without_environment_raises_error(self):
        """Test that service without environment raises ValueError."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        with pytest.raises(ValueError) as exc_info:
            test_func(organisation="org", project="proj", service="svc")
        assert "service requires environment to be specified" in str(exc_info.value)

    def test_environment_without_project_raises_error(self):
        """Test that environment without project raises ValueError."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        with pytest.raises(ValueError) as exc_info:
            test_func(organisation="org", environment="env")
        assert "environment requires project to be specified" in str(exc_info.value)

    def test_project_without_organisation_raises_error(self):
        """Test that project without organisation raises ValueError."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        with pytest.raises(ValueError) as exc_info:
            test_func(project="proj")
        assert "project requires organisation to be specified" in str(exc_info.value)

    def test_service_without_project_raises_error(self):
        """Test that service without project raises ValueError."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        with pytest.raises(ValueError) as exc_info:
            test_func(organisation="org", service="svc")
        assert "service requires environment to be specified" in str(exc_info.value)

    def test_environment_and_service_without_project_raises_error(self):
        """Test that environment and service without project raises ValueError."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        with pytest.raises(ValueError) as exc_info:
            test_func(organisation="org", environment="env", service="svc")
        assert "environment requires project to be specified" in str(exc_info.value)

    # Type validation tests
    def test_organisation_must_be_string(self):
        """Test that organisation must be a string."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        with pytest.raises(ValueError) as exc_info:
            test_func(organisation=123)
        assert "organisation must be a string, got int" in str(exc_info.value)

    def test_project_must_be_string(self):
        """Test that project must be a string."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        with pytest.raises(ValueError) as exc_info:
            test_func(organisation="org", project=456)
        assert "project must be a string, got int" in str(exc_info.value)

    def test_environment_must_be_string(self):
        """Test that environment must be a string."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        with pytest.raises(ValueError) as exc_info:
            test_func(organisation="org", project="proj", environment=["env"])
        assert "environment must be a string, got list" in str(exc_info.value)

    def test_service_must_be_string(self):
        """Test that service must be a string."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        with pytest.raises(ValueError) as exc_info:
            test_func(
                organisation="org", project="proj", environment="env", service={"key": "val"}
            )
        assert "service must be a string, got dict" in str(exc_info.value)

    def test_type_validation_before_hierarchy_validation(self):
        """Test that type validation happens before hierarchy validation."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return "success"

        # Even though hierarchy is invalid (service without environment),
        # type error should be raised first
        with pytest.raises(ValueError) as exc_info:
            test_func(organisation=123, service="svc")
        assert "organisation must be a string, got int" in str(exc_info.value)

    # Decorator behavior tests
    def test_decorator_preserves_function_name(self):
        """Test that decorator preserves the original function name."""

        @validate_hierarchy
        def my_function(organisation=None, project=None, environment=None, service=None):
            return "success"

        assert my_function.__name__ == "my_function"

    def test_decorator_preserves_function_docstring(self):
        """Test that decorator preserves the original function docstring."""

        @validate_hierarchy
        def my_function(organisation=None, project=None, environment=None, service=None):
            """This is a test docstring."""
            return "success"

        assert my_function.__doc__ == "This is a test docstring."

    def test_decorator_passes_through_return_value(self):
        """Test that decorator passes through the function's return value."""

        @validate_hierarchy
        def test_func(organisation=None, project=None, environment=None, service=None):
            return {"org": organisation, "proj": project}

        result = test_func(organisation="org", project="proj")
        assert result == {"org": "org", "proj": "proj"}

    def test_decorator_with_additional_kwargs(self):
        """Test that decorator works with additional keyword arguments."""

        @validate_hierarchy
        def test_func(
            organisation=None, project=None, environment=None, service=None, extra=None
        ):
            return f"{organisation}-{extra}"

        result = test_func(organisation="org", extra="value")
        assert result == "org-value"

    def test_decorator_with_positional_args(self):
        """Test that decorator works when function receives positional args."""

        @validate_hierarchy
        def test_func(*args, organisation=None, project=None, environment=None, service=None):
            return f"args={args}, org={organisation}"

        result = test_func("pos1", "pos2", organisation="org")
        assert result == "args=('pos1', 'pos2'), org=org"
