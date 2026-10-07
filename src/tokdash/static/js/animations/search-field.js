/**
 * TokDash v4 Animation System - Search field
 *
 * The Sessions Explorer's search box was a bare input and a placeholder. Two
 * things a filter box owes its user were missing: a mark that says what the box
 * does before you have typed in it, and a way back out of a query that is not
 * "select the text and delete it". On a box that filters a long table the way
 * out is the one that matters — a half-typed term leaves the table looking
 * empty, and the term is the only thing that explains why.
 *
 * So the field gains exactly those two, and nothing else. The leading mark is
 * decoration (`aria-hidden`) placed over the input's own padding; the clear
 * control keeps a reserved slot, so the slot is there before a query does and
 * the row never re-measures when it appears. The input keeps `.ui-input`, so a
 * theme's border, fill and focus ring stay this control's.
 *
 * Filtering stays the app's. The input keeps its own inline handler and this
 * module never touches a row: clearing writes the empty string and re-dispatches
 * the very `input` event a keystroke sends, so the app's single filter path runs
 * once, with the same semantics as typing nothing. Without the bundle the field
 * is still a working search box that merely lacks the mark and the way out.
 */

const states = new WeakMap();

function inputOf(field) {
  return field.querySelector('.search-field-input') || field.querySelector('input');
}

function clearOf(field) {
  return field.querySelector('[data-search-field-clear]');
}

function stateOf(field) {
  let state = states.get(field);
  if (state) return state;
  const input = inputOf(field);
  if (!input) return null;
  state = {
    field,
    input,
    clear: clearOf(field),
    focused: false,
    hasQuery: Boolean(input.value),
  };
  states.set(field, state);
  return state;
}

/**
 * Write the field's state to the DOM.
 *
 * `data-has-query` is what the stylesheet keys the clear control's arrival off.
 * The withdrawn control also leaves the tab order and the accessibility tree,
 * because a control that cannot act is not a control — it is decoration, and
 * the field already has its decoration.
 */
function paint(state) {
  const { field, input, clear } = state;
  const hasQuery = Boolean(input.value);
  state.hasQuery = hasQuery;
  field.dataset.hasQuery = hasQuery ? 'true' : 'false';
  if (!clear) return state;
  clear.tabIndex = hasQuery ? 0 : -1;
  if (hasQuery) clear.removeAttribute('aria-hidden');
  else clear.setAttribute('aria-hidden', 'true');
  return state;
}

function publicState(state) {
  return {
    ready: state.field.dataset.searchField === 'ready',
    query: state.input.value,
    hasQuery: state.hasQuery === true,
    clearVisible: state.clear ? !state.clear.hasAttribute('aria-hidden') : false,
    clearTabIndex: state.clear ? state.clear.tabIndex : null,
    focused: state.focused === true,
  };
}

/**
 * Empty the field through the app's own filter path, and report whether there
 * was anything to empty. Escape and the clear control both land here so the two
 * ways out cannot drift apart.
 */
function clearQuery(state) {
  if (!state.input.value) {
    paint(state);
    return false;
  }
  state.input.value = '';
  // The same event a keystroke sends, so the app's handler filters: this module
  // never reaches for the table itself, and the query semantics stay one path.
  state.input.dispatchEvent(new Event('input', { bubbles: true }));
  paint(state);
  return true;
}

/**
 * Re-read a field's value and repaint. Exposed because a caller that writes the
 * value itself owns the call: the DOM has no way to tell this module that the
 * value changed under it.
 */
export function syncSearchField(field) {
  if (!field || !field.matches?.('[data-search-field]')) return null;
  const state = stateOf(field);
  return state ? publicState(paint(state)) : null;
}

/**
 * Mount every search field under `root`.
 *
 * Idempotent: a field already mounted is only repainted, never double-bound. The
 * listeners here are about the affordances, not about the query — the input's
 * own handler still owns filtering, and this module deliberately never calls it.
 */
export function mountSearchFields(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return 0;
  let count = 0;
  root.querySelectorAll('[data-search-field]').forEach((field) => {
    const state = stateOf(field);
    if (!state) return;
    if (field.dataset.searchField !== 'ready') {
      field.dataset.searchField = 'ready';
      const { input, clear } = state;
      input.addEventListener('input', () => paint(state));
      input.addEventListener('focus', () => {
        state.focused = true;
        paint(state);
      });
      input.addEventListener('blur', () => {
        state.focused = false;
      });
      // Escape is the keyboard's way out of the query, and it only acts on a
      // query that exists: an empty box swallows the key rather than announcing
      // a clear that cleared nothing.
      input.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        clearQuery(state);
      });
      if (clear) {
        clear.addEventListener('click', () => {
          if (!clearQuery(state)) return;
          // The control that was just used is on its way out; focus goes back to
          // the box the user is still working in, not to the body.
          input.focus();
        });
      }
    }
    paint(state);
    count += 1;
  });
  return count;
}

/**
 * The field as data: what is in the box, whether the way out is on screen, and
 * whether the field is mounted. Exposed for tests and for callers that need the
 * query without reading the input twice.
 */
export function searchFieldState(field) {
  if (!field || !field.matches?.('[data-search-field]')) return null;
  const state = stateOf(field);
  return state ? publicState(paint(state)) : null;
}
