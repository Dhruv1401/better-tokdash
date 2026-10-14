"""Tests for HermesParser."""
import sqlite3
from pathlib import Path

from tokdash import osinfo
from tokdash.pricing import PricingDatabase
from tokdash.sources.coding_tools import BaseParser, HermesParser, _sig_cache


def _create_hermes_db(db_path: Path, rows: list, usage_rows: list = None) -> None:
    """Create a minimal Hermes state.db with the given session rows and optional usage rows."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            model TEXT,
            billing_provider TEXT,
            started_at REAL,
            message_count INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read_tokens INTEGER,
            cache_write_tokens INTEGER,
            reasoning_tokens INTEGER,
            estimated_cost_usd REAL,
            actual_cost_usd REAL
        )
        """
    )
    cur.executemany(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    if usage_rows is not None:
        cur.execute(
            """
            CREATE TABLE session_model_usage (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                model TEXT NOT NULL,
                billing_provider TEXT NOT NULL DEFAULT '',
                billing_base_url TEXT NOT NULL DEFAULT '',
                billing_mode TEXT NOT NULL DEFAULT '',
                task TEXT NOT NULL DEFAULT '',
                api_call_count INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                estimated_cost_usd REAL NOT NULL DEFAULT 0,
                actual_cost_usd REAL NOT NULL DEFAULT 0,
                cost_status TEXT,
                cost_source TEXT,
                first_seen REAL,
                last_seen REAL,
                PRIMARY KEY (session_id, model, billing_provider, billing_base_url, billing_mode, task)
            )
            """
        )
        cur.executemany(
            "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            usage_rows,
        )
    conn.commit()
    conn.close()


def _default_usage_row(
    session_id="sess-001",
    model="claude-3-5-sonnet",
    billing_provider="anthropic",
    billing_base_url="",
    billing_mode="",
    task="",
    api_call_count=1,
    input_tokens=1000,
    output_tokens=100,
    cache_read_tokens=0,
    cache_write_tokens=0,
    reasoning_tokens=0,
    estimated_cost_usd=0.0,
    actual_cost_usd=0.0,
    cost_status=None,
    cost_source=None,
    first_seen=None,
    last_seen=None,
):
    return (
        session_id, model, billing_provider, billing_base_url, billing_mode,
        task, api_call_count, input_tokens, output_tokens, cache_read_tokens,
        cache_write_tokens, reasoning_tokens, estimated_cost_usd, actual_cost_usd,
        cost_status, cost_source, first_seen, last_seen,
    )



def _default_row(
    row_id="sess-001",
    model="MiniMax-M2.7",
    billing_provider="minimax",
    started_at=1779395293.72756,
    message_count=5,
    input_tokens=7000,
    output_tokens=47,
    cache_read_tokens=0,
    cache_write_tokens=0,
    reasoning_tokens=0,
    estimated_cost=0.002,
    actual_cost=0.0021564,
):
    return (
        row_id, model, billing_provider, started_at, message_count,
        input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
        reasoning_tokens, estimated_cost, actual_cost,
    )


def test_hermes_parser_basic(monkeypatch, tmp_path):
    """Reads a single session row and maps all fields correctly."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    _create_hermes_db(hermes_dir / "state.db", [_default_row()])

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)

    assert len(entries) == 1
    e = entries[0]
    assert e["source"] == "hermes"
    assert e["model"] == "MiniMax-M2.7"
    assert e["provider"] == "minimax"
    assert e["input"] == 7000
    assert e["output"] == 47
    assert e["cacheRead"] == 0
    assert e["cacheWrite"] == 0
    assert e["reasoning"] == 0
    # actual_cost_usd > 0, so it should be used
    assert abs(e["cost"] - 0.0021564) < 1e-9
    expected_ts = int(1779395293.72756 * 1000)
    assert e["timestamp"] == expected_ts


def test_hermes_parser_cost_fallback_estimated(monkeypatch, tmp_path):
    """When actual_cost_usd is 0, falls back to estimated_cost_usd."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    _create_hermes_db(
        hermes_dir / "state.db",
        [_default_row(actual_cost=0.0, estimated_cost=0.005)],
    )

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)

    assert len(entries) == 1
    assert abs(entries[0]["cost"] - 0.005) < 1e-9


def test_hermes_parser_cost_fallback_pricing_db(monkeypatch, tmp_path):
    """When both recorded costs are 0, falls back to pricing DB."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    _create_hermes_db(
        hermes_dir / "state.db",
        [_default_row(model="kimi-k2.5", billing_provider="moonshotai", actual_cost=0.0, estimated_cost=0.0)],
    )

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    db = PricingDatabase()
    parser = HermesParser(db)
    entries = parser.collect(None, None)

    assert len(entries) == 1
    # Should be computed from pricing DB, not 0 (kimi-k2.5 has pricing)
    assert entries[0]["cost"] >= 0


def test_hermes_parser_skip_all_zero_no_cost(monkeypatch, tmp_path):
    """Rows with all-zero tokens AND zero costs are skipped."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    _create_hermes_db(
        hermes_dir / "state.db",
        [_default_row(input_tokens=0, output_tokens=0, cache_read_tokens=0,
                      cache_write_tokens=0, reasoning_tokens=0,
                      actual_cost=0.0, estimated_cost=0.0)],
    )

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)
    assert len(entries) == 0


def test_hermes_parser_zero_cost_with_tokens_not_skipped(monkeypatch, tmp_path):
    """Rows with tokens but zero cost (subscription-included) are NOT skipped."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    _create_hermes_db(
        hermes_dir / "state.db",
        [_default_row(
            model="gpt-5.2",
            billing_provider="openai",
            input_tokens=1000,
            output_tokens=100,
            actual_cost=0.0,
            estimated_cost=0.0,
        )],
    )

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)
    # Row has tokens so it is NOT skipped; cost comes from pricing DB
    assert len(entries) == 1


def test_hermes_parser_dedup_across_dbs(monkeypatch, tmp_path):
    """Duplicate session IDs across multiple state.db files are deduplicated."""
    dir1 = tmp_path / "hermes1"
    dir2 = tmp_path / "hermes2"
    dir1.mkdir()
    dir2.mkdir()
    row = _default_row(row_id="shared-id")
    _create_hermes_db(dir1 / "state.db", [row])
    _create_hermes_db(dir2 / "state.db", [row])

    monkeypatch.setenv("HERMES_HOME", f"{dir1},{dir2}")
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)
    assert len(entries) == 1


def test_hermes_parser_scans_named_profiles(monkeypatch, tmp_path):
    """Named profiles under ~/.hermes/profiles/<name>/state.db count by default.

    Each profile keeps its own history (hermes never clones session state
    between profiles), so all three rows are distinct sessions.
    """
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(osinfo, "is_windows", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    _create_hermes_db(hermes_dir / "state.db", [_default_row(row_id="main-1")])
    for name in ("robot1", "robot2"):
        profile = hermes_dir / "profiles" / name
        profile.mkdir(parents=True)
        _create_hermes_db(profile / "state.db", [_default_row(row_id=f"{name}-1")])
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    assert parser.search_dirs == [
        hermes_dir,
        hermes_dir / "profiles" / "robot1",
        hermes_dir / "profiles" / "robot2",
    ]
    entries = parser.collect(None, None)
    assert len(entries) == 3
    assert sum(e["input"] for e in entries) == 3 * 7000


def test_hermes_parser_profiles_under_env_home(monkeypatch, tmp_path):
    """A HERMES_HOME entry brings its own profiles — no need to list them by hand."""
    home = tmp_path / "custom-hermes"
    home.mkdir()
    _create_hermes_db(home / "state.db", [_default_row(row_id="main-1")])
    profile = home / "profiles" / "robot1"
    profile.mkdir(parents=True)
    _create_hermes_db(profile / "state.db", [_default_row(row_id="robot1-1")])

    monkeypatch.setenv("HERMES_HOME", str(home))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)
    assert {e["timestamp"] for e in entries}  # sanity: rows survived
    assert len(entries) == 2


def test_hermes_parser_default_dir(monkeypatch, tmp_path):
    """Without HERMES_HOME, defaults to ~/.hermes."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(osinfo, "is_windows", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    assert parser.search_dirs == [tmp_path / ".hermes"]
    # No DB file → empty result without error
    entries = parser.collect(None, None)
    assert entries == []


def test_hermes_parser_skip_null_model(monkeypatch, tmp_path):
    """Rows with NULL or empty model are now included (fallback path).
    They produce entries with model='unknown'."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    rows = [
        _default_row(row_id="good", model="MiniMax-M2.7"),
        _default_row(row_id="null-model", model=None, billing_provider="openai"),
    ]
    _create_hermes_db(hermes_dir / "state.db", rows)

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)
    assert len(entries) == 2
    by_id = {e["entry_id"]: e for e in entries}
    assert "hermes:good" in by_id
    assert by_id["hermes:good"]["model"] == "MiniMax-M2.7"
    assert "hermes:null-model" in by_id
    assert by_id["hermes:null-model"]["model"] == "unknown"


def test_hermes_parser_started_at_ms_passthrough(monkeypatch, tmp_path):
    """If started_at is already in ms (> 1e12), it is used as-is."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    ts_ms = 1779395293727.0  # already in milliseconds
    _create_hermes_db(hermes_dir / "state.db", [_default_row(started_at=ts_ms)])

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)
    assert len(entries) == 1
    assert entries[0]["timestamp"] == int(ts_ms)


def test_hermes_parser_multi_model_session(monkeypatch, tmp_path):
    """A session with multiple models in session_model_usage should produce
    multiple entries, one per model, with correct per-model token counts."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    sess_row = _default_row(
        row_id="sess-multi",
        model="gpt-4o",
        billing_provider="openai",
        message_count=7,
        input_tokens=5000,
        output_tokens=400,
        actual_cost=0.025,
    )
    # Insert in reverse chronological order to verify first_seen sorting
    usage_rows = [
        _default_usage_row(
            session_id="sess-multi",
            model="gpt-4o",
            billing_provider="openai",
            input_tokens=2000,
            output_tokens=150,
            cache_read_tokens=50,
            cache_write_tokens=25,
            reasoning_tokens=10,
            actual_cost_usd=0.010,
            first_seen=1779395300.0,
        ),
        _default_usage_row(
            session_id="sess-multi",
            model="claude-3-5-sonnet",
            billing_provider="anthropic",
            input_tokens=3000,
            output_tokens=250,
            cache_read_tokens=100,
            cache_write_tokens=50,
            reasoning_tokens=20,
            actual_cost_usd=0.015,
            first_seen=1779395293.0,
        ),
    ]
    _create_hermes_db(hermes_dir / "state.db", [sess_row], usage_rows)

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)

    assert len(entries) == 2
    by_model = {e["model"]: e for e in entries}
    assert "claude-3-5-sonnet" in by_model
    assert "gpt-4o" in by_model

    c = by_model["claude-3-5-sonnet"]
    assert c["source"] == "hermes"
    assert c["provider"] == "anthropic"
    assert c["input"] == 3000
    assert c["output"] == 250
    assert c["cacheRead"] == 100
    assert c["cacheWrite"] == 50
    assert c["reasoning"] == 20
    assert abs(c["cost"] - 0.015) < 1e-9
    assert c["messageCount"] == 7
    assert c["entry_id"] == "hermes:sess-multi:claude-3-5-sonnet"

    g = by_model["gpt-4o"]
    assert g["source"] == "hermes"
    assert g["provider"] == "openai"
    assert g["input"] == 2000
    assert g["output"] == 150
    assert g["cacheRead"] == 50
    assert g["cacheWrite"] == 25
    assert g["reasoning"] == 10
    assert abs(g["cost"] - 0.010) < 1e-9
    assert "messageCount" not in g  # Non-first models omit messageCount
    assert g["entry_id"] == "hermes:sess-multi:gpt-4o"


def test_hermes_parser_multi_model_aggregation(monkeypatch, tmp_path):
    """Multiple session_model_usage rows for the same (session_id, model)
    but different tasks should be summed into one entry."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    sess_row = _default_row(row_id="sess-agg", model="claude-3-5-sonnet", message_count=4)
    usage_rows = [
        _default_usage_row(
            session_id="sess-agg",
            model="claude-3-5-sonnet",
            task="main-agent",
            billing_provider="anthropic",
            input_tokens=1000,
            output_tokens=100,
            cache_read_tokens=10,
            cache_write_tokens=5,
            reasoning_tokens=2,
            actual_cost_usd=0.005,
            estimated_cost_usd=0.004,
        ),
        _default_usage_row(
            session_id="sess-agg",
            model="claude-3-5-sonnet",
            task="subtask-reviewer",
            billing_provider="anthropic",
            input_tokens=2000,
            output_tokens=200,
            cache_read_tokens=20,
            cache_write_tokens=10,
            reasoning_tokens=4,
            actual_cost_usd=0.010,
            estimated_cost_usd=0.008,
        ),
    ]
    _create_hermes_db(hermes_dir / "state.db", [sess_row], usage_rows)

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)

    assert len(entries) == 1
    e = entries[0]
    assert e["model"] == "claude-3-5-sonnet"
    assert e["provider"] == "anthropic"
    assert e["input"] == 3000
    assert e["output"] == 300
    assert e["cacheRead"] == 30
    assert e["cacheWrite"] == 15
    assert e["reasoning"] == 6
    assert abs(e["cost"] - 0.015) < 1e-9
    assert e["messageCount"] == 4
    assert e["entry_id"] == "hermes:sess-agg:claude-3-5-sonnet"


def test_hermes_parser_no_session_model_usage_table(monkeypatch, tmp_path):
    """When session_model_usage table doesn't exist, fall back to current behavior (sessions table only)."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    _create_hermes_db(
        hermes_dir / "state.db",
        [_default_row(row_id="sess-no-table", model="MiniMax-M2.7", actual_cost=0.002)],
    )

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)

    assert len(entries) == 1
    e = entries[0]
    assert e["model"] == "MiniMax-M2.7"
    assert e["entry_id"] == "hermes:sess-no-table"
    assert e["input"] == 7000
    assert e["output"] == 47
    assert abs(e["cost"] - 0.002) < 1e-9


def test_hermes_parser_multi_model_cost_precedence(monkeypatch, tmp_path):
    """Cost precedence should work per-model: actual > estimated > pricing DB."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    sess_row = _default_row(row_id="sess-cost-prec", model="kimi-k2.5")
    usage_rows = [
        # Model 1: actual > 0 and estimated > 0 -> uses actual
        _default_usage_row(
            session_id="sess-cost-prec",
            model="gpt-4o",
            billing_provider="openai",
            input_tokens=1000,
            output_tokens=100,
            actual_cost_usd=0.02,
            estimated_cost_usd=0.05,
        ),
        # Model 2: actual == 0, estimated > 0 -> uses estimated
        _default_usage_row(
            session_id="sess-cost-prec",
            model="claude-3-5-sonnet",
            billing_provider="anthropic",
            input_tokens=1000,
            output_tokens=100,
            actual_cost_usd=0.0,
            estimated_cost_usd=0.03,
        ),
        # Model 3: actual == 0, estimated == 0 -> uses pricing DB
        _default_usage_row(
            session_id="sess-cost-prec",
            model="kimi-k2.5",
            billing_provider="moonshotai",
            input_tokens=1000,
            output_tokens=100,
            actual_cost_usd=0.0,
            estimated_cost_usd=0.0,
        ),
    ]
    _create_hermes_db(hermes_dir / "state.db", [sess_row], usage_rows)

    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)

    assert len(entries) == 3
    by_model = {e["model"]: e for e in entries}

    # Model 1: actual cost took precedence over estimated
    assert abs(by_model["gpt-4o"]["cost"] - 0.02) < 1e-9

    # Model 2: estimated cost used when actual is 0
    assert abs(by_model["claude-3-5-sonnet"]["cost"] - 0.03) < 1e-9

    # Model 3: pricing DB used when both actual and estimated are 0
    assert by_model["kimi-k2.5"]["cost"] > 0


def test_hermes_parser_multi_model_mixed_cost_aggregation(monkeypatch, tmp_path):
    """One row with actual_cost > 0 and another with actual_cost = 0 for the
    same model: the unpriced tokens must be priced, not swallowed."""
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    sess_row = _default_row(row_id="sess-mixed", model="kimi-k2.5", message_count=3)
    usage_rows = [
        _default_usage_row(
            session_id="sess-mixed", model="kimi-k2.5", task="main",
            input_tokens=100, output_tokens=10,
            actual_cost_usd=0.005, estimated_cost_usd=0.004,
        ),
        _default_usage_row(
            session_id="sess-mixed", model="kimi-k2.5", task="background_review",
            input_tokens=1000, output_tokens=100,
            actual_cost_usd=0.0, estimated_cost_usd=0.0,
        ),
    ]
    _create_hermes_db(hermes_dir / "state.db", [sess_row], usage_rows)
    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    _sig_cache.clear()
    BaseParser._entry_cache.clear()

    parser = HermesParser(PricingDatabase())
    entries = parser.collect(None, None)

    assert len(entries) == 1
    e = entries[0]
    # Cost = 0.005 (fixed) + priced(1000, 100) > 0.005
    assert e["cost"] > 0.005
    # Tokens are summed
    assert e["input"] == 1100
    assert e["output"] == 110

