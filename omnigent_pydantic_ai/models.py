from pydantic import BaseModel


class PendingApproval(BaseModel):
    """A tool call awaiting a human verdict, surfaced by the Temporal workflow."""

    tool_call_id: str
    tool_name: str
    args: dict | str | None


class Verdicts(BaseModel):
    """Human approve/deny decisions, keyed by tool_call_id."""

    decisions: dict[str, bool]
