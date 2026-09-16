class ApiContractError(Exception):
    """Base class for every error raised by this package."""


class ConfigurationError(ApiContractError):
    """Raised when the API_CONTRACT settings block is unusable."""


class SchemaGenerationError(ApiContractError):
    """Raised when the OpenAPI schema could not be produced."""


class SchemaValidationError(ApiContractError):
    def __init__(self, message: str, problems=None):
        super().__init__(message)
        self.problems = list(problems or [])


class PostmanSyncError(ApiContractError):
    """Raised when an existing Postman collection cannot be synchronized."""


class ContractOutOfDateError(ApiContractError):
    """Raised by ``check`` when committed artifacts do not match the API."""


class BreakingChangeError(ApiContractError):
    def __init__(self, message: str, changes=None):
        super().__init__(message)
        self.changes = list(changes or [])
