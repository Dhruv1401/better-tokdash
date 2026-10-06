/**
 * TokDash v4 Animation System - Popovers
 *
 * A panel that belongs to a control: the refresh report under the refresh
 * button was one, but it was welded to that control's corner with
 * `position: absolute; right: 0`, so it could only ever open downward and only
 * ever right-aligned, and it disappeared off the side of a narrow window.
 *
 * This owns the part that is the same every time — where the panel goes, who can
 * reach it, and how it goes away — and leaves the panel's contents to whoever
 * built them. The panel is moved to a body-level layer while it is open, because
 * the topbar it lives in sets backdrop-filter and a filtered ancestor becomes the
 * containing block for a fixed child: left in place, a viewport-positioned panel
 * would be positioned against the toolbar instead of the window.
 */

const LAYER_ID = 'tokdashPopoverLayer';
const OFFSET_PX = 10;
const EDGE_PX = 8;
// How long a scroll report is treated as still settling after a panel opens.
const SCROLL_SETTLE_MS = 250;

let layer = null;
let openHandle = null;
// Every panel this module has been asked to own, so an outside caller can look one up.
const attached = [];

function ensureLayer(doc = document) {
  if (layer && layer.isConnected) return layer;
  layer = doc.createElement('div');
  layer.id = LAYER_ID;
  layer.className = 'popover-layer';
  (doc.body || doc.documentElement).appendChild(layer);
  return layer;
}

function triggerIsOnScreen(trigger) {
  const rect = trigger.getBoundingClientRect();
  const vh = window.innerHeight || document.documentElement.clientHeight;
  return rect.bottom >= 0 && rect.top <= vh;
}

/**
 * Place the panel against its trigger.
 *
 * Preferred side first, then whichever side has more room, so a panel under a
 * control near the bottom of the window opens upward rather than off the screen.
 * Horizontally the requested alignment is applied and then clamped, which is what
 * keeps a 390px panel on screen when its trigger sits near an edge.
 */
function place(handle) {
  const { trigger, panel, options } = handle;
  const t = trigger.getBoundingClientRect();
  // The panel may be running its own open animation, and an animated element
  // reports an animated box. offsetWidth/offsetHeight are the laid-out box, so a
  // panel that scales or slides on open is still placed against its trigger's real
  // edge rather than a few pixels off. The caller owns the animation; the primitive
  // must not inherit its geometry.
  const pWidth = panel.offsetWidth;
  const pHeight = panel.offsetHeight;
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const vh = window.innerHeight || document.documentElement.clientHeight;

  const spaceBelow = vh - (t.bottom + OFFSET_PX);
  const spaceAbove = t.top - OFFSET_PX;
  const preferBottom = options.placement !== 'top';
  const fits = preferBottom ? spaceBelow >= pHeight + EDGE_PX : spaceAbove >= pHeight + EDGE_PX;
  const side = fits ? (preferBottom ? 'bottom' : 'top') : (spaceAbove > spaceBelow ? 'top' : 'bottom');

  const align = options.align || 'end';
  const rawX = align === 'start' ? t.left : align === 'center' ? t.left + t.width / 2 - pWidth / 2 : t.right - pWidth;
  const maxX = Math.max(EDGE_PX, vw - EDGE_PX - pWidth);
  const x = Math.min(Math.max(rawX, EDGE_PX), maxX);
  const y = side === 'bottom' ? t.bottom + OFFSET_PX : t.top - OFFSET_PX - pHeight;

  panel.dataset.placement = side;
  panel.dataset.align = align;
  panel.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0)`;
  return side;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusables(panel) {
  return [...panel.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
}

function onDocumentKeydown(event) {
  const handle = openHandle;
  if (!handle) return;
  if (event.key === 'Escape') {
    event.stopPropagation();
    // Only take focus back if it is somewhere inside the panel: a report that
    // announced itself mid-task must not yank the caret out of a form.
    closePopover({ restoreFocus: handle.panel.contains(document.activeElement) });
    return;
  }
  if (event.key !== 'Tab' || !handle.options.modal) return;
  // A modal panel is a loop: Tab out of the last control wraps to the first, so
  // the page behind it is unreachable while it is up.
  const items = focusables(handle.panel);
  if (!items.length) {
    event.preventDefault();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function onDocumentPointerDown(event) {
  const handle = openHandle;
  if (!handle) return;
  const target = event.target;
  if (handle.panel.contains(target) || handle.trigger.contains(target)) return;
  // A modal panel owns the page until it is dismissed, so a click outside is not
  // a dismissal — the backdrop is the only way out besides Escape.
  if (handle.options.modal) {
    event.preventDefault();
    return;
  }
  closePopover({ restoreFocus: false, reason: 'outside' });
}

function onScroll() {
  const handle = openHandle;
  if (!handle) return;
  if (!triggerIsOnScreen(handle.trigger)) {
    // Same reasoning as the tooltip: a focus that scrolls an off-screen trigger
    // into view reports the position before the scroll landed.
    if (performance.now() - (handle.openedAt || 0) < SCROLL_SETTLE_MS) {
      setTimeout(() => {
        if (openHandle === handle && !triggerIsOnScreen(handle.trigger)) closePopover({ restoreFocus: false, reason: 'scroll' });
      }, SCROLL_SETTLE_MS);
      return;
    }
    closePopover({ restoreFocus: false, reason: 'scroll' });
    return;
  }
  place(handle);
}

function onResize() {
  if (openHandle) place(openHandle);
}

function bindDocument(handle) {
  document.addEventListener('keydown', onDocumentKeydown, true);
  document.addEventListener('pointerdown', onDocumentPointerDown, true);
  window.addEventListener('scroll', onScroll, true);
  window.addEventListener('resize', onResize);
  handle.bound = true;
}

function unbindDocument(handle) {
  if (!handle.bound) return;
  document.removeEventListener('keydown', onDocumentKeydown, true);
  document.removeEventListener('pointerdown', onDocumentPointerDown, true);
  window.removeEventListener('scroll', onScroll, true);
  window.removeEventListener('resize', onResize);
  handle.bound = false;
}

/**
 * Bind a panel to the control that owns it.
 *
 * `trigger` opens and closes nothing on its own — the caller decides, because
 * only the caller knows whether a show was asked for or merely reported.
 */
export function attachPopover(trigger, panel, options = {}) {
  if (!trigger || !panel) return null;
  const handle = {
    trigger,
    panel,
    options: { modal: false, autoFocus: false, ...options },
    bound: false,
    openedAt: 0,
    home: panel.parentElement || null,
  };
  panel.setAttribute('aria-hidden', 'true');
  panel.dataset.popover = 'closed';
  trigger.setAttribute('aria-controls', panel.id);
  trigger.setAttribute('aria-expanded', 'false');
  attached.push(handle);
  return handle;
}

/**
 * Show a panel. `focus` moves focus into it, which is right when the user asked
 * for the panel and wrong when it opened to report something that finished
 * elsewhere — a live region must not take the caret out of the field in use.
 */
export function openPopover(handle, { focus = false } = {}) {
  if (!handle) return null;
  if (openHandle && openHandle !== handle) closePopover({ restoreFocus: false, reason: 'superseded' });
  const { trigger, panel, options } = handle;
  ensureLayer(trigger.ownerDocument || document).appendChild(panel);
  panel.hidden = false;
  panel.removeAttribute('aria-hidden');
  panel.dataset.popover = 'open';
  if (options.modal) {
    if (!panel.hasAttribute('role')) panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
  }
  handle.openedAt = performance.now();
  openHandle = handle;
  trigger.setAttribute('aria-expanded', 'true');
  // Measured after the panel has its real box, so the flip uses the true height.
  place(handle);
  bindDocument(handle);
  const wantsFocus = focus || options.autoFocus;
  if (wantsFocus) {
    const target = focusables(panel)[0] || panel;
    if (!panel.hasAttribute('tabindex') && target === panel) panel.setAttribute('tabindex', '-1');
    target.focus();
    handle.focusedInto = true;
  }
  if (typeof options.onOpen === 'function') options.onOpen(panel);
  return handle;
}

/** Hide a panel and put everything back the way it was found. */
export function closePopover({ restoreFocus = false, reason = 'api' } = {}, handle = openHandle) {
  if (!handle) return null;
  const { trigger, panel, options } = handle;
  if (openHandle === handle) openHandle = null;
  unbindDocument(handle);
  panel.dataset.popover = 'closed';
  panel.hidden = true;
  panel.setAttribute('aria-hidden', 'true');
  if (options.modal) panel.removeAttribute('aria-modal');
  trigger.setAttribute('aria-expanded', 'false');
  if (restoreFocus || handle.focusedInto) {
    // Return the user to the control they came from, but never steal focus from
    // wherever they have since moved on to.
    if (trigger.contains(document.activeElement) || panel.contains(document.activeElement) || document.activeElement === document.body) {
      if (typeof trigger.focus === 'function') trigger.focus();
    }
    handle.focusedInto = false;
  }
  if (typeof options.onClose === 'function') options.onClose(panel, reason);
  return handle;
}

/** Re-place the open panel. Used after content changes its height. */
export function repositionPopover(handle = openHandle) {
  if (!handle) return null;
  place(handle);
  return handle;
}

/** Whether a panel is open, and where it ended up. Exposed for tests. */
export function popoverState() {
  if (!openHandle) return null;
  const { panel } = openHandle;
  return {
    open: panel.dataset.popover === 'open',
    placement: panel.dataset.placement || 'bottom',
    align: panel.dataset.align || 'end',
    hidden: panel.hidden,
    modal: panel.getAttribute('aria-modal') === 'true',
    expanded: openHandle.trigger.getAttribute('aria-expanded'),
    inLayer: panel.parentElement?.id === LAYER_ID,
  };
}

/** The handle currently attached to `panel`, if any. */
export function popoverFor(panel) {
  return attached.find((h) => h.panel === panel) || null;
}
