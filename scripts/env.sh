# Source before running any omnigent command: `source env.sh`
# Pins the env the harness needs across the server, host daemon, and the
# harness subprocess they spawn.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# So the runner subprocess can import omnigent_pydantic_ai and examples.agent.
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"

# Gemini on Vertex via gcloud ADC (`gcloud auth application-default login`).
# Set GOOGLE_CLOUD_PROJECT to your project (or rely on the ADC quota project).
export GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
export PYDANTIC_AI_MODEL="${PYDANTIC_AI_MODEL:-gemini-3.1-flash-lite}"

# Use the venv's omnigent (patched), not a global/Homebrew one.
export PATH="$HERE/.venv/bin:$PATH"
