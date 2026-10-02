"""Tests for FreebuffParser: Freebuff Desktop's per-project ``desktop-v2.db``
stores.

Pins the accounting conventions verified against four live stores and the
shipped orchestrator bundle:

* one entry per ``role='assistant'`` row that carries a non-zero ``usage``;
* ``cachedInputTokens`` is a SUBSET of ``inputTokens`` (cache-inclusive
  prompt) and is split into its own bucket;
* ``reasoningOutputTokens`` is a SUBSET of ``outputTokens`` and is split out;
* ``cacheWrite`` is zero by construction;
* ``costUsd`` is never read — cost is pricing-DB only;
* ``threads.model`` splits once on ``/`` into (provider, model), and an opaque
  ``m-<hex>`` handle keeps provider "" and prices at 0.00;
* milliseconds timestamps;
* the store is read through the WAL snapshot helper (live rows sit in -wal);
* every project DB is unioned, and ``entry_id`` is source-global.
"""
import json
import sqlite3
from pathlib import Path

from tokdash import clientpaths
from tokdash.pricing import PricingDatabase
from tokdash.sources import coding_tools as ct
from tokdash.sources.coding_tools import (
    BaseParser,
    CodingToolsUsageTracker,
    FreebuffParser,
    _sig_cache,
)

# 2026-10-02T13:04:12.181Z — a live row's timestamp, milliseconds.
TS_MS = 1_790_924_652_181
MODEL_QUALIFIED = "z-ai/glm-5.3-flash"
MODEL_HANDLE = "m-22ff70c712"

# The real store's schema, trimmed to the columns the parser reads. The
# message table's ``seq`` is AUTOINCREMENT in the shipped schema, which is what
# makes the dedup key stable; keep it that way here.
_THREADS_DDL = """
CREATE TABLE threads (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  project_path TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT 'New thread',
  model TEXT,
  harness_id TEXT,
  agent_mode TEXT NOT NULL DEFAULT 'build',
  created_at INTEGER NOT NULL
)
"""

_MESSAGES_DDL = """
CREATE TABLE messages (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  request_id TEXT,
  input_id TEXT,
  role TEXT NOT NULL,
  parts_json TEXT NOT NULL DEFAULT '[]',
  attachments_json TEXT NOT NULL DEFAULT '[]',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  ts INTEGER NOT NULL
)
"""


def _metrics(
    *,
    input_tokens=0,
    cached_input=0,
    output_tokens=0,
    reasoning=0,
    cost_usd=0,
):
    """A ``metrics_json`` payload in the store's own shape.

    ``totalTokens`` is written as ``inputTokens + outputTokens`` because that
    identity held on every live row — it is what establishes that the cached
    share sits INSIDE input.
    """
    return json.dumps({
        "context": {"usedTokens": input_tokens + output_tokens},
        "compactions": [],
        "usage": {
            "inputTokens": input_tokens,
            "cachedInputTokens": cached_input,
            "outputTokens": output_tokens,
            "reasoningOutputTokens": reasoning,
            "totalTokens": input_tokens + output_tokens,
        },
        "costUsd": cost_usd,
    })


def _make_db(
    project_dir: Path,
    *,
    thread_id="t1",
    model=MODEL_QUALIFIED,
    messages=(),
    checkpoint=True,
) -> Path:
    """Create one project's ``desktop-v2.db``.

    ``messages`` is a sequence of ``(role, metrics_json, ts)``; ``None`` for
    metrics writes the column default ``'{}'`` (the shipped column is
    ``TEXT NOT NULL DEFAULT '{}'``, so a message without usage still holds an
    object, never SQL NULL). ``checkpoint=False`` leaves the rows in the WAL
    (never truncating it) so the snapshot path is exercised for real.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    db = project_dir / "desktop-v2.db"
    conn = sqlite3.connect(db)
    try:
        # The shipped store is WAL-mode; match it so the -wal semantics the
        # parser relies on are real.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_THREADS_DDL)
        conn.execute(_MESSAGES_DDL)
        conn.execute(
            "INSERT INTO threads (id, project_id, project_path, title, model, "
            "harness_id, agent_mode, created_at) VALUES (?, 'p1', ?, 'T', ?, "
            "'codebuff', 'build', ?)",
            (thread_id, str(project_dir), model, TS_MS),
        )
        for role, metrics_json, ts in messages:
            conn.execute(
                "INSERT INTO messages (thread_id, role, metrics_json, ts) "
                "VALUES (?, ?, ?, ?)",
                (thread_id, role, metrics_json if metrics_json is not None else "{}", ts),
            )
        conn.commit()
        if checkpoint:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    return db


def _fresh(monkeypatch, tmp_path) -> FreebuffParser:
    """A parser rooted at a fake home, with both caches cleared."""
    _sig_cache.clear()
    BaseParser._entry_cache.clear()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return FreebuffParser(PricingDatabase())


def _projects(tmp_path) -> Path:
    return tmp_path / ".config" / "freebuff-desktop" / "projects"


# --- path resolution --------------------------------------------------------


def test_home_and_db_paths_are_derived_from_home(monkeypatch, tmp_path):
    _sig_cache.clear()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert clientpaths.freebuff_desktop_home() == (
        tmp_path / ".config" / "freebuff-desktop"
    )
    _make_db(_projects(tmp_path) / "proj-a-11111111")
    _make_db(_projects(tmp_path) / "proj-b-22222222")
    # Sorted, and only real desktop-v2.db files.
    (_projects(tmp_path) / "proj-c-33333333").mkdir(parents=True)
    paths = clientpaths.freebuff_desktop_db_paths()
    assert [p.parent.name for p in paths] == ["proj-a-11111111", "proj-b-22222222"]


def test_no_projects_dir_yields_nothing(monkeypatch, tmp_path):
    parser = _fresh(monkeypatch, tmp_path)
    assert parser._file_signatures() == ()
    assert parser._parse_all() == []


# --- core accounting --------------------------------------------------------


def test_cache_is_split_out_of_input(monkeypatch, tmp_path):
    """``cachedInputTokens`` sits inside ``inputTokens``; split, never add."""
    _make_db(
        _projects(tmp_path) / "p1",
        messages=[
            ("user", None, TS_MS),
            ("assistant", _metrics(input_tokens=1000, cached_input=900,
                                   output_tokens=50), TS_MS + 1),
        ],
    )
    entries = _fresh(monkeypatch, tmp_path)._parse_all()

    assert len(entries) == 1
    e = entries[0]
    # 1000 total input, 900 of it cached -> 100 fresh, 900 cacheRead.
    assert (e["input"], e["cacheRead"]) == (100, 900)
    assert e["input"] + e["cacheRead"] == 1000  # conserved, not doubled
    assert (e["output"], e["cacheWrite"], e["reasoning"]) == (50, 0, 0)


def test_reasoning_is_split_out_of_output(monkeypatch, tmp_path):
    """``reasoningOutputTokens`` is a subset of output; compute.py adds it on
    top for display, so it must be removed from output here."""
    _make_db(
        _projects(tmp_path) / "p1",
        messages=[
            ("assistant", _metrics(output_tokens=1000, reasoning=400), TS_MS),
        ],
    )
    entries = _fresh(monkeypatch, tmp_path)._parse_all()

    e = entries[0]
    assert (e["output"], e["reasoning"]) == (600, 400)
    assert e["output"] + e["reasoning"] == 1000


def test_model_splits_once_into_provider_and_model(monkeypatch, tmp_path):
    _make_db(
        _projects(tmp_path) / "p1",
        model=MODEL_QUALIFIED,
        messages=[("assistant", _metrics(input_tokens=10, output_tokens=5), TS_MS)],
    )
    e = _fresh(monkeypatch, tmp_path)._parse_all()[0]
    assert (e["provider"], e["model"]) == ("z-ai", "glm-5.3-flash")
    # The priced model is what the pricing DB can resolve.
    assert e["cost"] == PricingDatabase().get_cost("glm-5.3-flash", 10, 5, 0, 0)
    assert e["cost"] > 0


def test_second_slash_stays_in_the_model(monkeypatch, tmp_path):
    _make_db(
        _projects(tmp_path) / "p1",
        model="vendor/family/model-x",
        messages=[("assistant", _metrics(input_tokens=1, output_tokens=1), TS_MS)],
    )
    e = _fresh(monkeypatch, tmp_path)._parse_all()[0]
    assert (e["provider"], e["model"]) == ("vendor", "family/model-x")


def test_opaque_handle_keeps_no_provider_and_prices_at_zero(monkeypatch, tmp_path):
    """The catalog handle form ``m-<hex>`` is opaque and rotates per account;
    its mapping is server-side and never written to disk, so it cannot be
    resolved offline. The row still counts its tokens."""
    _make_db(
        _projects(tmp_path) / "p1",
        model=MODEL_HANDLE,
        messages=[
            ("assistant", _metrics(input_tokens=5000, cached_input=4000,
                                   output_tokens=200), TS_MS),
        ],
    )
    e = _fresh(monkeypatch, tmp_path)._parse_all()[0]

    assert e["provider"] == ""
    assert e["model"] == MODEL_HANDLE
    assert e["cost"] == 0.0
    # Tokens are still fully counted despite the unpriced model.
    assert (e["input"], e["cacheRead"], e["output"]) == (1000, 4000, 200)


def test_cost_usd_is_never_read(monkeypatch, tmp_path):
    """The store writes ``costUsd`` (always 0 on the free tier); a non-zero
    value there must not become the row's cost."""
    _make_db(
        _projects(tmp_path) / "p1",
        model=MODEL_QUALIFIED,
        messages=[
            ("assistant", _metrics(input_tokens=1_000_000, output_tokens=0,
                                   cost_usd=999.0), TS_MS),
        ],
    )
    e = _fresh(monkeypatch, tmp_path)._parse_all()[0]
    expected = PricingDatabase().get_cost("glm-5.3-flash", 1_000_000, 0, 0, 0)
    assert e["cost"] == expected
    assert e["cost"] != 999.0


# --- row selection ----------------------------------------------------------


def test_only_assistant_rows_with_usage_count(monkeypatch, tmp_path):
    _make_db(
        _projects(tmp_path) / "p1",
        messages=[
            ("user", None, TS_MS),
            ("assistant", _metrics(input_tokens=10, output_tokens=5), TS_MS + 1),
            ("user", None, TS_MS + 2),
            # An assistant row with no usage object at all.
            ("assistant", json.dumps({"context": {}}), TS_MS + 3),
            # An all-zero usage object: a cancelled/errored turn.
            ("assistant", _metrics(), TS_MS + 4),
            ("assistant", _metrics(input_tokens=7, output_tokens=3), TS_MS + 5),
        ],
    )
    entries = _fresh(monkeypatch, tmp_path)._parse_all()
    assert len(entries) == 2
    assert [e["timestamp"] for e in entries] == [TS_MS + 1, TS_MS + 5]


def test_unparsable_metrics_is_skipped(monkeypatch, tmp_path):
    _make_db(
        _projects(tmp_path) / "p1",
        messages=[
            ("assistant", "{not json", TS_MS),
            ("assistant", "[]", TS_MS + 1),
            ("assistant", _metrics(input_tokens=1, output_tokens=1), TS_MS + 2),
        ],
    )
    entries = _fresh(monkeypatch, tmp_path)._parse_all()
    assert len(entries) == 1
    assert entries[0]["timestamp"] == TS_MS + 2


def test_non_positive_timestamp_is_skipped(monkeypatch, tmp_path):
    _make_db(
        _projects(tmp_path) / "p1",
        messages=[
            ("assistant", _metrics(input_tokens=1, output_tokens=1), 0),
            ("assistant", _metrics(input_tokens=2, output_tokens=2), TS_MS),
        ],
    )
    entries = _fresh(monkeypatch, tmp_path)._parse_all()
    assert [e["timestamp"] for e in entries] == [TS_MS]


# --- identity ---------------------------------------------------------------


def test_entry_id_is_thread_scoped_and_stable(monkeypatch, tmp_path):
    _make_db(
        _projects(tmp_path) / "p1",
        thread_id="thread-abc",
        messages=[
            ("assistant", _metrics(input_tokens=1, output_tokens=1), TS_MS),
            ("assistant", _metrics(input_tokens=2, output_tokens=2), TS_MS + 1),
        ],
    )
    parser = _fresh(monkeypatch, tmp_path)
    first = parser._parse_all()
    assert [e["entry_id"] for e in first] == [
        "freebuff:thread-abc:1",
        "freebuff:thread-abc:2",
    ]
    # Re-reading the same store yields the same keys, so nothing re-bills.
    assert [e["entry_id"] for e in parser._parse_all()] == [
        "freebuff:thread-abc:1",
        "freebuff:thread-abc:2",
    ]


def test_projects_are_unioned(monkeypatch, tmp_path):
    """Each project is a disjoint store; all of them are real usage."""
    _make_db(
        _projects(tmp_path) / "p1",
        thread_id="t-a",
        messages=[("assistant", _metrics(input_tokens=10, output_tokens=1), TS_MS)],
    )
    _make_db(
        _projects(tmp_path) / "p2",
        thread_id="t-b",
        messages=[("assistant", _metrics(input_tokens=20, output_tokens=2), TS_MS + 1)],
    )
    entries = _fresh(monkeypatch, tmp_path)._parse_all()

    assert len(entries) == 2
    assert sum(e["input"] for e in entries) == 30
    # Entry keys are source-global, so the two projects cannot collide.
    assert len({e["entry_id"] for e in entries}) == 2


# --- WAL --------------------------------------------------------------------


def test_rows_left_in_the_wal_are_read(monkeypatch, tmp_path):
    """The desktop app holds the store open; live rows sit in the -wal. A
    read-only open in place would miss them, so the snapshot path is used.

    SQLite checkpoints and removes the -wal when its last connection closes,
    so the writer connection is deliberately held open here — that is exactly
    the state the running app leaves the store in.
    """
    project = _projects(tmp_path) / "p1"
    project.mkdir(parents=True, exist_ok=True)
    db = project / "desktop-v2.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_THREADS_DDL)
        conn.execute(_MESSAGES_DDL)
        conn.execute(
            "INSERT INTO threads (id, project_id, project_path, title, model, "
            "harness_id, agent_mode, created_at) VALUES ('t1', 'p1', ?, 'T', ?, "
            "'codebuff', 'build', ?)",
            (str(project), MODEL_QUALIFIED, TS_MS),
        )
        conn.execute(
            "INSERT INTO messages (thread_id, role, metrics_json, ts) "
            "VALUES ('t1', 'assistant', ?, ?)",
            (_metrics(input_tokens=42, output_tokens=8), TS_MS),
        )
        conn.commit()

        # The writer is still open: the rows are in the -wal, not the main db.
        assert (project / "desktop-v2.db-wal").exists()

        entries = _fresh(monkeypatch, tmp_path)._parse_all()
        assert len(entries) == 1
        assert entries[0]["input"] == 42
    finally:
        conn.close()


def test_read_never_creates_sidecars_in_the_source_tree(monkeypatch, tmp_path):
    """The reader must not write into the user's store directory: the -shm is
    the WAL coordination file, and a read-only open in place would create it."""
    project = _projects(tmp_path) / "p1"
    project.mkdir(parents=True, exist_ok=True)
    db = project / "desktop-v2.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_THREADS_DDL)
        conn.execute(_MESSAGES_DDL)
        conn.execute(
            "INSERT INTO threads (id, project_id, project_path, title, model, "
            "harness_id, agent_mode, created_at) VALUES ('t1', 'p1', ?, 'T', ?, "
            "'codebuff', 'build', ?)",
            (str(project), MODEL_QUALIFIED, TS_MS),
        )
        conn.execute(
            "INSERT INTO messages (thread_id, role, metrics_json, ts) "
            "VALUES ('t1', 'assistant', ?, ?)",
            (_metrics(input_tokens=9, output_tokens=1), TS_MS),
        )
        conn.commit()

        before = sorted(p.name for p in project.iterdir())
        entries = _fresh(monkeypatch, tmp_path)._parse_all()
        after = sorted(p.name for p in project.iterdir())

        assert len(entries) == 1
        assert before == after
    finally:
        conn.close()


def test_a_corrupt_db_does_not_blank_the_others(monkeypatch, tmp_path):
    good = _make_db(
        _projects(tmp_path) / "p-good",
        messages=[("assistant", _metrics(input_tokens=5, output_tokens=5), TS_MS)],
    )
    bad = _projects(tmp_path) / "p-bad" / "desktop-v2.db"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"this is not a sqlite database at all")

    entries = _fresh(monkeypatch, tmp_path)._parse_all()
    assert len(entries) == 1
    assert good.exists()


# --- registry ---------------------------------------------------------------


def test_registered_and_declares_capabilities():
    tracker = CodingToolsUsageTracker()
    assert isinstance(tracker.parsers["freebuff"], FreebuffParser)
    parser = tracker.parsers["freebuff"]
    assert parser.sync_capability.mode == "file_replace"
    assert parser.sync_capability.append_jsonl is False
    assert parser.sync_capability.session_store is False
    # Stored persistently, so it must declare an identity (the registry test
    # in test_usage_cache_identity enforces the same rule globally).
    assert parser.persistent_parser_version == 1
    assert parser.persistent_parser_signature()["object"].endswith("FreebuffParser")


def test_billing_record_is_priceable(monkeypatch, tmp_path):
    _make_db(
        _projects(tmp_path) / "p1",
        model=MODEL_QUALIFIED,
        messages=[
            ("assistant", _metrics(input_tokens=1000, cached_input=400,
                                   output_tokens=100), TS_MS),
        ],
    )
    e = _fresh(monkeypatch, tmp_path)._parse_all()[0]
    billing = e["_billing"]
    assert billing["kind"] == "pricing"
    # Both the bare and the qualified id are candidates, so a repricing pass
    # resolves whichever key the DB carries.
    assert "glm-5.3-flash" in billing["models"]
    assert "z-ai/glm-5.3-flash" in billing["models"]
    # Billing uses the FULL output (reasoning stays billed at the output rate)
    # and the disjoint fresh-input/cache split.
    assert billing["input"] == 600
    assert billing["output"] == 100
    assert billing["cache_read"] == 400
    assert billing["cache_write"] == 0
    assert ct.usage_entry_cost(billing, PricingDatabase()) == e["cost"]
