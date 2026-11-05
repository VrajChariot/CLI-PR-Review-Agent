class PrReviewError(Exception):
    """Base class for all expected CLI failures."""


class ConfigError(PrReviewError):
    """Invalid arguments, environment, or local setup."""


class PlatformError(PrReviewError):
    """Pull request platform (GitHub / Azure DevOps) request failed."""


class WorkspaceError(PrReviewError):
    """Local git operation failed."""


class AgentError(PrReviewError):
    """The review agent failed."""
