import functools


def validate_hierarchy(func):
    """
    Decorator to validate the hierarchy of environment variables.

    The hierarchy is: organisation > project > environment > service > variable
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        organisation = kwargs.get("organisation")
        project = kwargs.get("project")
        environment = kwargs.get("environment")
        service = kwargs.get("service")

        # Validate types - each provided value must be a string
        for name, value in [
            ("organisation", organisation),
            ("project", project),
            ("environment", environment),
            ("service", service),
        ]:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a string, got {type(value).__name__}")

        # Validate hierarchy - cannot skip levels
        if service is not None and environment is None:
            raise ValueError("service requires environment to be specified")
        if environment is not None and project is None:
            raise ValueError("environment requires project to be specified")
        if project is not None and organisation is None:
            raise ValueError("project requires organisation to be specified")

        return func(*args, **kwargs)

    return wrapper
