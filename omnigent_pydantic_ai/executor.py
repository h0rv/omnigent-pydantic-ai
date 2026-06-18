"""Omnigent Executor that runs a Pydantic AI agent — in-process or on Temporal.

`handles_tools_internally` is True (the agent owns its tool loop), and the
ExecutorAdapter injects `_elicitation_handler`, which raises a native Omnigent
approval card. When the agent gates a tool (`requires_approval`) it returns
`DeferredToolRequests`; we get the verdict via that handler and resume. The
adapter ignores `TurnComplete.response`, so output is emitted as `TextChunk`.
"""

import asyncio
import importlib
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)

from omnigent.inner.executor import (
    Executor,
    ExecutorConfig,
    ExecutorEvent,
    Message,
    TextChunk,
    ToolSpec,
    TurnComplete,
)

# "module:attr" of the Pydantic AI Agent to run; "in_process" or "temporal".
AGENT_REF = os.environ.get("PYDANTIC_AI_AGENT", "examples.agent:agent")
EXECUTION = os.environ.get("PYDANTIC_AI_EXECUTION", "in_process")


def load_agent() -> Any:
    module, _, attr = AGENT_REF.partition(":")
    return getattr(importlib.import_module(module), attr or "agent")


def last_user_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            ).strip()
    return ""


def as_dict(args: Any) -> dict:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {"args": parsed}
        except (json.JSONDecodeError, TypeError):
            return {"args": args}
    return {"args": args}


class PydanticAIExecutor(Executor):
    def __init__(self) -> None:
        self.agent = load_agent()
        self._elicitation_handler = None  # injected by ExecutorAdapter

    def handles_tools_internally(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True

    async def run_turn(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        system_prompt: str,
        config: ExecutorConfig | None = None,
    ) -> AsyncIterator[ExecutorEvent]:
        prompt = last_user_text(messages)
        if EXECUTION == "temporal":
            output = await self._run_temporal(prompt)
        else:
            output = await self._run_in_process(prompt)
        if output:
            yield TextChunk(text=output)
        yield TurnComplete()

    async def _run_in_process(self, prompt: str) -> str:
        result = await self.agent.run(prompt)
        while isinstance(result.output, DeferredToolRequests):
            verdicts = DeferredToolResults()
            for call in result.output.approvals:
                approved = await self._approve(call.tool_name, as_dict(call.args))
                verdicts.approvals[call.tool_call_id] = (
                    ToolApproved() if approved else ToolDenied()
                )
            result = await self.agent.run(
                message_history=result.all_messages(), deferred_tool_results=verdicts
            )
        return str(result.output)

    async def _run_temporal(self, prompt: str) -> str:
        # Durable: the agent loop runs in a Temporal workflow; we drive native
        # approvals via its query (pending) + signal (verdicts) bridge.
        from omnigent_pydantic_ai.temporal import TASK_QUEUE, ReviewWorkflow, connect
        from omnigent_pydantic_ai.models import Verdicts

        client = await connect()
        handle = await client.start_workflow(
            ReviewWorkflow.run,
            prompt,
            id=f"review-{uuid.uuid4().hex[:12]}",
            task_queue=TASK_QUEUE,
        )
        result = asyncio.ensure_future(handle.result())
        handled: set[str] = set()
        while not result.done():
            try:
                pending = await handle.query(ReviewWorkflow.pending_approvals)
            except Exception:
                pending = []
            fresh = [p for p in pending if p.tool_call_id not in handled]
            if fresh:
                decisions = {}
                for p in fresh:
                    handled.add(p.tool_call_id)
                    decisions[p.tool_call_id] = await self._approve(
                        p.tool_name, as_dict(p.args)
                    )
                await handle.signal(
                    ReviewWorkflow.submit_verdicts, Verdicts(decisions=decisions)
                )
            else:
                await asyncio.sleep(0.4)
        return await result

    async def _approve(self, tool_name: str, tool_input: dict) -> bool:
        # Raise a native Omnigent approval card; default-allow only if unwired.
        if self._elicitation_handler is None:
            return True
        return await self._elicitation_handler(tool_name, tool_input)
