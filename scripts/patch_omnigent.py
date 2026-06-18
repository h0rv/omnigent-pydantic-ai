"""Register the `pydantic-ai` harness in the installed Omnigent.

Omnigent 0.1.x has no plugin point for harnesses — the set is hardcoded in two
allowlists. This adds our entry to both, in whichever Omnigent the active
interpreter imports (run it with the same venv you run `omnigent` from).
Idempotent.

    python patch_omnigent.py            # apply
    python patch_omnigent.py --check    # report only; exit 1 if unpatched
"""

import sys
from pathlib import Path

import omnigent

HARNESS = "pydantic-ai"
MODULE = "omnigent_pydantic_ai.harness"
ROOT = Path(omnigent.__file__).parent

TARGETS = [
    # name -> module, used by the runner to import the harness app
    (
        ROOT / "runtime" / "harnesses" / "__init__.py",
        "_HARNESS_MODULES: dict[str, str] = {\n",
        f'    "{HARNESS}": "{MODULE}",\n',
    ),
    # spec-validator allowlist (rejects unknown harness names at load time)
    (
        ROOT / "spec" / "_omnigent_compat.py",
        "OMNIGENT_HARNESSES = frozenset(\n    {\n",
        f'        "{HARNESS}",\n',
    ),
]


def main() -> None:
    check = "--check" in sys.argv
    missing = False
    for path, anchor, insert in TARGETS:
        text = path.read_text()
        if HARNESS in text:
            print(f"[ok]      {path}")
            continue
        missing = True
        if check:
            print(f"[MISSING] {path}")
            continue
        if anchor not in text:
            sys.exit(f"anchor not found in {path} — Omnigent layout changed")
        path.write_text(text.replace(anchor, anchor + insert, 1))
        print(f"[patched] {path}")
    if check and missing:
        sys.exit(1)
    if not check:
        print(f"\n{HARNESS!r} -> {MODULE!r} in {ROOT}")


if __name__ == "__main__":
    main()
