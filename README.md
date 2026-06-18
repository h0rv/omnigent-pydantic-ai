# omnigent-pydantic-ai

Run [Pydantic AI](https://ai.pydantic.dev) agents inside [Omnigent](https://github.com/omnigent-ai/omnigent) — in the dropdown, on a host, with native human-in-the-loop approval. The same agent runs in-process or durably on Temporal. Omnigent ships no Pydantic AI harness; `omnigent_pydantic_ai/` is one.

```mermaid
flowchart LR
  UI[Omnigent dropdown] --> H[host / runner]
  H --> X["pydantic-ai harness (create_app)"]
  X --> E[PydanticAIExecutor]
  E -->|in-process| A[Pydantic AI agent]
  E -->|temporal| W[Temporal workflow]
  A -. requires_approval .-> C[native approval card]
  W -. query / signal .-> C
```

On an approval-gated tool the agent returns `DeferredToolRequests`; the executor raises a native Omnigent card and resumes on the verdict.

## Define an agent

A normal Pydantic AI agent plus an Omnigent spec that selects the harness:

- `examples/agent.py` — gate tools with `@agent.tool(requires_approval=True)` and `output_type=[str, DeferredToolRequests]`.
- `examples/config.yaml` — `executor: {type: omnigent, config: {harness: pydantic-ai}}`. A dir with `config.yaml` at its root is the agent bundle, so `--agent examples` registers it.

The harness loads `$PYDANTIC_AI_AGENT` (default `examples.agent:agent`); `$PYDANTIC_AI_EXECUTION` picks `in_process` (default) or `temporal`.

## Run

```sh
gcloud auth application-default login    # once, for Vertex
uv sync && source scripts/env.sh
python scripts/patch_omnigent.py         # register the harness (idempotent)

omnigent server -p 6868 --agent examples &
omnigent host --server http://localhost:6868 &
# open http://localhost:6868 → review-agent → message it → approve the commit card
```

REPL instead of the UI: `omnigent run examples -p "Reconcile batch #42 and commit it."`

Durable on Temporal (output arrives at turn boundaries — Temporal buffers streaming):

```sh
temporal server start-dev --port 7349 --namespace hitl &
python -m omnigent_pydantic_ai.temporal &      # worker
PYDANTIC_AI_EXECUTION=temporal omnigent run examples -p "..."
```

Test: `uv run python tests/test_harness_hitl.py`

## Patches to Omnigent

Omnigent 0.1.x has no harness plugin point, so `scripts/patch_omnigent.py` adds `pydantic-ai` to two allowlists (`_HARNESS_MODULES`, `OMNIGENT_HARNESSES`). One more rough edge is handled in `harness.py`: Omnigent forwards approvals as `{type, data:{...}}` but the harness scaffold wants those fields flat (else it 422s and the turn hangs), so a small ASGI middleware flattens them. Clean upstream fixes: a plugin entry point, and forwarding flat or accepting the envelope.
