from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class PendingApproval(BaseModel):
    """A tool call awaiting a human verdict, surfaced by the Temporal workflow."""

    tool_call_id: str
    tool_name: str
    args: dict | str | None


class Verdicts(BaseModel):
    """Human approve/deny decisions, keyed by tool_call_id."""

    decisions: dict[str, bool]


# The two shapes of an approval reply. Omnigent's server forwards the envelope;
# the harness scaffold validates the flat form. These models + from_envelope are
# the whole adapter — see harness.FlattenApprovalEnvelope.


class ApprovalEnvelope(BaseModel):
    """As Omnigent forwards it: {"type": "approval", "data": {...}}."""

    type: Literal["approval"]
    data: dict[str, Any]


class FlatApproval(BaseModel):
    """As the harness scaffold wants it: the fields at the top level."""

    model_config = ConfigDict(extra="allow")  # keep any fields we don't name

    type: Literal["approval"] = "approval"
    elicitation_id: str
    action: str
    content: dict[str, Any] | None = None

    @classmethod
    def from_envelope(cls, envelope: ApprovalEnvelope) -> "FlatApproval":
        return cls(**envelope.data)
