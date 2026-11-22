"""Print which tests cover each hard-frame rule. Always exits 0."""

import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
found: dict[int, list[str]] = {}
for f in sorted(root.glob("apps/**/tests/test_*.py")):
    for m in re.finditer(r"^\s*def (test_hf(\d\d)_\w*)", f.read_text(), re.M):
        found.setdefault(int(m.group(2)), []).append(f"{f.relative_to(root)}::{m.group(1)}")

for n in range(1, 21):
    tests = found.get(n)
    print(f"HF-{n}: " + (", ".join(tests) if tests else "MISSING"))
