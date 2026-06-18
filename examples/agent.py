"""Example agent: Gemini on Vertex with an approval-gated `commit` tool.

The user-authored part — a normal Pydantic AI Agent. `commit` is marked
`requires_approval`, so the run returns DeferredToolRequests and Omnigent
gathers the human verdict before it executes.
"""

import os

from pydantic_ai import Agent, DeferredToolRequests, RunContext
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google_cloud import GoogleCloudProvider

model = GoogleModel(
    os.environ.get("PYDANTIC_AI_MODEL", "gemini-3.1-flash-lite"),
    provider=GoogleCloudProvider(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
    ),
)

agent = Agent(
    model,
    name="review-agent",
    output_type=[str, DeferredToolRequests],
    system_prompt=(
        "You reconcile a batch and propose a commit. Call the commit tool to "
        "finalize it. Commit requires human approval."
    ),
)


@agent.tool(requires_approval=True)
async def commit(ctx: RunContext[None], summary: str) -> str:
    return f"Committed: {summary}"
