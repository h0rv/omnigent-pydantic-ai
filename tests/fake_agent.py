"""Deterministic offline agent for tests — same shape as agent.py, no network.

A FunctionModel calls the approval-gated `commit`, then emits final text once
the tool has run, so the HITL round-trip is reproducible without Vertex.
"""

from pydantic_ai import Agent, DeferredToolRequests, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

FINAL_TEXT = "Batch #42 reconciled and committed."


def model_function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolReturnPart) and part.tool_name == "commit":
                return ModelResponse(parts=[TextPart(content=FINAL_TEXT)])
    return ModelResponse(
        parts=[ToolCallPart(tool_name="commit", args={"summary": "Reconciled #42."})]
    )


agent = Agent(
    FunctionModel(model_function),
    output_type=[str, DeferredToolRequests],
    system_prompt="Reconcile the batch and commit it; commit requires approval.",
)


@agent.tool(requires_approval=True)
async def commit(ctx: RunContext[None], summary: str) -> str:
    return f"Committed: {summary}"
