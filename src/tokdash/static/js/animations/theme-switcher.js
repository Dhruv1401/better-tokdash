/**
 * TokDash v4 Animation System - Theme Switcher
 *
 * The 17 style themes were a dropdown, which asks the user to read 17 words and
 * imagine how each one looks. This renders them as preview tiles instead: each
 * swatch is painted from that theme's own ramp, and one ring slides between the
 * tiles so the current choice is a position on screen rather than a word.
 *
 * The native <select> stays in the DOM and stays the value carrier. It is what
 * applyStyleTheme() syncs and what the persisted change listener reads, so
 * picking a tile commits through the same path the dropdown always used — no
 * second source of truth for which theme is on.
 */

const CHECK_PATH = 'm4.6 8.4 2.3 2.3 4.5-4.9';
const COLUMN_FALLBACK = 4;

// Where a tile gets its colours. heatColorsMap is the eight-step ramp each theme
// already uses for its heatmap, which runs surface -> accent; themeMetaColors is
// the theme-color pair, used only if a ramp is missing.
function swatchPalette(theme, dark) {
  const config = (typeof window !== 'undefined' && window.TOKDASH_THEME_CONFIG) || {};
  const mode = dark ? 'dark' : 'light';
  const ramp = config.heatColorsMap?.[theme]?.[mode] || null;
  const meta = config.themeMetaColors?.[theme]?.[mode] || null;
  return {
    bg: ramp?.[1] || meta || (dark ? '#1E293B' : '#E0E7FF'),
    // The ramp's far end is the strongest text-weight colour in both modes.
    ink: ramp?.[7] || (dark ? '#BFDBFE' : '#1E40AF'),
    accent: ramp?.[5] || config.themeMetaColors?.[theme]?.light || '#2563EB',
  };
}

function isDarkDocument() {
  return document.documentElement.classList.contains('dark');
}

// One mounted switcher at a time: the settings panel is a singleton.
let state = null;

function paintTile(tile, dark) {
  const { bg, ink, accent } = swatchPalette(tile.dataset.theme, dark);
  tile.style.setProperty('--sw-bg', bg);
  tile.style.setProperty('--sw-ink', ink);
  tile.style.setProperty('--sw-accent', accent);
}

function buildTile(option) {
  const tile = document.createElement('button');
  tile.type = 'button';
  tile.className = 'theme-swatch';
  tile.dataset.theme = option.value;
  tile.setAttribute('role', 'radio');
  tile.setAttribute('aria-checked', 'false');
  tile.tabIndex = -1;

  const preview = document.createElement('span');
  preview.className = 'theme-swatch-preview';
  preview.setAttribute('aria-hidden', 'true');

  const check = document.createElement('span');
  check.className = 'theme-swatch-check';
  check.setAttribute('aria-hidden', 'true');
  check.innerHTML = `<svg width="10" height="10" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="${CHECK_PATH}" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

  const name = document.createElement('span');
  name.className = 'theme-swatch-name';
  name.textContent = option.label;
  // Carrying the key as well as the text keeps the tiles in step with the select
  // when applyI18n() re-translates the page.
  if (option.i18nKey) name.setAttribute('data-i18n', option.i18nKey);

  tile.append(preview, check, name);
  return tile;
}

function visibleTiles() {
  if (!state) return [];
  return state.tiles;
}

/**
 * Place the selection ring now.
 *
 * The grid lives inside the settings `<dialog>`, which is still hidden when the
 * bundle mounts — every tile measures zero there, so the ring parks on a
 * coordinate it cannot use until the panel opens. The surface that reveals the
 * grid calls this the moment it does, so the ring is already on the selected
 * tile the first time the panel is shown, instead of waiting for a
 * ResizeObserver delivery: that needs a rendering frame, and in a tab that is
 * not painting it never arrives, which is exactly when a restored dashboard
 * first opens the panel.
 */
export function placeThemeSwitcher() {
  placeIndicator();
}

function activeTile() {
  if (!state) return null;
  return state.tiles.find((tile) => tile.dataset.theme === state.theme) || null;
}

// Position the ring over the checked tile. Reads layout, so it is deliberately
// kept out of the selection path's paint: the ring is CSS-positioned from these
// custom properties and animates on its own.
function placeIndicator() {
  if (!state || !state.indicator) return;
  const tile = activeTile();
  if (!tile || !tile.offsetWidth || !tile.offsetHeight) {
    state.root.dataset.ready = 'false';
    return;
  }
  // First placement of a box the user has not seen yet: adopt it silently. The
  // ring is hidden until here, so transitioning the corner it was parked at into
  // the real position would read as it flying in from nowhere.
  const adopting = state.root.dataset.ready === 'false';
  if (adopting) state.indicator.style.transition = 'none';
  state.indicator.style.width = `${tile.offsetWidth}px`;
  state.indicator.style.height = `${tile.offsetHeight}px`;
  // Written directly rather than through a custom property: a transition cannot
  // start from a var()-derived value, so the ring would hold its previous matrix.
  state.indicator.style.transform = `translate3d(${tile.offsetLeft}px, ${tile.offsetTop}px, 0)`;
  state.root.dataset.ready = 'true';
  if (adopting) {
    // Flush the adopted box, then hand the transition back. Waiting on a frame
    // instead would leave the ring unscheduled in a tab that is not painting,
    // which is exactly when the panel first opens on a restored dashboard.
    void state.indicator.offsetWidth;
    state.indicator.style.transition = '';
  }
}

// How many tiles the grid currently fits per row, read from the layout rather
// than from the CSS, so Up/Down follow the wrapping at any panel width.
function columnCount() {
  const tiles = visibleTiles();
  if (tiles.length < 2) return 1;
  const firstTop = tiles[0].offsetTop;
  for (let index = 1; index < tiles.length; index += 1) {
    if (tiles[index].offsetTop !== firstTop) return index;
  }
  return tiles.length || COLUMN_FALLBACK;
}

function focusTile(tile) {
  if (!tile) return;
  state.tiles.forEach((each) => { each.tabIndex = each === tile ? 0 : -1; });
  tile.focus();
}

/**
 * Commit a theme. Hands it to the native select and lets its existing change
 * listener persist, apply and re-render — the same path a manual selection took,
 * so this control has no private copy of the theme logic.
 */
function commit(theme, { focus = false } = {}) {
  if (!state) return;
  const tile = state.tiles.find((each) => each.dataset.theme === theme) || null;
  // A tile that is no longer mounted cannot take the focus; the choice still
  // commits, because the select is the value carrier either way.
  if (focus) focusTile(tile);
  if (state.select.value !== theme) {
    state.select.value = theme;
    state.select.dispatchEvent(new Event('change', { bubbles: true }));
  } else {
    syncThemeSwitcher(theme);
  }
}

/**
 * Remember the tile a press went down on.
 *
 * A click only means the tile under the pointer if the pointer stayed on it. The
 * tiles shrink by 3% while pressed and sit in a panel that scrolls, so a release
 * a couple of pixels off the tile is a click on the grid, the panel or the scrim —
 * the browser dispatches `click` at the nearest common ancestor of the press and
 * the release — and the choice was dropped, or (on the scrim) the dialog was taken
 * away. Tracking the pressed tile makes the press the choice; the release only
 * finishes it.
 */
function rememberPressedTile(event) {
  if (!state) return;
  const tile = event.target.closest?.('.theme-swatch') || null;
  state.pressedTheme = tile ? tile.dataset.theme : null;
}

function forgetPressedTile() {
  if (state) state.pressedTheme = null;
}

// A click that never left its tile is the grid listener's business below. This
// one answers only for a release that landed elsewhere, and it runs in the
// document's capture phase so it still sees a click the dialog's scrim guard is
// about to swallow.
function completePressedTile(event) {
  if (!state || !state.pressedTheme) return;
  const theme = state.pressedTheme;
  state.pressedTheme = null;
  if (event.target.closest?.('.theme-swatch')) return;
  commit(theme);
}

function onKeydown(event) {
  if (!state) return;
  const tiles = visibleTiles();
  const current = tiles.indexOf(event.target.closest?.('.theme-swatch'));
  if (current < 0) return;
  const columns = columnCount();
  let next = null;
  switch (event.key) {
    case 'ArrowRight': next = (current + 1) % tiles.length; break;
    case 'ArrowLeft': next = (current - 1 + tiles.length) % tiles.length; break;
    case 'ArrowDown': next = Math.min(current + columns, tiles.length - 1); break;
    case 'ArrowUp': next = Math.max(current - columns, 0); break;
    case 'Home': next = 0; break;
    case 'End': next = tiles.length - 1; break;
    // Enter and Space already activate the focused button; only the arrows and
    // the ends need intercepting, and only they should stop the page scrolling.
    default: return;
  }
  event.preventDefault();
  commit(tiles[next].dataset.theme, { focus: true });
}

/**
 * Reflect a theme in the switcher: checked tile, roving tabindex, ring position
 * and preview colours. Safe to call before mounting and safe to call twice — the
 * caller (applyStyleTheme) cannot know whether the bundle has loaded yet.
 */
export function syncThemeSwitcher(theme) {
  if (!state) return;
  const next = theme || document.documentElement.dataset.uiTheme || 'paper';
  state.theme = next;
  const dark = isDarkDocument();
  state.tiles.forEach((tile) => {
    const checked = tile.dataset.theme === next;
    tile.setAttribute('aria-checked', checked ? 'true' : 'false');
    // Selection follows focus in a radiogroup, so the checked tile is the one
    // Tab reaches and the ring mirrors that.
    tile.tabIndex = checked ? 0 : -1;
    if (tile.dataset.tint !== (dark ? 'dark' : 'light')) {
      tile.dataset.tint = dark ? 'dark' : 'light';
      paintTile(tile, dark);
    }
  });
  placeIndicator();
}

/**
 * Build the switcher inside `root` from the options of `select`.
 * Returns null when the surface or the select is missing, leaving the native
 * control to do the job on its own.
 */
export function mountThemeSwitcher(root, { select = null } = {}) {
  if (!root || typeof document === 'undefined') return null;
  const selectEl = select || document.getElementById('styleThemeSelect');
  if (!selectEl) return null;

  const options = [...selectEl.options].map((option) => ({
    value: option.value,
    label: option.textContent.trim() || option.value,
    i18nKey: option.getAttribute('data-i18n') || '',
  }));
  if (!options.length) return null;

  root.textContent = '';
  const indicator = document.createElement('span');
  indicator.className = 'theme-switcher-indicator';
  indicator.setAttribute('aria-hidden', 'true');
  root.appendChild(indicator);

  const tiles = options.map((option) => {
    const tile = buildTile(option);
    paintTile(tile, isDarkDocument());
    tile.dataset.tint = isDarkDocument() ? 'dark' : 'light';
    return tile;
  });
  tiles.forEach((tile) => root.appendChild(tile));

  state = { root, select: selectEl, tiles, indicator, theme: null, pressedTheme: null };
  root.addEventListener('keydown', onKeydown);
  root.addEventListener('click', (event) => {
    const tile = event.target.closest?.('.theme-swatch');
    if (tile) commit(tile.dataset.theme);
  });
  root.addEventListener('pointerdown', rememberPressedTile, true);
  root.addEventListener('mousedown', rememberPressedTile, true);
  root.addEventListener('pointercancel', forgetPressedTile, true);
  document.addEventListener('click', completePressedTile, true);

  // The panel is hidden on first paint, so every tile measures zero. Placement
  // on open is the revealer's call (see `placeThemeSwitcher`); a ResizeObserver
  // then covers every later size change — widening, a font reflow.
  if (typeof ResizeObserver === 'function') {
    state.observer = new ResizeObserver(placeIndicator);
    state.observer.observe(root);
  } else if (typeof window !== 'undefined') {
    window.addEventListener('resize', placeIndicator);
  }

  syncThemeSwitcher(document.documentElement.dataset.uiTheme || selectEl.value || 'paper');
  return state;
}

/** Drop the mounted switcher. Exists for tests and for a panel rebuild. */
export function unmountThemeSwitcher() {
  if (!state) return;
  state.observer?.disconnect();
  state.root.removeEventListener('keydown', onKeydown);
  if (typeof document !== 'undefined') document.removeEventListener('click', completePressedTile, true);
  state = null;
}

/** Exposed for tests: the tiles currently mounted. */
export function themeSwitcherTiles() {
  return visibleTiles();
}
