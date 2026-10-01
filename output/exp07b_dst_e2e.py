"""EXP-07b: end-to-end through tokdash.dateutil.parse_date_range with a faked
'september afternoon in New York' now().  Shows the Jan-5 window drifts one
hour off true local midnight and disagrees with the localtime day-bucketing
used by the heatmap.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

from tokdash import dateutil


class NY(tzinfo):
    """America/New_York rules for 2025-2027 only (DST since 2007: Mar 2nd Sun - Nov 1st Sun)."""
    def _is_dst(self, dt):
        if dt.month < 3 or dt.month >= 12:
            return False
        if dt.month > 3 and dt.month < 11:
            return True
        if dt.month == 3:
            second_sun = 8 + (6 - datetime(dt.year, 3, 1).weekday()) % 7
            return dt.day > second_sun or (dt.day == second_sun and dt.hour >= 2)
        first_sun = 1 + (6 - datetime(dt.year, 11, 1).weekday()) % 7
        return not (dt.day < first_sun or (dt.day == first_sun and dt.hour < 2))
    def utcoffset(self, dt):
        return timedelta(hours=-4) if self._is_dst(dt) else timedelta(hours=-5)
    def tzname(self, dt):
        return "EDT" if self._is_dst(dt) else "EST"
    def dst(self, dt):
        return timedelta(hours=1) if self._is_dst(dt) else timedelta()


class FakeNow(datetime):
    @classmethod
    def now(cls, tz=None):
        # 2026-09-15 14:00 in New York (EDT, UTC-4)
        base = datetime(2026, 9, 15, 14, 0, tzinfo=NY())
        return base if tz is None else base.astimezone(tz)


dateutil.datetime = FakeNow  # patch the module under test

since, until = dateutil.parse_date_range("2026-01-05", "2026-01-05")
true_since = datetime(2026, 1, 5, 0, 0, tzinfo=NY())   # true local midnight, EST
true_until = datetime(2026, 1, 6, 0, 0, tzinfo=NY())

print("code window :", since.astimezone(timezone.utc), "->", until.astimezone(timezone.utc))
print("true window :", true_since.astimezone(timezone.utc), "->", true_until.astimezone(timezone.utc))
print("start drift :", (since - true_since).total_seconds(), "s; end drift:", (until - true_until).total_seconds(), "s")

# An event at Jan 5, 23:30 true local (EST): heatmap buckets it on Jan 5.
evt = datetime(2026, 1, 5, 23, 30, tzinfo=NY())
in_window = since <= evt < until
print(f"event Jan 5 23:30 EST ({evt.astimezone(timezone.utc)} UTC): in 'Jan 5' window? {in_window}"
      f"  | heatmap day bucket: {evt.astimezone(NY()).date()}")
