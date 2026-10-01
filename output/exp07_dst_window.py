"""EXP-07: DST anchoring of date windows.

parse_date_range / _date_range_from_args build local midnights by attaching
datetime.now().astimezone().tzinfo — the CURRENT fixed offset — to arbitrary
dates. For dates in the other DST phase, the window boundary drifts by the
DST delta (1h in most zones), so rows in the first/last hour of the day can
land in the wrong day-window.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

from tokdash.dateutil import parse_date_range

print("This machine's local tz:", datetime.now().astimezone().tzinfo)

# Simulate a New York machine in September (EDT, UTC-4) asking for a January window.
edt = timezone(timedelta(hours=-4), "EDT")  # the fixed offset now() captures in September

# What the code does: replace(tzinfo=<fixed current offset>)
jan_window_since = datetime.strptime("2026-01-05", "%Y-%m-%d").replace(tzinfo=edt)
jan_window_until = datetime.strptime("2026-01-05", "%Y-%m-%d").replace(tzinfo=edt) + timedelta(days=1)

# What true local midnight EST (UTC-5) would be:
true_since = datetime(2026, 1, 5, tzinfo=timezone(timedelta(hours=-5)))
true_until = datetime(2026, 1, 6, tzinfo=timezone(timedelta(hours=-5)))

print(f"code-built Jan 5 window (UTC): {jan_window_since.astimezone(timezone.utc)} .. {jan_window_until.astimezone(timezone.utc)}")
print(f"true local midnight (UTC):     {true_since.astimezone(timezone.utc)} .. {true_until.astimezone(timezone.utc)}")
drift = jan_window_since.astimezone(timezone.utc) - true_since.astimezone(timezone.utc)
print(f"boundary drift: {drift}")

# Consequence: a Claude event stamped 2026-12-31T23:30 local EST (= 2027-01-01T04:30Z? no —)
# Event: Dec 31, 23:30 EST = Jan 1, 04:30 UTC? Dec 31 23:30 -05:00 = Jan 1 04:30Z.
# A window "2026-01-01..2026-01-31" built with the EDT anchor starts at
# 2026-01-01T00:00-04:00 = 04:00Z. The Dec-31 23:30 EST event (04:30Z? that's AFTER 04:00Z Jan 1)...
evt = datetime(2026, 12, 31, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
print(f"\nEvent Dec 31 23:30 EST = {evt.astimezone(timezone.utc)} UTC")
w_start = datetime.strptime("2026-01-01", "%Y-%m-%d").replace(tzinfo=edt)
print(f"January window (EDT anchor) starts {w_start.astimezone(timezone.utc)} UTC")
print("Event inside January window?", evt.astimezone(timezone.utc) >= w_start)
