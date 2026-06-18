"""The `pydantic-ai` harness: create_app() wraps our executor for Omnigent.

The runner resolves the harness name to this module (via _HARNESS_MODULES) and
serves create_app() over a unix socket — same contract as the built-in pi /
claude-sdk wraps.
"""

import json

from fastapi import FastAPI

from omnigent.runtime.harnesses._executor_adapter import ExecutorAdapter

from omnigent_pydantic_ai.executor import PydanticAIExecutor


def flatten_approval(body: bytes) -> bytes:
    """Rewrite Omnigent's approval envelope to the flat fields the scaffold wants.

    The server forwards `{type: approval, data: {elicitation_id, action}}`, but
    the harness scaffold's ApprovalEvent expects those fields at the top level —
    otherwise it 422s and the elicitation Future never resolves (the turn hangs).
    """
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body
    if payload.get("type") == "approval" and isinstance(payload.get("data"), dict):
        return json.dumps({"type": "approval", **payload["data"]}).encode()
    return body


class FlattenApprovalEnvelope:
    """ASGI middleware applying flatten_approval to POST .../events bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        is_event_post = (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and scope.get("path", "").endswith("/events")
        )
        if not is_event_post:
            await self.app(scope, receive, send)
            return

        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        body = flatten_approval(body)

        headers = [
            (k, v)
            for k, v in scope.get("headers", [])
            if k.lower() != b"content-length"
        ]
        headers.append((b"content-length", str(len(body)).encode()))
        scope = {**scope, "headers": headers}

        sent = False

        async def replay_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return (
                await receive()
            )  # delegate on (e.g. http.disconnect) so streaming works

        await self.app(scope, replay_receive, send)


def create_app() -> FastAPI:
    app = ExecutorAdapter(executor_factory=PydanticAIExecutor).build()
    app.add_middleware(FlattenApprovalEnvelope)
    return app
