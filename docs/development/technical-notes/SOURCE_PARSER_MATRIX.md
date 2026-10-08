# Source Parser Matrix

This document is a reference for all supported sources and their parsers.

## Summary

- **Total parsers:** 28 (27 in `coding_tools.py` + 1 standalone OpenClaw)
- **Persistent-store parsers:** 22 (17 file_replace + 5 source_replace)
- **Live-query parsers (source_native_db):** 6 (OpenCode, Kilo, Mimo, ZCode, QoderIde, Devin)
- **Session-capable:** 4 (Codex, Claude, DSH, Reasonix)
- **Self-reporting costs:** 4 (Pi Agent via `use_recorded_cost=True`; Hermes, Mimo, Qoder CLI in parse logic)
- **All sources are local-only** — no network-backed usage sources

## Parser inventory

| Parser | Tool | Input format | Discovery | Store mode | Sessions | Own costs | Notes |
|---|---|---|---|---|---|---|---|
| `OpenCodeParser` | OpenCode | SQLite DB | `clientpaths.opencode_db_path()` | source_native_db | No | No | Per-query cache (32 entries) |
| `KiloCodeParser` | Kilo Code | SQLite DB | `clientpaths.kilo_db_paths()` | source_native_db | No | No | Subclass of OpenCodeParser |
| `ClineParser` | Cline | JSON (`.messages.json`) | `clientpaths.cline_data_dir()` | file_replace | No | No | Cache-inclusive input split |
| `CodexParser` | Codex | JSONL (rollout) | `clientpaths.codex_sessions_dir()` | file_replace | Yes | No | session_store=True, fork replay detection |
| `ClaudeParser` | Claude Code | JSONL (streaming) | `clientpaths.claude_project_dirs()` | file_replace | Yes | No | session_store=True, streaming snapshot collapse |
| `GeminiCLIParser` | Gemini CLI | JSON + JSONL | `clientpaths.gemini_chats_json_glob()` | file_replace | No | No | append_jsonl=True |
| `AntigravityCLIParser` | Antigravity | SQLite DB (protobuf) | `clientpaths.antigravity_conversation_dirs()` | file_replace | No | No | Protobuf wire walker |
| `AmpParser` | Amp | — | `clientpaths.amp_root()` | source_replace | No | No | **Placeholder** — emits no rows |
| `KimiParser` | Kimi CLI | JSONL (`wire.jsonl`) | `clientpaths.kimi_roots()` | file_replace | No | No | Two schemas (legacy + Kimi Code) |
| `GrokParser` | Grok Build | JSONL (`unified.jsonl`) | `clientpaths.grok_home() / "logs"` | source_replace | No | No | Pid-keyed model attribution |
| `PiAgentParser` | Pi Agent | JSONL | `clientpaths.pi_agent_search_dirs()` | file_replace | No | Yes | use_recorded_cost=True |
| `OmpParser` | omp (oh-my-pi) | JSONL | `clientpaths.omp_agent_search_dirs()` | file_replace | No | No | Subclass of PiAgentParser |
| `CopilotCLIParser` | GitHub Copilot CLI | OTel JSONL | `clientpaths.copilot_otel_dir()` | source_replace | No | No | Two-source merge (OTel + events.jsonl) |
| `HermesParser` | Hermes | SQLite DB (`state.db`) | `clientpaths.hermes_search_dirs()` | source_replace | No | Yes | actual_cost_usd → estimated_cost_usd |
| `MimoParser` | Mimocode | SQLite DB (`mimocode.db`) | `clientpaths.mimocode_db_path()` | source_native_db | No | Yes | Per-query cache |
| `ZCodeParser` | ZCode | SQLite DB (`db.sqlite`) | `clientpaths.zcode_db_path()` | source_native_db | No | No | WAL mode, temp-dir snapshot |
| `QoderIdeParser` | Qoder IDE | SQLite DB (`local.db`) | `clientpaths.qoder_ide_db_path()` | source_native_db | No | No | Temp-dir snapshot |
| `QoderCliParser` | Qoder CLI | JSONL (transcript + segments) | `clientpaths.qoder_cli_roots()` | source_replace | No | Yes | Two-file merge per request_id |
| `DSHParser` | DeepSeek Harness | JSONL (zstd) | `clientpaths.dsh_sessions_dir()` | file_replace | Yes | No | session_store=True, shared decoder |
| `ReasonixParser` | Reasonix | JSONL (daily stats) | `clientpaths.reasonix_stats_dir()` | file_replace | Yes | No | session_store=True, content-keyed dedup |
| `WorkBuddyParser` | WorkBuddy | JSONL | `clientpaths.workbuddy_roots()` | file_replace | No | No | append_jsonl=True |
| `ZedParser` | Zed | SQLite DB (`threads.db`) | `clientpaths.zed_threads_db()` | file_replace | No | No | One entry per thread |
| `QwenCodeParser` | Qwen Code | JSONL | `clientpaths.qwen_chat_files()` | file_replace | No | No | append_jsonl=True, global uuid fold |
| `CrushParser` | Charm Crush | SQLite DB (`crush.db`) | `clientpaths.crush_data_dirs()` | file_replace | No | No | WAL snapshot |
| `MiniMaxCodeParser` | MiniMax Code | JSONL (`messages.jsonl`) | `clientpaths.minimax_code_session_files()` | file_replace | No | No | append_jsonl=True |
| `DevinParser` | Devin CLI | SQLite DB (`sessions.db`) | `clientpaths.devin_db_paths()` | source_native_db | No | No | WAL snapshot for drvfs/UNC |
| `MuseParser` | Meta Muse Code | JSONL (`session.jsonl`) | `clientpaths.muse_session_files()` | file_replace | No | No | cross-file stable-key ownership |
| `FreebuffParser` | Freebuff Desktop | SQLite DB (`desktop-v2.db`) | `clientpaths.freebuff_desktop_db_paths()` | file_replace | No | No | Two tables (messages + receipts) |

## OpenClaw (standalone)

OpenClaw is NOT a `BaseParser` subclass. It has its own corpus cache and store sync:

- **Input format:** JSONL session transcripts
- **Discovery:** `clientpaths.openclaw_agent_sessions_glob()`
- **Store mode:** Persistent store with signature-based sync
- **Session-capable:** Yes
- **Own costs:** Yes (pricing DB wins, OpenClaw's recorded cost is fallback)
- **Special:** File-signature corpus cache (max 8), `OPENCLAW_PARSER_VERSION=2`

## Sync modes

### file_replace

Unchanged files stay indexed; changed files reparsed. Stored in `usage_entries` table. This is the most common mode (22 parsers).

### source_replace

Source-wide replacement required for correctness. Stored in `usage_entries` table. Used by sources where cross-file dedup is needed (e.g., Grok, Copilot CLI, Qoder CLI).

### source_native_db

Queried live from source DB; never copied into `usage_entries`. `persistent_parser_version = None`. Used by 6 parsers (OpenCode, Kilo, Mimo, ZCode, QoderIde, Devin).

## Cost sources

Sources that report their own costs:

| Source | Cost field | Authoritative | Notes |
|---|---|---|---|
| Pi Agent | `usage.cost.total` | Yes, when positive | Fallback to pricing DB |
| Hermes | `actual_cost_usd`, `estimated_cost_usd` | Yes, when positive | Fallback to pricing DB |
| Mimicode | `data.cost` | Yes, when positive | Fallback to pricing DB |
| Qoder CLI | credits | Yes, converted to USD | Fallback to pricing DB |
| OpenClaw | `usage.cost` / `usage.totalCost` | Fallback only | Pricing DB wins |

## Session-capable sources

4 sources populate the `session_records` table (`session_store=True`):

- **Codex** — JSONL rollout files
- **Claude Code** — JSONL streaming snapshots
- **DeepSeek Harness** — JSONL (zstd-compressed)
- **Reasonix** — JSONL (daily stats)

In addition, `sessions.py` handles 5 stored session tools: Codex, Claude, Kimi, DSH, and Reasonix.

## Placeholder parsers

`AmpParser` is a placeholder — it emits no rows until a stable schema is available.
