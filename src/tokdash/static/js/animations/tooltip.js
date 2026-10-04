/**
 * TokDash v4 Animation System - Tooltips
 *
 * Detail that a card cannot fit — the exact token count, what "cache hit rate"
 * measures, which colour a composition bar stands for — was carried by 137 ad-hoc
 * `title` attributes. The browser's own tooltip cannot be styled, cannot be read
 * by a keyboard user, and cannot be positioned, so on a dashboard built out of
 * dense figures it is the one detail cue that looks nothing like the rest.
 *
 * This is the replacement: one shared bubble, one motion vocabulary, and a
 * placement pass that flips and clamps so a hint on the edge cards stays on
 * screen instead of being clipped by the viewport.
 *
 * The trigger keeps its `title` (and its `data-i18n-title`, so translations keep
 * working); attaching adopts that text as the content and takes the native
 * tooltip away, because two tooltips on one element is worse than either.
 */

const LAYER_ID = 'tokdashTooltip';
// Long enough that sweeping the pointer across a card does not flash a hint, short
// enough that a deliberate pause is answered. Focus opens instantly: a keyboard
// user asked for it by tabbing there, and has no hover to wait out.
const OPEN_DELAY_MS = 320;
const GAP_PX = 8;
// Keeps a hint off the very edge of the window, where a rounded chip looks clipped.
const EDGE_PX = 8;
// The arrow stays this far from the chip's corners, clear of the 7px corner radius.
const ARROW_INSET_PX = 14;
// How long a scroll report is treated as still settling after a hint opens.
const SCROLL_SETTLE_MS = 250;

let layer = null;
let bubble = null;
let textNode = null;
let openEntry = null;
let openTimer = null;
let escapeBound = false;

// Trigger element -> its attachment. Weak so a re-rendered card does not leak.
const attachments = new WeakMap();

function ensureLayer(doc = document) {
  if (layer && layer.isConnected) return layer;
  layer = doc.createElement('div');
  layer.id = LAYER_ID;
  layer.className = 'tooltip';
  layer.setAttribute('role', 'tooltip');
  layer.dataset.open = 'false';
  layer.setAttribute('aria-hidden', 'true');

  bubble = doc.createElement('div');
  bubble.className = 'tooltip-bubble';
  textNode = doc.createElement('span');
  textNode.className = 'tooltip-text';
  bubble.appendChild(textNode);
  layer.appendChild(bubble);
  (doc.body || doc.documentElement).appendChild(layer);
  return layer;
}

function triggerIsOnScreen(entry) {
  const rect = entry.trigger.getBoundingClientRect();
  const viewportH = window.innerHeight || document.documentElement.clientHeight;
  return rect.bottom >= 0 && rect.top <= viewportH;
}

function contentFor(entry) {
  const { trigger, options } = entry;
  if (typeof options.content === 'function') return options.content(trigger);
  if (options.content != null) return options.content;
  return trigger.dataset.tooltipText || '';
}

function stringFor(entry) {
  const value = contentFor(entry);
  if (value == null) return '';
  return typeof value === 'string' ? value : String(value.textContent || value);
}

// Adopting the title is what makes this a drop-in replacement: the attribute stays
// in the markup as the source of truth (and for data-i18n-title), and the native
// tooltip is withdrawn. A later applyI18n() re-writes `title`, so the observer puts
// the new translation back into the adopted slot and withdraws it again.
function adoptTitle(trigger, entry) {
  const title = trigger.getAttribute('title');
  if (title == null) return;
  trigger.dataset.tooltipText = title;
  trigger.setAttribute('title', '');
  trigger.removeAttribute('title');
  if (entry && !entry.observingTitle && typeof MutationObserver === 'function') {
    entry.observingTitle = new MutationObserver(() => {
      const next = trigger.getAttribute('title');
      if (next == null) return;
      trigger.dataset.tooltipText = next;
      trigger.removeAttribute('title');
    });
    entry.observingTitle.observe(trigger, { attributes: true, attributeFilter: ['title'] });
  }
}

function cancelPending() {
  if (openTimer) {
    clearTimeout(openTimer);
    openTimer = null;
  }
}

/**
 * Place the bubble against the trigger and report the side it ended up on.
 *
 * Preferred side first, then the opposite one when there is no room — a card in
 * the top row opens downward once its hint would leave the window. Horizontally
 * the chip is centred on the trigger and then clamped, and the arrow keeps
 * pointing at the trigger centre even when the chip had to move.
 */
function place(entry) {
  const rect = entry.trigger.getBoundingClientRect();
  const size = bubble.getBoundingClientRect();
  const viewportW = window.innerWidth || document.documentElement.clientWidth;
  const viewportH = window.innerHeight || document.documentElement.clientHeight;

  const preferred = entry.options.placement || 'top';
  const room = preferred === 'top'
    ? rect.top - GAP_PX - size.height
    : viewportH - (rect.bottom + GAP_PX) - size.height;
  let placement = preferred;
  if (room < EDGE_PX) placement = preferred === 'top' ? 'bottom' : 'top';

  const y = placement === 'top'
    ? rect.top - GAP_PX - size.height
    : rect.bottom + GAP_PX;
  const centred = rect.left + rect.width / 2 - size.width / 2;
  const maxX = Math.max(EDGE_PX, viewportW - EDGE_PX - size.width);
  const x = Math.min(Math.max(centred, EDGE_PX), maxX);

  const arrowAt = rect.left + rect.width / 2 - x;
  const arrow = Math.min(Math.max(arrowAt, ARROW_INSET_PX), size.width - ARROW_INSET_PX);

  layer.dataset.placement = placement;
  layer.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0)`;
  layer.style.setProperty('--tooltip-arrow-x', `${Math.round(arrow)}px`);
  return placement;
}

function onDocumentKeydown(event) {
  if (event.key !== 'Escape') return;
  const entry = openEntry;
  if (!entry) return;
  // Escape dismisses the hint but leaves focus alone: the trigger is where the
  // user was and where they will keep working.
  hideTooltip();
  if (entry.options.onEscape) entry.options.onEscape(entry.trigger);
}

function showTooltip(entry) {
  if (!entry || !entry.trigger.isConnected) return;
  const text = stringFor(entry);
  if (!text) return;
  const node = ensureLayer(entry.trigger.ownerDocument || document);
  cancelPending();
  entry.openedAt = performance.now();
  openEntry = entry;
  textNode.textContent = text;
  node.dataset.open = 'true';
  node.removeAttribute('aria-hidden');
  // Described-by only while the description is actually on screen: pointing at a
  // hidden bubble describes nothing and some readers announce the empty result.
  entry.trigger.setAttribute('aria-describedby', LAYER_ID);
  // Measured after the text lands, so the flip decision uses the real height.
  place(entry);
  if (!escapeBound) {
    document.addEventListener('keydown', onDocumentKeydown, true);
    escapeBound = true;
  }
  if (typeof entry.options.onShow === 'function') entry.options.onShow(entry.trigger);
}

function hideTooltip(reason = 'dismiss') {
  cancelPending();
  const entry = openEntry;
  openEntry = null;
  if (escapeBound) {
    document.removeEventListener('keydown', onDocumentKeydown, true);
    escapeBound = false;
  }
  if (layer) {
    layer.dataset.open = 'false';
    layer.setAttribute('aria-hidden', 'true');
  }
  if (entry) {
    entry.trigger.removeAttribute('aria-describedby');
    if (typeof entry.options.onHide === 'function') entry.options.onHide(entry.trigger, reason);
  }
}

function scheduleShow(entry) {
  cancelPending();
  const delay = entry.options.delay ?? OPEN_DELAY_MS;
  if (delay <= 0) {
    showTooltip(entry);
    return;
  }
  openTimer = setTimeout(() => {
    openTimer = null;
    showTooltip(entry);
  }, delay);
}

/**
 * Attach a tooltip to `trigger`.
 *
 * Content, in order: `options.content` (string, node or function), then the
 * `data-tooltip` value, then the trigger's own `title`, which is adopted and
 * withdrawn. Returns a handle so a caller that owns the trigger's lifetime can
 * detach it; the trigger is otherwise left exactly as it was found.
 */
export function attachTooltip(trigger, options = {}) {
  if (!trigger || typeof trigger.addEventListener !== 'function') return null;
  const existing = attachments.get(trigger);
  if (existing) return existing;

  const entry = { trigger, options, observingTitle: false, handlers: null };
  adoptTitle(trigger, entry);

  const onEnter = () => scheduleShow(entry);
  const onLeave = () => hideTooltip('leave');
  const onFocus = () => showTooltip(entry);
  const onBlur = () => hideTooltip('blur');
  // A pointer that presses the trigger (the ⓘ hints are spans) should not leave a
  // hint hanging over whatever it opened.
  const onPointerDown = () => hideTooltip('press');
  // A scrolling page must not strand the chip where the trigger used to be, so a
  // scroll re-places it while the trigger is still on screen. Only a trigger that
  // has actually left the window closes the hint.
  const onScroll = () => {
    const entry = openEntry;
    if (!entry || entry.trigger !== trigger) return;
    if (!triggerIsOnScreen(entry)) {
      // Focusing a trigger below the fold scrolls it into view, and the first
      // scroll report describes the position before that scroll landed. Believing
      // it would close the very hint the keyboard user just asked for, so give the
      // scroll a moment and look again rather than hiding on the first report.
      if (performance.now() - (entry.openedAt || 0) < SCROLL_SETTLE_MS) {
        setTimeout(() => {
          if (openEntry === entry && !triggerIsOnScreen(entry)) hideTooltip('scroll');
        }, SCROLL_SETTLE_MS);
        return;
      }
      hideTooltip('scroll');
      return;
    }
    place(entry);
  };

  entry.handlers = { onEnter, onLeave, onFocus, onBlur, onPointerDown, onScroll };
  trigger.addEventListener('pointerenter', onEnter);
  trigger.addEventListener('pointerleave', onLeave);
  trigger.addEventListener('focus', onFocus);
  trigger.addEventListener('blur', onBlur);
  trigger.addEventListener('pointerdown', onPointerDown);
  window.addEventListener('scroll', onScroll, true);
  attachments.set(trigger, entry);
  return entry;
}

/** Withdraw a tooltip and undo everything attaching did to the trigger. */
export function detachTooltip(trigger) {
  const entry = attachments.get(trigger);
  if (!entry) return;
  const { handlers } = entry;
  trigger.removeEventListener('pointerenter', handlers.onEnter);
  trigger.removeEventListener('pointerleave', handlers.onLeave);
  trigger.removeEventListener('focus', handlers.onFocus);
  trigger.removeEventListener('blur', handlers.onBlur);
  trigger.removeEventListener('pointerdown', handlers.onPointerDown);
  window.removeEventListener('scroll', handlers.onScroll, true);
  entry.observingTitle?.disconnect();
  if (openEntry === entry) hideTooltip('detach');
  // Hand the native title back: a trigger that loses its tooltip should not lose
  // its only detail cue with it.
  if (trigger.dataset.tooltipText) {
    trigger.setAttribute('title', trigger.dataset.tooltipText);
    delete trigger.dataset.tooltipText;
  }
  attachments.delete(trigger);
}

/**
 * Attach every `[data-tooltip]` element under `root`. An empty attribute means
 * "use my title", which is how the KPI hints are declared: their text stays in
 * the i18n dictionary and the primitive takes over presenting it.
 */
export function mountTooltips(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return 0;
  let count = 0;
  root.querySelectorAll('[data-tooltip]').forEach((trigger) => {
    if (attachments.has(trigger)) return;
    const placement = trigger.getAttribute('data-tooltip-placement') || 'top';
    if (attachTooltip(trigger, { placement })) count += 1;
  });
  return count;
}

/** Whether a hint is on screen, its text and the side it chose. Exposed for tests. */
export function tooltipState() {
  if (!openEntry || !layer) return null;
  return {
    text: textNode ? textNode.textContent : '',
    placement: layer.dataset.placement || 'top',
    open: layer.dataset.open === 'true',
    describedBy: openEntry.trigger.getAttribute('aria-describedby'),
  };
}

/** Close whatever is open. Used by surfaces that navigate or rebuild under a hint. */
export function dismissTooltip() {
  hideTooltip('external');
}
