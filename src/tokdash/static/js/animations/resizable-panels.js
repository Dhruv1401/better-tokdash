/**
 * TokDash v4 Animation System - Resizable Sessions Explorer columns
 *
 * Discovery: Sessions Explorer has no side pane to drag between. Each tool is a
 * `<details>` whose body stacks a KPI card row *above* one wide session table
 * (`.session-panel { display: block }`), and every one of those tables is a
 * fixed-layout table whose column widths are declared in a real `<colgroup>`
 * (`table-layout: fixed`, widths as percentages). The honest split the markup
 * already carries is therefore the column groups themselves: drag the gap
 * between two adjacent columns and resize exactly those two.
 *
 * Where the divider lives, and why:
 *   - NOT inside `<th>`. The app's `applyI18n()` assigns `textContent` to every
 *     `[data-i18n]` element on every language change, which destroys child
 *     nodes (it already has to re-create `.sort-arrow` for the same reason).
 *   - NOT inside `<table>`/`<thead>`/`<tr>`. A non-row child of a table is
 *     wrapped in an anonymous cell and would shift the layout.
 *   - So it goes in the `.overflow-x-auto` wrapper the table already sits in,
 *     which also keeps it outside the table's sort handlers entirely.
 *
 * Why widths are percentages and not pixels: the pair's declared total is
 * constant, so writing `left + right = pair` back leaves every other column
 * byte-identical — neighbors cannot move — and the values survive a window
 * resize without measuring anything. The divider's own `left` is a percentage
 * of that same width, so positioning needs no measurement either; only its
 * height and the ARIA pixel values are measured, and only while the panel is
 * actually on screen.
 *
 * When handles exist — one path, not two: Sessions Explorer stacks 21 collapsed
 * tables behind 21 `<details>` handles, and only the open panel is ever visible
 * or in the tab order, so nothing is built eagerly. `mountResizablePanels`
 * claims each table's `<details>` with the open/close hook and mounts only the
 * panels that are on screen; every other panel gets its handles the moment it
 * opens, through the same idempotent `ensureMounted`, and loses them when it
 * closes. The `mounted` map is the single owner of live handle state: a table
 * that is not in the map has no handles, no listeners and no residue in the
 * DOM, and repeated open/close builds exactly one set. The handle also carries
 * the "Drag to resize columns" hint through the shared tooltip primitive, and
 * is detached from it on release — a closed panel has no tooltip attachment
 * either.
 *
 * Without PointerEvents, or with fewer than two columns, the module binds
 * nothing and the table is exactly what the app already renders.
 */

import { attachTooltip, detachTooltip } from './tooltip.js';

const STORAGE_KEY = 'tokdash-sessions-split';
const WRAP_CLASS = 'tokdash-col-wrap';

const MIN_PX = 56;
const MAX_PX = 900;
const KEY_STEP_PX = 12;

const DRAG_TRANSITION = 'none';
const KEY_TRANSITION = 'width var(--t-med) cubic-bezier(.16, 1, .3, 1)';

/**
 * The one owner of live handle state: table -> the divider states it owns.
 * Absent from this map means "closed panel": nothing mounted, nothing listening.
 * `watched` only remembers whose `<details>` already carries the open/close
 * hook so mounting twice never wires it twice; it holds no handle state.
 */
const mounted = new Map();
const watched = new WeakSet();

function prefersReducedMotion() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function tableWidth(table) {
  if (!table || typeof table.getBoundingClientRect !== 'function') return 0;
  const rect = table.getBoundingClientRect();
  const width = rect ? rect.width : 0;
  return Number.isFinite(width) && width > 0 ? width : 0;
}

function clamp01(r) {
  return Number.isFinite(r) ? Math.min(1, Math.max(0, r)) : 0;
}

function round4(n) {
  return Math.round(n * 10000) / 10000;
}

function fmt(n) {
  return String(round4(n));
}

/** The declared width of a `<col>`, or null when the markup is not a percentage. */
function readPct(col) {
  const style = col && col.style;
  const raw = style && typeof style.width === 'string' ? style.width.trim() : '';
  if (!raw || raw[raw.length - 1] !== '%') return null;
  const value = parseFloat(raw);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/**
 * Achievable [low, high] left-column width in px for a pair totalling `pairPx`.
 *
 * MIN_PX is a floor on both sides. MAX_PX caps one side, which is only
 * satisfiable while the pair is at most `2 * MAX_PX` wide; past that the cap is
 * dropped rather than inverting the interval. If the pair is too narrow to give
 * both sides their minimum, it settles at the midpoint.
 */
function leftPxBounds(pairPx) {
  if (!Number.isFinite(pairPx) || pairPx <= 0) return [0, 0];
  let low = MIN_PX;
  let high = pairPx - MIN_PX;
  if (pairPx <= 2 * MAX_PX) {
    low = Math.max(low, pairPx - MAX_PX);
    high = Math.min(high, MAX_PX);
  }
  if (low > high) {
    const mid = pairPx / 2;
    return [mid, mid];
  }
  return [low, high];
}

function clampLeftPx(leftPx, pairPx) {
  const [low, high] = leftPxBounds(pairPx);
  return Math.min(Math.max(leftPx, low), high);
}

// --- Persistence -----------------------------------------------------------
// One JSON object under a `tokdash-`-style key, mirroring the overview toggle.
// Storage is best-effort: an unavailable localStorage degrades to "resizes do
// not survive a reload" and never breaks the drag.

let storageCache = null;

function storage() {
  if (storageCache) return storageCache;
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
    const parsed = raw ? JSON.parse(raw) : null;
    storageCache = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch (_) {
    storageCache = {};
  }
  return storageCache;
}

function writeStorage() {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(storage()));
    }
  } catch (_) { /* resize still works, it just will not be remembered */ }
}

function storedKey(panel, index) {
  return `sessions-split:${panel}:col:${index}-${index + 1}`;
}

function readStored(panel, index) {
  const value = storage()[storedKey(panel, index)];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function writeStored(panel, index, ratio) {
  storage()[storedKey(panel, index)] = round4(ratio);
  writeStorage();
}

function clearStored(panel, index) {
  delete storage()[storedKey(panel, index)];
  writeStorage();
}

// --- State -----------------------------------------------------------------

function declaredRatio(st) {
  return st.pairPct > 0 ? st.declaredLeft / st.pairPct : 0.5;
}

function pairPxOf(st) {
  return st.pairPct / 100 * tableWidth(st.table);
}

function setTransition(st, value) {
  st.left.style.transition = value;
  st.right.style.transition = value;
}

function positionDivider(st) {
  const ratio = st.ratio == null ? declaredRatio(st) : st.ratio;
  st.divider.style.left = fmt(st.basePct + st.pairPct * ratio) + '%';
}

function syncAria(st) {
  const pairPx = pairPxOf(st);
  if (!pairPx) {
    st.divider.removeAttribute('aria-valuenow');
    return;
  }
  const [low, high] = leftPxBounds(pairPx);
  const ratio = st.ratio == null ? declaredRatio(st) : st.ratio;
  st.divider.setAttribute('aria-valuemin', String(Math.round(low)));
  st.divider.setAttribute('aria-valuemax', String(Math.round(high)));
  st.divider.setAttribute('aria-valuenow', String(Math.round(clampLeftPx(ratio * pairPx, pairPx))));
}

/** The column's own header text, minus any sort arrow glyph. */
function headerLabel(th) {
  if (!th) return 'column';
  const text = (th.textContent || '').replace(/[▲▼]/g, ' ').replace(/\s+/g, ' ').trim();
  return text || 'column';
}

function refreshLabel(st) {
  st.divider.setAttribute(
    'aria-label',
    `Resize ${headerLabel(st.leftTh)} and ${headerLabel(st.rightTh)} columns`
  );
}

/**
 * Write `ratio` back into the two columns, clamped against the pixel bounds.
 *
 * The pair total is preserved exactly (right = pair - left after rounding), so
 * every other column keeps the width it declared and nothing beside the divider
 * moves by a single pixel.
 */
function applyRatio(st, ratio) {
  const pairPx = pairPxOf(st);
  let next = clamp01(ratio);
  if (pairPx > 0) next = clampLeftPx(next * pairPx, pairPx) / pairPx;
  st.ratio = next;

  const leftPct = round4(st.pairPct * next);
  st.left.style.width = fmt(leftPct) + '%';
  st.right.style.width = fmt(round4(st.pairPct - leftPct)) + '%';

  positionDivider(st);
  syncAria(st);
}

/** Double-click / Escape: forget the split and put the declared widths back. */
function resetSplit(st) {
  clearStored(st.panel, st.index);
  setTransition(st, prefersReducedMotion() ? 'none' : KEY_TRANSITION);
  st.ratio = declaredRatio(st);
  st.left.style.width = fmt(st.declaredLeft) + '%';
  st.right.style.width = fmt(st.declaredRight) + '%';
  positionDivider(st);
  syncAria(st);
}

// --- Gesture handlers ------------------------------------------------------

function stateOf(element) {
  return element && element.__rp ? element.__rp : null;
}

function onPointerDown(event) {
  const st = stateOf(event.currentTarget);
  if (!st) return;
  if (event.pointerType !== 'touch' && event.button !== 0) return;

  const pairPx = pairPxOf(st);
  // A collapsed panel has no box to measure; there is nothing to drag yet.
  if (!pairPx) return;

  st.divider.focus({ preventScroll: true });
  st.drag = {
    id: event.pointerId,
    x: event.clientX,
    ratio0: st.ratio == null ? declaredRatio(st) : st.ratio,
    pairPx,
    moved: false,
  };
  st.divider.dataset.dragging = 'true';
  // The drag paints every frame, so it must not queue behind the reset/keyboard
  // transition; `endDrag` puts the theme transition back afterwards.
  setTransition(st, DRAG_TRANSITION);
  try { st.divider.setPointerCapture(event.pointerId); } catch (_) { /* listeners still fire */ }
}

function onPointerMove(event) {
  const st = stateOf(event.currentTarget);
  if (!st || !st.drag || (event.pointerId !== undefined && st.drag.id !== event.pointerId)) return;
  const dx = event.clientX - st.drag.x;
  if (!st.drag.moved && Math.abs(dx) < 1) return;
  st.drag.moved = true;
  applyRatio(st, st.drag.ratio0 + dx / st.drag.pairPx);
}

function endDrag(st, persist) {
  const moved = st.drag && st.drag.moved;
  st.drag = null;
  st.divider.dataset.dragging = 'false';
  setTransition(st, '');
  if (persist && moved) writeStored(st.panel, st.index, st.ratio);
}

function onPointerUp(event) {
  const st = stateOf(event.currentTarget);
  if (!st || !st.drag || (event.pointerId !== undefined && st.drag.id !== event.pointerId)) return;
  try { st.divider.releasePointerCapture(event.pointerId); } catch (_) { /* already released */ }
  endDrag(st, true);
}

function onPointerCancel(event) {
  const st = stateOf(event.currentTarget);
  if (!st || !st.drag) return;
  endDrag(st, false);
}

function onKeyDown(event) {
  const st = stateOf(event.currentTarget);
  if (!st) return;

  const current = st.ratio == null ? declaredRatio(st) : st.ratio;
  const pairPx = pairPxOf(st);
  let next;
  if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
    next = current - (pairPx ? KEY_STEP_PX / pairPx : 0.02);
  } else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
    next = current + (pairPx ? KEY_STEP_PX / pairPx : 0.02);
  } else if (event.key === 'Home') {
    next = 0;
  } else if (event.key === 'End') {
    next = 1;
  } else if (event.key === 'Escape') {
    event.preventDefault();
    resetSplit(st);
    return;
  } else {
    return;
  }

  event.preventDefault();
  if (!pairPx) return;
  // Keyboard moves are discrete, so they are allowed the committed token
  // transition — but never under reduced motion, and never mid-drag.
  setTransition(st, prefersReducedMotion() ? 'none' : KEY_TRANSITION);
  applyRatio(st, next);
  writeStored(st.panel, st.index, st.ratio);
}

function onDoubleClick(event) {
  const st = stateOf(event.currentTarget);
  if (!st) return;
  event.preventDefault();
  resetSplit(st);
  st.divider.focus({ preventScroll: true });
}

// --- Measured-only upkeep --------------------------------------------------
// `left` is a percentage and needs no measurement, so a freshly built divider
// takes its stored split even before the panel has painted. Height and the ARIA
// pixel values do need a box, so they are measured once the panel that owns
// them is on screen.

function reposition(table) {
  const owned = mounted.get(table) || [];
  owned.forEach((st) => {
    const rect = typeof st.th.getBoundingClientRect === 'function'
      ? st.th.getBoundingClientRect() : null;
    if (rect && rect.height > 0) {
      st.divider.style.height = Math.round(rect.height) + 'px';
    }
    refreshLabel(st);
    positionDivider(st);
    syncAria(st);
  });
}

/** The `<details>` that collapses this table, or null when it has none. */
function panelOf(table) {
  return typeof table.closest === 'function'
    ? table.closest('details[data-panel-details]')
    : null;
}

/** Visible right now: no `<details>` wrapper to wait on, or an open one. */
function panelOpen(table) {
  const details = panelOf(table);
  return !details || !!details.open;
}

// --- Mount -----------------------------------------------------------------

function buildDivider(st) {
  const divider = document.createElement('button');
  divider.type = 'button';
  divider.className = 'tokdash-col-divider';
  divider.id = `tokdash-col-divider-${st.panel}-c${st.index}`;
  divider.setAttribute('role', 'separator');
  divider.setAttribute('aria-orientation', 'vertical');
  divider.setAttribute('aria-valuemin', String(MIN_PX));
  divider.setAttribute('aria-valuemax', String(MAX_PX));
  divider.setAttribute('aria-valuenow', '0');
  divider.dataset.rpPanel = st.panel;
  divider.dataset.rpCol = String(st.index);
  divider.dataset.dragging = 'false';
  divider.tabIndex = 0;
  return divider;
}

function wire(st) {
  const divider = st.divider;
  divider.__rp = st;
  divider.addEventListener('pointerdown', onPointerDown);
  divider.addEventListener('pointermove', onPointerMove);
  divider.addEventListener('pointerup', onPointerUp);
  divider.addEventListener('pointercancel', onPointerCancel);
  divider.addEventListener('keydown', onKeyDown);
  divider.addEventListener('dblclick', onDoubleClick);
}

/**
 * Declare the handle's hint the way the donut wedges declare a dynamically
 * built trigger — the three data attributes, then the shared primitive — and
 * attach it *after* the drag listeners, so the primitive's own
 * press-to-dismiss runs after `onPointerDown`'s `focus()` and a drag never
 * leaves the bubble hanging over the columns.
 */
function wireTooltip(st) {
  const divider = st.divider;
  divider.dataset.tooltip = '';
  divider.dataset.tooltipPlacement = 'top';
  divider.dataset.tooltipText = 'Drag to resize columns';
  try { attachTooltip(divider, { placement: 'top' }); } catch (_) { /* the aria-label still names the pair */ }
}

/**
 * Build this table's handles if it does not have them yet — the one path both
 * the init mount and the panel-open hook go through. Idempotent via the
 * `mounted` map, so mounting twice (or a double `toggle`) duplicates nothing.
 *
 * Scope to this table's OWN `<colgroup>`/`<thead>`: a session table renders its
 * project groups as nested tables inside body cells, and each of those carries
 * a `<colgroup>` too, so a subtree-wide query counts seven column groups
 * against one header row and the pairing below would never line up. A table
 * whose widths are not percentages is left completely alone: the pair
 * arithmetic would silently change its layout.
 *
 * Returns how many handles this call built (0 when already mounted or invalid).
 */
function ensureMounted(table) {
  if (!table || !table.dataset || mounted.has(table)) return 0;

  const colgroup = table.querySelector(':scope > colgroup');
  const thead = table.querySelector(':scope > thead');
  if (!colgroup || !thead) return 0;

  const cols = Array.from(colgroup.querySelectorAll('col'));
  if (cols.length < 2) return 0;

  const pct = cols.map(readPct);
  if (pct.some((value) => value === null)) return 0;

  const ths = Array.from(thead.querySelectorAll('th'));
  if (ths.length < cols.length) return 0;

  const host = (typeof table.closest === 'function' && table.closest('.overflow-x-auto'))
    || table.parentNode;
  if (!host || typeof host.appendChild !== 'function') return 0;
  if (host.classList && host.classList.add) host.classList.add(WRAP_CLASS);

  const owned = [];
  // Claim before building: the map is the single owner of this table's state
  // from here on, and a table in the map is never built a second time.
  mounted.set(table, owned);

  let base = 0;
  for (let index = 0; index < cols.length - 1; index += 1) {
    const st = {
      table,
      host,
      th: ths[index],
      leftTh: ths[index],
      rightTh: ths[index + 1],
      left: cols[index],
      right: cols[index + 1],
      panel: table.dataset.panel,
      index,
      pairPct: pct[index] + pct[index + 1],
      basePct: base,
      declaredLeft: pct[index],
      declaredRight: pct[index + 1],
      ratio: null,
      drag: null,
      divider: null,
    };
    base += pct[index];

    st.divider = buildDivider(st);
    host.appendChild(st.divider);
    wire(st);
    wireTooltip(st);
    owned.push(st);

    const stored = readStored(st.panel, index);
    st.ratio = stored == null ? declaredRatio(st) : stored;
    if (stored != null) {
      applyRatio(st, stored);
    } else {
      positionDivider(st);
      syncAria(st);
    }
  }

  reposition(table);
  return owned.length;
}

/**
 * A closed panel must carry nothing: drop its handles from the map, disconnect
 * their state from their listeners, and take the elements out of the DOM — the
 * element's own listeners go with it. The columns keep the width they had; the
 * stored split puts the same widths back on the next open, so a close/open
 * cycle is invisible except for the handles coming and going.
 *
 * Returns how many handles this call removed (0 when nothing was mounted).
 */
function releasePanel(table) {
  const owned = mounted.get(table);
  if (!owned || !owned.length) return 0;
  mounted.delete(table);
  owned.forEach((st) => {
    if (!st.divider) return;
    st.divider.__rp = null;
    // The primitive keeps its own scroll listener on `window`, so releasing the
    // handle has to detach it too — otherwise every close/open cycle would leave
    // nine dead listeners behind for the life of the page.
    try { detachTooltip(st.divider); } catch (_) { /* the element is leaving anyway */ }
    st.divider.remove();
  });
  return owned.length;
}

/**
 * Claim this table's `<details>` and install its open/close hook exactly once:
 * opening builds through `ensureMounted`, closing releases through
 * `releasePanel`. A table with no `<details>` ancestor needs no hook — it is
 * always visible and was mounted by the init pass.
 */
function watchPanel(table) {
  if (watched.has(table)) return;
  watched.add(table);
  if (typeof table.closest !== 'function') return;
  const details = panelOf(table);
  if (!details || typeof details.addEventListener !== 'function') return;
  details.addEventListener('toggle', () => {
    if (details.open) ensureMounted(table);
    else releasePanel(table);
  });
}

/**
 * Claim every session table under `root`: install the panel hook, and build
 * handles for the panels that are on screen right now. Idempotent per table —
 * a second call wires no hook twice and builds nothing twice, because both
 * steps key off `watched` / `mounted` rather than a one-shot flag.
 *
 * Returns how many dividers this call built (0 when all panels are closed or
 * everything was already mounted).
 */
export function mountResizablePanels(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return 0;
  if (typeof document === 'undefined' || typeof document.createElement !== 'function') return 0;
  if (typeof window === 'undefined' || !('PointerEvent' in window)) return 0;

  const tables = Array.from(root.querySelectorAll('table.session-table[data-panel]'));
  if (!tables.length) return 0;

  let count = 0;
  tables.forEach((table) => {
    watchPanel(table);
    // Visibility decides, not eagerness: a panel open at init gets its handles
    // now; a collapsed one waits for its <details> to fire `toggle`.
    if (panelOpen(table)) count += ensureMounted(table);
  });

  return count;
}
