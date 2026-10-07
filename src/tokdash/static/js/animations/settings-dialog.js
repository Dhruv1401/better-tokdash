/**
 * TokDash v4 Animation System - Settings dialog
 *
 * Settings opened as a claim rather than as a modal. The markup said
 * `role="dialog" aria-modal="true"` while nothing enforced either: one Tab from
 * the open panel landed on a range segment in the topbar *behind* it, and the
 * page underneath still scrolled out from under the scrim. A control that
 * announces modality it does not have is worse than one that stays quiet, because
 * the user believes the page behind it is out of reach and then finds it is not.
 *
 * The scrim is a real `<dialog>` now, so the hard half is the platform's: while
 * it is up the rest of the document is inert, focus cannot leave it, Escape
 * closes it, and the element that opened it gets the focus back. This module owns
 * the half the platform does not do on its own — putting the focus in the panel
 * on the way in, tracking which of the two settings triggers actually opened it,
 * and holding the page still so a dimmed dashboard does not slide underneath the
 * reader while they are choosing a setting.
 *
 * The panel's entropy stays the app's: every control inside is the one that was
 * always there, and their handlers are never touched.
 */

const SCROLL_LOCK_CLASS = 'settings-dialog-open';
// The width the scrollbar was taking, put back on the page so locking the scroll
// does not reflow the topbar six pixels to the right.
const GUTTER_PROPERTY = '--settings-dialog-gutter';

let state = null;

function syncOpener(open) {
  const opener = state && state.opener;
  if (!opener || typeof opener.setAttribute !== 'function') return;
  opener.setAttribute('aria-expanded', String(Boolean(open)));
}

/**
 * Stop the page behind the dialog from moving.
 *
 * The scrim is fixed, so a scrollable page slides under a dimmed pane: the
 * reader follows the settings they opened with the page gone from underneath it,
 * and the place they came from is somewhere else when they close. Measured once,
 * on the way in, because the gutter is worth zero the moment the lock is on.
 */
function lockPage() {
  if (!state || state.locked) return;
  // Measured from the element's own box, not `clientWidth`: that rounds to whole
  // pixels, and a scrollbar really taking 5.6 of them would leave the page 0.4px
  // narrower under the lock — a move the topbar would wear.
  const layoutWidth = document.documentElement.getBoundingClientRect().width;
  const gutter = Math.max(0, window.innerWidth - layoutWidth);
  document.documentElement.style.setProperty(GUTTER_PROPERTY, `${gutter}px`);
  document.documentElement.classList.add(SCROLL_LOCK_CLASS);
  state.locked = true;
}

function unlockPage() {
  if (!state || !state.locked) return;
  document.documentElement.classList.remove(SCROLL_LOCK_CLASS);
  document.documentElement.style.removeProperty(GUTTER_PROPERTY);
  state.locked = false;
}

/**
 * Everything the dialog does as it goes away, whichever way it went.
 *
 * `close()` queues its event, so this runs on the way out as well as from the
 * platform's own close; the guard makes the second report a no-op rather than a
 * second focus hand-off.
 */
function settleClosed() {
  if (!state || state.closed) return;
  state.closed = true;
  unlockPage();
  syncOpener(false);
  if (state.focusOnClose !== false) {
    const opener = state.opener;
    if (opener && typeof opener.focus === 'function') opener.focus();
  }
  state.focusOnClose = true;
  state.opener = null;
  if (typeof state.options.onClose === 'function') state.options.onClose(state.backdrop);
}

/**
 * Bind the dialog's behaviour to the markup that already exists.
 *
 * Idempotent. Without a platform that can show a modal dialog this returns 0 and
 * leaves the app's own open/close path in charge, which is why the panel is only
 * marked as the bundle's once this has taken.
 */
export function mountSettingsDialog(backdrop, panel, options = {}) {
  if (!backdrop || !panel) return 0;
  if (typeof backdrop.showModal !== 'function' || typeof backdrop.close !== 'function') return 0;
  if (state && state.backdrop === backdrop) return 1;

  state = {
    backdrop,
    panel,
    options,
    opener: null,
    locked: false,
    closed: true,
    focusOnClose: true,
  };

  // The panel is the focus target on the way in: it is a long scrolling surface,
  // so the reader is put at its top with the dialog's name announced, rather than
  // on the close button where Enter would undo the thing they just asked for.
  panel.setAttribute('tabindex', '-1');

  backdrop.addEventListener('close', () => { settleClosed(); });
  return 1;
}

/** Whether the dialog is up, who opened it, and where the focus is. */
export function settingsDialogState() {
  if (!state) return null;
  const { backdrop, panel, opener } = state;
  const active = typeof document !== 'undefined' ? document.activeElement : null;
  return {
    mounted: true,
    open: Boolean(backdrop.open),
    labelled: backdrop.getAttribute('aria-labelledby') || null,
    opener: opener ? (opener.id || opener.tagName || null) : null,
    expanded: opener ? opener.getAttribute('aria-expanded') : null,
    scrollLocked: Boolean(document.documentElement.classList.contains(SCROLL_LOCK_CLASS)),
    focusInPanel: active === panel,
    focusInside: panel.contains(active),
    activeElement: active ? (active === panel ? 'panel' : (active.id || active.tagName || null)) : null,
  };
}

/**
 * Show the dialog, with the focus inside it.
 *
 * `opener` is the control that asked for it. It is passed in rather than read off
 * the document because the desktop sidebar trigger and the phone-width mirror are
 * both wired to the same entry point, and only one of the two is on screen: focus
 * has to come back to the button the user actually pressed.
 */
export function openSettingsDialog({ opener = null } = {}) {
  if (!state) return null;
  const { backdrop, panel } = state;
  const active = typeof document !== 'undefined' ? document.activeElement : null;
  const candidate = opener && opener.isConnected !== false ? opener : null;
  state.opener = candidate
    || (active && active !== document.body && active !== document.documentElement ? active : null);
  state.closed = false;
  state.focusOnClose = true;

  if (!backdrop.open) {
    backdrop.removeAttribute('hidden');
    backdrop.showModal();
  }
  lockPage();
  syncOpener(true);
  if (typeof panel.focus === 'function') panel.focus({ preventScroll: true });
  if (typeof state.options.onOpen === 'function') state.options.onOpen(panel);
  return settingsDialogState();
}

/** Hide the dialog, handing the focus back unless the caller says otherwise. */
export function closeSettingsDialog({ restoreFocus = true } = {}) {
  if (!state) return null;
  const { backdrop } = state;
  if (!backdrop.open) return settingsDialogState();
  state.focusOnClose = restoreFocus;
  backdrop.close();
  backdrop.setAttribute('hidden', '');
  settleClosed();
  return settingsDialogState();
}

/** Forget the mount. Used by surfaces that rebuild the shell, and by tests. */
export function unmountSettingsDialog() {
  if (!state) return null;
  if (state.backdrop.open) state.backdrop.close();
  unlockPage();
  state.closed = true;
  state = null;
  return null;
}
