# Tokdash Companion 1.1.0

A feature release for both tray apps. The flyout now reads the calendar instead
of three fixed buckets, the multi-server settings speak the dashboard's
host-and-address language, and the settings window on each platform was rebuilt
around the controls it actually needs.

## Changes

- **Calendar periods.** The period segment is `Day / Week / Month / Year` and
  each one is a calendar-aligned window: this week, this month, the year to
  date. The arrows step to the previous and next window, and every window
  carries its own tokens, cost, estimated active time and comparison against the
  equal window before it, plus per-server rows when more than one server is
  enabled. The selected period persists. The day segment now reads `Day` on both
  platforms.
- **Instant navigation.** An arrow click updates the selected date and draws the
  loading placeholders at once instead of waiting on the round trip, and a
  refresh that was cancelled by a newer one can no longer land on top of it.
- **Activity glance.** An optional strip under the hero: 24 hourly bars for
  today, a per-day histogram for the week, and the contribution grid for month
  and year. With several servers enabled each contributes its own series. Every
  face is optional — a source the connected server does not serve hides that
  face rather than drawing a zero.
- **Configurable rankings.** Choose how many top-tool and top-model rows the
  flyout prints. macOS gets a slider in Settings, Windows a slim slider in the
  same place.
- **Reset credits, both providers.** Codex credit expiry as before, and Claude
  Code limit resets, which arrive from the server as of Tokdash 2.6.3. The
  notice stays on one line and scrolls in its own viewport when it overflows;
  reduced-motion settings stop the scroll and keep the full text as a tooltip.
- **Provider and tool marks.** Ranked rows wear the agent's own mark.
- **Servers group by host.** Settings keeps one entry per machine and gives it a
  row per address, each with its own reachability and latency, automatic or
  preferred routing, and failover that moves only once the next address proves
  the same daemon identity. Two addresses of one live Tokdash contribute their
  usage once, and **Open Dashboard** follows the address that is actually
  serving. Existing single-address settings migrate unchanged, and servers that
  do not identify themselves stay supported as single-address hosts.
- **Settings rebuilt.** macOS: the window opens taller within the visible
  screen, rank rows use a slider, and an enabled switch stays blue while it is
  off. Windows: rounded fields and buttons, blue switches, compact dropdowns, a
  clear primary **Save**, and a six-pixel rounded scrollbar thumb with a larger
  hit area shared with the quota lists. Keyboard focus and high-contrast colours
  are preserved.
- **A tighter Mac flyout.** Fixed-width scrolling date label that stays inside
  the panel, closer section spacing, and no freshness/Quit footer — **Quit**
  remains in the flyout's right-click menu.
- **Fixed:** an optimised macOS build could report a reachable server as
  unreachable in a multi-server setup. Concurrent health responses now survive
  the optimised refresh.

## Server compatibility

The companion still works against Tokdash `1.5.2` or newer. Four surfaces light
up only against newer servers, and each hides itself when the connected server
is older rather than showing a zero:

| Feature | Needs Tokdash |
|---|---|
| Activity glance (today, week) | `2.5.0` |
| Contribution grid (month, year) | `2.5.0` |
| Per-account quota attribution | `2.5.3` |
| Claude Code limit resets | `2.6.3` |

Update checks remain optional. They never download or install software;
**View update** opens the validated Tokdash GitHub release page in the default
browser.

## Important: unsigned binaries

These binaries are **not code signed**. GitHub hosting and `SHA256SUMS` verify
the downloaded files against this release, but they do not establish an
operating-system-trusted publisher.

- macOS Gatekeeper will warn that Apple cannot verify the developer. If you
  trust this repository and the checksum, Control-click the app, choose
  **Open**, and confirm **Open**.
- Windows SmartScreen may show an unknown-publisher warning. If you trust this
  repository and the checksum, choose **More info**, then **Run anyway**.
- Do not download these binaries from mirrors or third-party sites.

The Microsoft Store build is signed by the Store during certification and is not
covered by this policy.

## Assets

- `Tokdash-Companion-1.1.0-macos-universal-unsigned.dmg` supports Apple Silicon
  and Intel Macs on macOS 14 or newer.
- `Tokdash-Companion-1.1.0-windows-x64-unsigned.zip` is a self-contained Windows
  11 x64 portable build. Windows 11 on Arm may run it through x64 emulation.
- `SHA256SUMS` covers both downloadable binaries.

To update on macOS, quit Tokdash Companion, open the DMG, drag the app to
Applications, and choose **Replace**. To update the portable Windows build,
disable launch at login, quit, replace the extracted directory, and re-enable
it. Existing settings migrate automatically, including the new per-host server
grouping.

The companion has no telemetry, credential discovery, or port scanning. It
connects only to Tokdash endpoints configured by the user and, for manual or
opted-in update checks, GitHub's public releases API.
