"""Integration test: the native HITL approval round-trip, over in-process ASGI.

Serves the real harness on a unix socket (as Omnigent's runner does) and replays
the exact event protocol: post a turn, get `response.elicitation_request`, post
the approval **in the envelope shape the Omnigent server sends**
(`{type:approval, data:{...}}`), and assert the turn completes. Without the
envelope-flattening fix this 422s and the turn hangs.

    uv run python tests/test_harness_hitl.py
    uv run pytest tests/test_harness_hitl.py
"""

import asyncio
import contextlib
import json
import os

os.environ["PYDANTIC_AI_AGENT"] = "tests.fake_agent:agent"  # set before harness import

import httpx
import uvicorn

from tests.fake_agent import FINAL_TEXT

CONV = "conv_test_hitl"
AGENT_NAME = "review-agent"
TIMEOUT_S = 30


@contextlib.asynccontextmanager
async def serve_harness():
    from omnigent_pydantic_ai import harness

    app = harness.create_app()
    app.state.conversation_id = CONV  # the runner normally stashes these
    app.state.harness = "pydantic-ai"

    sock = f"/tmp/hitl_{os.getpid()}.sock"  # short: macOS unix sockets cap ~104 chars
    with contextlib.suppress(FileNotFoundError):
        os.unlink(sock)
    server = uvicorn.Server(uvicorn.Config(app, uds=sock, log_level="warning"))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if server.started:
                break
            if task.done():
                task.result()
            await asyncio.sleep(0.02)
        transport = httpx.AsyncHTTPTransport(uds=sock)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://harness.local"
        ) as c:
            yield c
    finally:
        server.should_exit = server.force_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=5)


def sse_data(line: str) -> dict | None:
    if not line.startswith("data:"):
        return None
    with contextlib.suppress(json.JSONDecodeError):
        return json.loads(line[len("data:") :].strip() or "null")
    return None


async def run_round_trip() -> dict:
    elicitation_id = asyncio.get_event_loop().create_future()
    events: list[dict] = []
    approval: dict = {}

    async def stream_turn(client):
        body = {
            "type": "message",
            "role": "user",
            "content": "commit it",
            "model": AGENT_NAME,
        }
        async with client.stream(
            "POST", f"/v1/sessions/{CONV}/events", json=body
        ) as resp:
            async for line in resp.aiter_lines():
                evt = sse_data(line)
                if not evt:
                    continue
                events.append(evt)
                if (
                    evt.get("type") == "response.elicitation_request"
                    and not elicitation_id.done()
                ):
                    elicitation_id.set_result(evt["elicitation_id"])
                if evt.get("type") in (
                    "response.completed",
                    "response.failed",
                    "response.cancelled",
                ):
                    return

    async def approve(client):
        eid = await elicitation_id
        resp = await client.post(
            f"/v1/sessions/{CONV}/events",
            json={
                "type": "approval",
                "data": {"elicitation_id": eid, "action": "accept"},
            },
        )
        approval["code"] = resp.status_code

    timed_out = False
    try:
        async with serve_harness() as client:
            await asyncio.wait_for(
                asyncio.gather(stream_turn(client), approve(client)), TIMEOUT_S
            )
    except asyncio.TimeoutError:
        timed_out = True

    return {
        "elicited": elicitation_id.done(),
        "timed_out": timed_out,
        "approval": approval.get("code"),
        "completed": any(e.get("type") == "response.completed" for e in events),
        "final_text": any(FINAL_TEXT in json.dumps(e) for e in events),
    }


def check(r: dict) -> None:
    assert r["elicited"], "agent never raised an elicitation"
    assert not r["timed_out"], (
        f"turn hung — approval did not resolve (envelope 422?): {r}"
    )
    assert r["approval"] in (200, 202, 204), f"approval rejected: {r}"
    assert r["completed"] and r["final_text"], (
        f"turn did not complete with final text: {r}"
    )


def test_hitl_approval_round_trip():
    check(asyncio.run(run_round_trip()))


if __name__ == "__main__":
    result = asyncio.run(run_round_trip())
    try:
        check(result)
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1)
    print(f"PASS: {result}")
