"""EXP-08: XSS sink audit — find innerHTML template interpolations that are
NOT escapeHtml'd, and check whether any carries attacker-controlled data
(model names, session ids, workspace/project paths, cost, provider ids all
come from local log files, which an attacker may influence via malicious
repos/log injection).

Static pass + targeted extraction; no live server needed.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
SRC = (REPO / "src" / "tokdash" / "static" / "index.html").read_text(encoding="utf-8")

# find every ${...} inside the file, with line numbers
lines = SRC.splitlines()
interp = re.compile(r"\$\{([^}]+)\}")

SINK_CONTEXT = re.compile(r"innerHTML\s*=\s*[`\"']|\binnerHTML\s*=")

dangerous = []
for i, line in enumerate(lines, 1):
    if "innerHTML" not in line:
        continue
    for m in interp.finditer(line):
        expr = m.group(1).strip()
        if "escapeHtml" in expr or "t(" == expr[:2] or expr.startswith("t('"):
            continue
        # expressions that are known-safe constants
        if re.fullmatch(r"[\d\s.+\-*/]+", expr):
            continue
        if expr in ("glyphs[icon] || glyphs.cross",):
            continue
        if expr.startswith(("String(", "Number(", "formatCurrency(", "formatTokenCount(",
                            "formatNumber(", "formatPct(", "formatRelativeTime(")):
            # number formatters are safe; String(x) may not be
            if not expr.startswith("String("):
                continue
        dangerous.append((i, expr[:130], line.strip()[:170]))

print(f"{len(dangerous)} unescaped interpolations inside innerHTML assignments:\n")
for i, expr, line in dangerous:
    print(f"L{i}: ${{{expr}}}")
    print(f"     {line}\n")
