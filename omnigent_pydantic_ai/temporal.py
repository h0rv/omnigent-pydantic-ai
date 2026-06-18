"""Durable mode: run the agent loop in a Temporal workflow.

Each model/tool call becomes a Temporal activity (via TemporalAgent). Approval
stays native: the workflow surfaces pending approvals via a query and waits for
a signal; the harness-side executor raises the Omnigent card and signals the
verdict back. Run the worker with `uv run -m omnigent_pydantic_ai.temporal`.
"""

import asyncio
import os

from temporalio import workflow
from temporalio.client import Client
from temporalio.worker import Worker

from omnigent_pydantic_ai.models import PendingApproval, Verdicts

with workflow.unsafe.imports_passed_through():
    from pydantic_ai import (
        DeferredToolRequests,
        DeferredToolResults,
        ToolApproved,
        ToolDenied,
    )
    from pydantic_ai.durable_exec.temporal import (
        PydanticAIPlugin,
        PydanticAIWorkflow,
        TemporalAgent,
    )

    from examples.agent import agent

temporal_agent = TemporalAgent(agent, name="review-agent")

ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7349")
NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "hitl")
TASK_QUEUE = "hitl"


@workflow.defn
class ReviewWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = [temporal_agent]

    def __init__(self) -> None:
        super().__init__()
        self._pending: list[PendingApproval] = []
        self._verdicts: dict[str, bool] | None = None

    @workflow.run
    async def run(self, prompt: str) -> str:
        result = await temporal_agent.run(prompt, deps=None)
        while isinstance(result.output, DeferredToolRequests):
            self._pending = [
                PendingApproval(
                    tool_call_id=c.tool_call_id, tool_name=c.tool_name, args=c.args
                )
                for c in result.output.approvals
            ]
            self._verdicts = None
            await workflow.wait_condition(lambda: self._verdicts is not None)
            decisions, self._pending = self._verdicts or {}, []

            verdicts = DeferredToolResults()
            for call in result.output.approvals:
                approved = bool(decisions.get(call.tool_call_id, False))
                verdicts.approvals[call.tool_call_id] = (
                    ToolApproved() if approved else ToolDenied()
                )
            result = await temporal_agent.run(
                message_history=result.all_messages(),
                deferred_tool_results=verdicts,
                deps=None,
            )
        return str(result.output)

    @workflow.signal
    async def submit_verdicts(self, verdicts: Verdicts) -> None:
        self._verdicts = verdicts.decisions

    @workflow.query
    def pending_approvals(self) -> list[PendingApproval]:
        return self._pending


async def connect() -> Client:
    return await Client.connect(
        ADDRESS, namespace=NAMESPACE, plugins=[PydanticAIPlugin()]
    )


async def run_worker() -> None:
    client = await connect()
    # PydanticAIPlugin auto-registers the agent's activities from the
    # workflow's __pydantic_ai_agents__, so we don't pass them here.
    async with Worker(client, task_queue=TASK_QUEUE, workflows=[ReviewWorkflow]):
        print(f"worker up on {ADDRESS}/{NAMESPACE} (task_queue={TASK_QUEUE})")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run_worker())
