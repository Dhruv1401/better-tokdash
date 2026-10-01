"""Mutation harness: semantic mutations vs targeted test subsets.

For each mutation: copy src/ to a scratch dir, apply one textual mutation,
run the targeted tests with PYTHONPATH pointed at the mutated tree, record
SURVIVED (tests still pass => testing gap) or KILLED (tests fail).
The real repo is never modified.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
SCRATCH = Path(__file__).resolve().parent / "mutant"
PY = sys.executable

# (name, file, old, new, targeted tests)
MUTATIONS = [
    (
        "M1 claude supersede: > becomes >= (equal totals now supersede)",
        "src/tokdash/sources/coding_tools.py",
        "    if total != best_total:\n        return total > best_total",
        "    if total != best_total:\n        return total >= best_total",
        ["tests/test_claude_session_cache_parity.py", "tests/test_usage_cache_identity.py"],
    ),
    (
        "M2 claude supersede: drop the equal-total-different-split reclassification rule",
        "src/tokdash/sources/coding_tools.py",
        "    if total != best_total:\n        return total > best_total\n    return buckets != best_buckets",
        "    if total != best_total:\n        return total > best_total\n    return False",
        ["tests/test_claude_session_cache_parity.py", "tests/test_session_cache_pricing.py"],
    ),
    (
        "M3 codex: disable stable-key replay dedup",
        "src/tokdash/sources/coding_tools.py",
        "                    if event_key and event_key in event_index_by_key:\n"
        "                        self.replay_events_skipped += 1",
        "                    if False and event_key and event_key in event_index_by_key:\n"
        "                        self.replay_events_skipped += 1",
        ["tests/test_pi_fork_replay.py", "tests/test_usage_cache_identity.py",
         "tests/test_session_merge_batch.py"],
    ),
    (
        "M4 parse_entries_json: drop reasoning from headline total",
        "src/tokdash/compute.py",
        "        total_tokens = tokens_in + tokens_out + tokens_cache + reasoning",
        "        total_tokens = tokens_in + tokens_out + tokens_cache",
        ["tests/test_review_fix_behaviors.py", "tests/test_insights_api.py",
         "tests/test_overview_active_time.py"],
    ),
    (
        "M5 aggregate_entries: unpriced detection cost <= 0 -> cost < 0",
        "src/tokdash/usage_store.py",
        "SUM(CASE WHEN cost <= 0 AND cost_authoritative = 0 THEN input ELSE 0 END) AS input_unpriced",
        "SUM(CASE WHEN cost < 0 AND cost_authoritative = 0 THEN input ELSE 0 END) AS input_unpriced",
        ["tests/test_usage_store.py", "tests/test_session_cache_pricing.py",
         "tests/test_provider_reported_cost.py"],
    ),
    (
        "M6 cache_hit_rate: den <= 0 -> den == 0",
        "src/tokdash/compute.py",
        "    if den <= 0:\n        return None\n    return round(num / den, 4)",
        "    if den == 0:\n        return None\n    return round(num / den, 4)",
        ["tests/test_cache_hit_rate.py"],
    ),
    (
        "M7 period fallback: unknown period resolves to today (the D1 regression)",
        "src/tokdash/compute.py",
        "    return ALL_TIME_DAYS",
        "    return 1",
        ["tests/test_period_semantics.py", "tests/test_insights_api.py"],
    ),
    (
        "M8 dateutil: since >= until -> since > until (accept inverted ranges)",
        "src/tokdash/dateutil.py",
        "    if since >= until:",
        "    if since > until:",
        ["tests/test_period_semantics.py", "tests/test_insights_api.py",
         "tests/test_usage_refresh_frontend.py"],
    ),
    (
        "M9 contributions: drop cost accumulation on heatmap days",
        "src/tokdash/compute.py",
        "        day[\"totals\"][\"tokens\"] += total\n        day[\"totals\"][\"cost\"] += cost",
        "        day[\"totals\"][\"tokens\"] += total\n        day[\"totals\"][\"cost\"] += 0.0",
        ["tests/test_insights_api.py", "tests/test_period_semantics.py",
         "tests/test_tui_charts.py"],
    ),
    (
        "M10 usage_billing: pricing fallback first-non-zero-wins -> always first candidate",
        "src/tokdash/usage_store.py",
        "            if cost > 0:\n                return cost",
        "            if cost >= 0:\n                return cost",
        ["tests/test_session_cache_pricing.py", "tests/test_pricing_override_cache_busting.py",
         "tests/test_usage_store.py"],
    ),
    (
        "M11 store cross-file tie: earliest-path-wins -> later-path-wins",
        "src/tokdash/usage_store.py",
        "                                        AND excluded.file_path <= usage_entries.file_path)))",
        "                                        AND excluded.file_path >= usage_entries.file_path)))",
        ["tests/test_usage_store.py", "tests/test_pi_fork_replay.py",
         "tests/test_session_merge_batch.py"],
    ),
    (
        "M12 sync: tail-append accepts ANY growth (skip old-signature guard)",
        "src/tokdash/usage_store.py",
        "                if size > old_size and old_sig == state.get(\"signature\"):",
        "                if size > old_size:",
        ["tests/test_usage_store.py", "tests/test_closed_window_cache_freshness.py",
         "tests/test_sync_single_flight.py"],
    ),
]


def prepare_scratch():
    if SCRATCH.exists():
        for attempt in range(5):
            try:
                shutil.rmtree(SCRATCH)
                break
            except PermissionError:
                import time
                time.sleep(1)
        else:
            if SCRATCH.exists():
                # last resort: leave tests dir stale, it gets overwritten below
                pass
    (SCRATCH / "src").parent.mkdir(parents=True, exist_ok=True)
    if not (SCRATCH / "src").exists():
        shutil.copytree(REPO / "src", SCRATCH / "src")
    if not (SCRATCH / "tests").exists():
        shutil.copytree(REPO / "tests", SCRATCH / "tests")
    if not (SCRATCH / "pyproject.toml").exists():
        shutil.copy(REPO / "pyproject.toml", SCRATCH / "pyproject.toml")


def apply_mutation(rel_path: str, old: str, new: str) -> bool:
    p = SCRATCH / rel_path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        return False
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def run_tests(targets) -> tuple[bool, str]:
    env: dict[str, str] = {
        **{k: v for k, v in __import__("os").environ.items() if not k.startswith("TOKDASH")},
        "PYTHONPATH": str(SCRATCH / "src"),
        "TOKDASH_DATA_DIR": str(SCRATCH / "data"),
        "TOKDASH_USAGE_DB": "0",
    }
    cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=600", *targets]
    proc = subprocess.run(cmd, cwd=SCRATCH, env=env, capture_output=True, text=True,
                          timeout=1200, encoding="utf-8", errors="replace")
    tail = (proc.stdout or "") + (proc.stderr or "")
    passed = proc.returncode == 0
    return passed, tail.strip().splitlines()[-1] if tail.strip() else "(no output)"


def main():
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    prepare_scratch()
    results = []
    for name, rel, old, new, targets in MUTATIONS:
        if only and not any(name.startswith(o + " ") or name.startswith(o + ":") for o in only):
            continue
        ok = apply_mutation(rel, old, new)
        if not ok:
            results.append((name, "MUTATION-DID-NOT-APPLY", ""))
            continue
        try:
            passed, last = run_tests(targets)
            results.append((name, "SURVIVED" if passed else f"KILLED ({last})", ""))
        except subprocess.TimeoutExpired:
            results.append((name, "TIMEOUT", ""))
        # restore pristine file
        shutil.copy(REPO / rel, SCRATCH / rel)
        print(f"{results[-1][1]:28s} {name}", flush=True)
    print("\n=== SUMMARY ===")
    for name, verdict, _ in results:
        print(f"{verdict:28s} {name}")


if __name__ == "__main__":
    main()
