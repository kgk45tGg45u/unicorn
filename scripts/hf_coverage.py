"""Print which tests cover each hard-frame rule. Exits with 1 when a rule has no test (P15.T10)."""

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
found: dict[int, list[str]] = {}
for f in sorted(root.glob("apps/**/tests/test_*.py")):
    for m in re.finditer(r"^\s*def (test_hf(\d\d)_\w*)", f.read_text(), re.M):
        found.setdefault(int(m.group(2)), []).append(f"{f.relative_to(root)}::{m.group(1)}")

missing = []
for n in range(1, 21):
    tests = found.get(n)
    print(f"HF-{n}: " + (", ".join(tests) if tests else "MISSING"))
    if not tests:
        missing.append(n)

if missing:
    print("\nNo test for: " + ", ".join(f"HF-{n}" for n in missing), file=sys.stderr)
    sys.exit(1)
