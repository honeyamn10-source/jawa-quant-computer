"""Domain errors with actionable messages."""

from __future__ import annotations


class JqcError(Exception):
    """Base error."""


class ProviderUnavailable(JqcError):
    """A model provider is offline, unreachable or misconfigured."""

    def __init__(self, provider: str, endpoint: str, detail: str = "") -> None:
        self.provider = provider
        self.endpoint = endpoint
        self.detail = detail
        super().__init__(f"Provider '{provider}' is unavailable at {endpoint}. {detail}")

    def user_message(self) -> str:
        lines = [
            "The AI service is not available.",
            "",
            f"Detected endpoint: {self.endpoint}",
            "",
            "• [Start setup]  →  • [Change endpoint]  →  • [Retry]",
        ]
        return "\n".join(lines)


class PermissionDenied(JqcError):
    """The action was blocked by the permission policy or a denied approval."""


class PlanParseError(JqcError):
    """The planner produced JSON we could not understand."""


class SkillNotFound(JqcError):
    """No skill registered for the requested tool name."""


class ActionNotFound(JqcError):
    """A skill has no action with that name."""


class TaskCancelled(JqcError):
    """The task was cancelled by the user."""


class MaxStepsExceeded(JqcError):
    """Resource control limit reached."""


class MaxRuntimeExceeded(JqcError):
    """Resource control limit reached."""


class VerificationFailed(JqcError):
    """The verifier could not confirm the outcome of a step."""
