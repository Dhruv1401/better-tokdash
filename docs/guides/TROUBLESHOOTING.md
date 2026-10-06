# Troubleshooting

Common errors and how to fix them.

## Port already in use (EADDRINUSE)

**Symptom:** `tokdash serve` fails with `OSError: [Errno 10048] Address already in use` or similar.

**Cause:** Another process (often another Tokdash instance) is bound to port 55423.

**Fix:**
```bash
# Windows: find and kill the process
netstat -ano | findstr 55423
taskkill /PID <pid> /F

# macOS/Linux
lsof -i :55423
kill <pid>
```

Or use a different port:
```bash
tokdash serve --port 55424
```

## UsageDatabaseSchemaTooNewError

**Symptom:** `tokdash serve` or `tokdash db status` fails with `UsageDatabaseSchemaTooNewError`.

**Cause:** The usage database was written by a newer version of Tokdash than the one currently running.

**Fix:** Update Tokdash:
```bash
pip install -U tokdash
```

Do NOT delete the database — it contains your full usage history.

## SQLite WAL lock / database is locked

**Symptom:** `tokdash db status` or `tokdash serve` fails with `sqlite3.OperationalError: database is locked`.

**Cause:** Another Tokdash process has the database open in WAL mode.

**Fix:**
1. Close all other Tokdash instances
2. If the error persists, repair the database:
```bash
tokdash db repair
```

**When to use `db resync` vs `db repair`:**
- `tokdash db resync` — rebuilds the database from source files. Use when the database is out of date or missing entries.
- `tokdash db repair` — fixes database corruption. Use when the database is corrupted or has WAL sidecar issues.

## macOS Keychain prompts during Claude profile scans

**Symptom:** macOS shows Keychain consent prompts when Tokdash scans Claude config files.

**Cause:** Tokdash reads Claude config files that macOS protects via Keychain.

**Fix:**
- Grant access when prompted
- Or limit which profiles are scanned:
```bash
export TOKDASH_CLAUDE_PROFILES="profile1,profile2"
```

## WSL2 localhost binding

**Symptom:** Dashboard is accessible from WSL2 but not from Windows browser.

**Cause:** WSL2 has its own localhost, not shared with Windows.

**Fix:**
```bash
# Option 1: bind to all interfaces
tokdash serve --bind 0.0.0.0

# Option 2: SSH port forwarding from Windows
ssh -L 55423:127.0.0.1:55423 <wsl-host>

# Option 3: set the public base path
export TOKDASH_PUBLIC_BASE_PATH="http://<windows-ip>:55423"
```

## Enabling OTel exports for GitHub Copilot

**Symptom:** GitHub Copilot usage is not showing in Tokdash.

**Cause:** Copilot does not write token usage by default.

**Fix:**
```bash
# Windows
set COPILOT_OTEL_FILE_EXPORTER_PATH=%USERPROFILE%\.copilot\otel

# macOS/Linux
export COPILOT_OTEL_FILE_EXPORTER_PATH=~/.copilot/otel
```

Data will be written to `~/.copilot/otel/`.

## Dashboard shows no data / empty state

**Symptom:** Dashboard loads but shows no usage data.

**Cause:** No supported clients found, or usage database is empty.

**Fix:**
1. Run diagnostics:
```bash
tokdash doctor
```
2. Check what's in the database:
```bash
tokdash db status
```
3. If the database is empty, force a sync:
```bash
tokdash db sync
```

## Update check fails

**Symptom:** `tokdash update` or the dashboard update check fails.

**Cause:** No network connectivity, or PyPI is unreachable.

**Fix:**
```bash
# Check network
pip install -U tokdash

# Disable update checks
export TOKDASH_UPDATE_CHECK=0
```

## See also

- [Onboarding guide](ONBOARDING.md) — initial setup and `tokdash doctor`
- [Remote access guide](REMOTE_ACCESS.md) — reaching your instance from another machine
- [Configuration reference](../reference/CONFIG.md) — all environment variables
- [API reference](../reference/API.md) — HTTP API endpoints
