/**
 * TokDash v4 Animation System - Switch
 *
 * A control was announcing "switch" without behaving like one. role="switch"
 * and aria-checked said the right words, and the thumb the stylesheet drew sat
 * there as decoration — the one gesture anyone's hand tries first on a switch
 * that looks like a switch, dragging the thumb with the pointer, did nothing
 * until the release, and then the release was only ever counted as a tap.
 *
 * This module is that gesture, and only that gesture. On pointerdown the thumb
 * starts following the pointer one to one, within a travel the stylesheet's own
 * numbers define, so the drag reads on the paint rather than against it.
 * Released past the halfway point, the drag was the decision — and the click
 * the platform was already going to send on pointerup does the committing, so
 * the app's own handler (the persistence write, aria-checked, the KPI
 * re-presentation) stays the only thing that ever changes state. Released short
 * of halfway, or cancelled by the platform, the gesture was a retreat: the
 * thumb returns and the trailing click is stopped at the capture phase of the
 * parent, before it can reach a handler that would hear a toggle the finger had
 * already taken back. Tab, Space and Enter are never touched: the control is
 * the button it always was, and the keyboard commits through the same click.
 *
 * Fallback contract: without PointerEvents the module binds nothing and the
 * control is exactly what it was — a working switch that answers a click.
 */

const states = new WeakMap();
// Pointer travel below this is a tap: the click passes through to the app's own
// handler unchanged. Past it the drag is real, and only crossing halfway lets
// the click through.
const DRAG_DEAD_ZONE = 3;
// If no click follows the pointerup (pointercancel, a lost capture), this is
// how long the drag's preview and the click-suppression flag wait before
// cleaning themselves up.
const CLICK_GRACE_MS = 80;

function stateOf(control) {
  let state = states.get(control);
  if (state) return state;
  state = { control, drag: null, suppressClick: false, graceTimer: null };
  states.set(control, state);
  return state;
}

function readPx(value) {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * The travel a thumb can cross, in CSS pixels, read from the element the
 * stylesheet styles: track width minus both insets and the thumb size it
 * declares. Measured per drag, so a change in the track's own geometry is the
 * drag's geometry too — the pointer and the paint can never disagree.
 */
function travelOf(state) {
  const track = state.control.querySelector('[aria-hidden="true"], .switch-track, .overview-readable-tokens-track');
  if (!track || typeof track.getBoundingClientRect !== 'function') return null;
  const style = typeof getComputedStyle === 'function' ? getComputedStyle(track) : null;
  const width = track.getBoundingClientRect().width;
  if (!Number.isFinite(width) || width <= 0 || !style) return null;
  const inset = readPx(style.getPropertyValue('--switch-inset'));
  const thumb = readPx(style.getPropertyValue('--switch-thumb-size'))
    ?? readPx(style.width)
    ?? width * 0.7;
  if (inset == null || thumb == null || thumb <= 0) return null;
  const travel = width - inset * 2 - thumb;
  return travel > 0 ? travel : null;
}

function checkedOf(control) {
  return control.getAttribute('aria-checked') === 'true';
}

/** Put the thumb where the pointer put it, without a transition. */
function preview(state, x) {
  if (!Number.isFinite(x)) return; // a drag that cannot be measured must not paint
  state.control.dataset.switchDrag = 'true';
  state.control.style.setProperty('--switch-drag-x', `${x}px`);
}

/** Give the paint back to aria-checked, which transitions from the preview. */
function clearPreview(state) {
  delete state.control.dataset.switchDrag;
  state.control.style.removeProperty('--switch-drag-x');
}

function endDrag(state) {
  state.drag = null;
  if (state.graceTimer) { clearTimeout(state.graceTimer); state.graceTimer = null; }
  // The click that may follow has its grace period; the flag cannot outlive it
  // or the next deliberate click would eat the app's handler.
  state.graceTimer = setTimeout(() => {
    state.suppressClick = false;
    clearPreview(state);
    state.graceTimer = null;
  }, CLICK_GRACE_MS);
}

/**
 * Mounted per control. The listeners are the gesture, not the state: a tap is
 * not intercepted at all (the platform still sends the click the app's handler
 * is bound to), a real drag is only ever a preview plus a veto on the way out.
 */
export function mountSwitches(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return 0;
  const hasPointer = typeof window !== 'undefined' && 'PointerEvent' in window;
  let count = 0;
  root.querySelectorAll('button[role="switch"]').forEach((control) => {
    const state = stateOf(control);
    if (hasPointer && control.dataset.switch !== 'ready') {
      control.dataset.switch = 'ready';

      control.addEventListener('pointerdown', (event) => {
        if (event.button !== undefined && event.button !== 0) return;
        if (state.drag) return;
        const travel = travelOf(state);
        if (travel == null) return;
        // A gesture that begins disarms the last one's veto: one retreat gets
        // one click stopped, not the next tap the user meant to land.
        state.suppressClick = false;
        state.drag = {
          pointerId: event.pointerId,
          startX: event.clientX,
          base: checkedOf(control) ? travel : 0,
          travel,
          moved: false,
        };
        // Capture keeps the gesture over the control even when the pointer
        // leaves it mid-drag; a hostile stub without a real pointer throws,
        // and the drag still works off the element's own listeners.
        try { control.setPointerCapture(event.pointerId); } catch (_) { /* keep the listeners */ }
        control.style.userSelect = 'none';
        preview(state, state.drag.base);
      });

      control.addEventListener('pointermove', (event) => {
        const drag = state.drag;
        if (!drag || (event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
        const dx = event.clientX - drag.startX;
        if (Math.abs(dx) >= DRAG_DEAD_ZONE) drag.moved = true;
        if (drag.moved) {
          preview(state, Math.min(drag.travel, Math.max(0, drag.base + dx)));
        }
      });

      control.addEventListener('pointerup', (event) => {
        const drag = state.drag;
        if (!drag || (event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
        if (drag.moved) {
          const dx = event.clientX - drag.startX;
          const passed = (drag.base + dx) > drag.travel / 2;
          // Committed: the click passes and the app's handler does the real
          // work. Retreated: the click that would announce a toggle the finger
          // withdrew is stopped before it propagates past the control.
          state.suppressClick = !passed;
        } else {
          state.suppressClick = false;
        }
        endDrag(state);
      });

      // The platform's way of ending a gesture it took over (a thrown touch, a
      // browser-level cancel): treat it as a retreat whenever it had moved.
      control.addEventListener('pointercancel', () => {
        if (!state.drag) return;
        state.suppressClick = state.drag.moved;
        endDrag(state);
      });

      // Runs in the capture phase of the parent, before any listener on the
      // control itself: the only vantage that sees the click first.
      const parent = control.parentElement || control;
      parent.addEventListener('click', (event) => {
        if (!state.suppressClick) { clearPreview(state); return; }
        state.suppressClick = false;
        if (state.graceTimer) { clearTimeout(state.graceTimer); state.graceTimer = null; }
        event.preventDefault();
        event.stopPropagation();
        clearPreview(state);
      }, true);
    }
    count += 1;
  });
  return count;
}

/**
 * The control as data. `checked` is read live from aria-checked, which stays
 * the app's: this module never writes the attribute.
 */
export function switchState(control) {
  if (!control || !control.matches?.('button[role="switch"]')) return null;
  const state = states.get(control);
  return {
    ready: state != null && control.dataset.switch === 'ready',
    checked: checkedOf(control),
    dragging: Boolean(state && state.drag),
    suppressClick: Boolean(state && state.suppressClick),
    preview: state && state.control.dataset.switchDrag === 'true'
      ? (state.control.style.getPropertyValue('--switch-drag-x') || null)
      : null,
  };
}
