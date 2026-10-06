/**
 * TokDash v4 Animation System - Range switcher
 *
 * The topbar used to carry the ten presets as ten loose ghost buttons plus a
 * "More ranges" disclosure that a width observer fed — one row at any width
 * and a menu everywhere else. Ten readings of one control is ten places to
 * drift: the active preset was whichever button last got aria-pressed, the
 * menu moved buttons around the DOM to fit, and a selection only ever *was*,
 * never *arrived*.
 *
 * The switcher is one control instead. Every preset is a segment, the active
 * segment is marked by a single pill that slides from the old selection to the
 * new one, and the DOM never rearranges: the segments keep the order a user
 * learned, whether all ten fit on one row or the track wraps. The pill is
 * visual state only — the segments keep aria-pressed, and the app keeps
 * committing ranges through its own click handler — so without the bundle the
 * control is still a complete, working set of buttons that merely lacks the
 * slide.
 *
 * Geometry is measured from the segments, never from the pill: an animated
 * element reports an animated box, and the pill has to land where the segment
 * IS, not where it was last painted.
 */

const states = new WeakMap();

/**
 * Place the indicator over whichever segment is pressed.
 *
 * offsetLeft/Top/Width/Height are the segment's layout truth and ignore the
 * indicator's own animation. The transform is written inline rather than
 * through a custom property, because a transform driven by a var() never
 * re-resolves under transition in Chromium — the pill would jump where it
 * should slide. The wrapping track is why the transform carries both axes: a
 * segment on the second row is reached by moving down, not further right.
 */
function placeIndicator(root, state) {
  const indicator = root.querySelector('.range-switcher-indicator');
  const active = [...root.querySelectorAll('.range-switcher-segment')]
    .find((segment) => segment.getAttribute('aria-pressed') === 'true');
  if (!indicator || !active) return null;
  const left = active.offsetLeft;
  const top = active.offsetTop;
  const width = active.offsetWidth;
  const height = active.offsetHeight;
  indicator.style.transform = `translate(${left}px, ${top}px)`;
  indicator.style.width = `${width}px`;
  indicator.style.height = `${height}px`;
  state.left = left;
  state.top = top;
  state.width = width;
  state.height = height;
  root.dataset.rangeValue = active.dataset.range || '';
  return { left, top, width, height, value: root.dataset.rangeValue };
}

/**
 * A segment list in document order, with the pressed one flagged.
 * Exposed through `rangeSwitcherState` rather than read ad hoc, so the app,
 * the tests and the module all describe the control the same way.
 */
function segmentReport(root) {
  return [...root.querySelectorAll('.range-switcher-segment')].map((segment) => ({
    range: segment.dataset.range || '',
    pressed: segment.getAttribute('aria-pressed') === 'true',
  }));
}

/**
 * Re-place the indicator under the current aria-pressed state.
 *
 * Called by the app whenever it rewrites that state — a range commit, a
 * language switch that changes every label's width — and by the module itself
 * when the track's box changes under it. Idempotent, and safe to call on a
 * control that was never mounted.
 */
export function syncRangeSwitcher(root) {
  if (!root || !root.matches?.('[data-range-switcher]')) return null;
  let state = states.get(root);
  if (!state) {
    state = { left: 0, top: 0, width: 0, height: 0 };
    states.set(root, state);
  }
  const placed = placeIndicator(root, state);
  return placed ? { ...state, value: root.dataset.rangeValue || null } : null;
}

/**
 * Turn the segment row into one switcher.
 *
 * Mounting builds the indicator if the markup has none, adopts the segments'
 * clicks for the visual move (the app's own listener still commits the range
 * and fetches), wires arrow-key navigation, and re-places the pill whenever
 * the track's box changes — fonts landing, a language switch, the rail
 * reappearing on its tab. Idempotent: a control already mounted is only
 * re-synced, never double-bound.
 */
export function mountRangeSwitcher(root, options = {}) {
  if (!root || !root.matches?.('[data-range-switcher]')) return 0;
  const segments = [...root.querySelectorAll('.range-switcher-segment')];
  if (!segments.length) return 0;

  if (root.dataset.rangeSwitcher !== 'ready') {
    root.dataset.rangeSwitcher = 'ready';
    let indicator = root.querySelector('.range-switcher-indicator');
    if (!indicator) {
      indicator = root.ownerDocument.createElement('span');
      indicator.className = 'range-switcher-indicator';
      indicator.setAttribute('aria-hidden', 'true');
      root.insertBefore(indicator, root.firstChild);
    }

    segments.forEach((segment) => {
      segment.addEventListener('click', () => {
        if (segment.getAttribute('aria-pressed') === 'true') return;
        segments.forEach((other) => {
          other.setAttribute('aria-pressed', String(other === segment));
        });
        syncRangeSwitcher(root);
        if (typeof options.onChange === 'function') {
          options.onChange(segment.dataset.range || '', segment);
        }
      });
    });

    // Arrow keys walk the segments in their visual order and select as they
    // go, so the keyboard gets the same arrive-somewhere the pointer does.
    // Tab keeps its native order; the roving here is a courtesy, not a trap.
    root.addEventListener('keydown', (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
      const toEnd = event.key === 'End' ? 1 : event.key === 'Home' ? -1 : 0;
      if (!step && !toEnd) return;
      event.preventDefault();
      const current = segments.findIndex((segment) => segment.getAttribute('aria-pressed') === 'true');
      const basis = current < 0 ? 0 : current;
      const next = toEnd
        ? (toEnd > 0 ? segments.length - 1 : 0)
        : (basis + step + segments.length) % segments.length;
      const target = segments[next];
      if (!target) return;
      target.focus();
      target.click();
    });

    // The pill's geometry goes stale whenever the track's box does: a font
    // landing changes label widths, the rail comes and goes with its tab.
    // Observing the track itself re-places the pill at exactly those moments
    // without a timer or a layout guess.
    if (typeof ResizeObserver === 'function') {
      const observer = new ResizeObserver(() => syncRangeSwitcher(root));
      observer.observe(root);
    }
  }

  // First placement paints without a slide: the pill has no previous position
  // to travel from, and animating from 0,0 reads as a glitch, not an arrival.
  const indicator = root.querySelector('.range-switcher-indicator');
  if (indicator) {
    indicator.style.transition = 'none';
    syncRangeSwitcher(root);
    void root.offsetWidth;
    indicator.style.transition = '';
  } else {
    syncRangeSwitcher(root);
  }
  return segments.length;
}

/**
 * The control as data: whether it is mounted, which segment owns the pill,
 * where the pill sits, and what every segment says. Exposed for tests and for
 * callers that need the selection without reading the DOM twice.
 */
export function rangeSwitcherState(root) {
  if (!root || !root.matches?.('[data-range-switcher]')) return null;
  const state = states.get(root) || { left: 0, top: 0, width: 0, height: 0 };
  const active = segmentReport(root).find((segment) => segment.pressed);
  return {
    ready: root.dataset.rangeSwitcher === 'ready',
    value: active ? active.range : null,
    left: state.left,
    top: state.top,
    width: state.width,
    height: state.height,
    segments: segmentReport(root),
  };
}
