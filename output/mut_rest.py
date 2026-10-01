import subprocess, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mutations import prepare_scratch, apply_mutation, run_tests, SCRATCH, REPO

REST = {
  "M2": ("src/tokdash/sources/coding_tools.py",
         "    if total != best_total:\n        return total > best_total\n    return buckets != best_buckets",
         "    if total != best_total:\n        return total > best_total\n    return False"),
  "M6": ("src/tokdash/compute.py",
         "    if den <= 0:\n        return None\n    return round(num / den, 4)",
         "    if den == 0:\n        return None\n    return round(num / den, 4)"),
  "M8": ("src/tokdash/dateutil.py",
         "    if since >= until:",
         "    if since > until:"),
  "M9": ("src/tokdash/compute.py",
         '        day["totals"]["tokens"] += total\n        day["totals"]["cost"] += cost',
         '        day["totals"]["tokens"] += total\n        day["totals"]["cost"] += 0.0'),
  "M12": ("src/tokdash/usage_store.py",
          '                if size > old_size and old_sig == state.get("signature"):',
          "                if size > old_size:"),
}
prepare_scratch()
for name, (rel, old, new) in REST.items():
    assert apply_mutation(rel, old, new), name
    try:
        passed, last = run_tests(["tests"])
        print(f"{name} FULL SUITE: {'SURVIVED' if passed else 'KILLED'} ({last})", flush=True)
    except Exception as e:
        print(f"{name} ERROR: {e}", flush=True)
    for attempt in range(5):
        try:
            shutil.copy(REPO / rel, SCRATCH / rel)
            break
        except PermissionError:
            time.sleep(1)
print("DONE", flush=True)
