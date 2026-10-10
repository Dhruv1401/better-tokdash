/**
 * TokDash v4 Animation System - Text reveal & morph
 *
 * Two named effects for the moments the tool is loading up, anchored to a real
 * signal rather than invented placeholder copy. The topbar status line
 * (`#lastUpdate`) begins life as a shimmering "Loading…" placeholder and, when
 * the dashboard resolves, is overwritten with real text — the success path
 * (`updateTimestamp`) writes "Last updated: HH:MM", the failure path
 * (`setDashboardFetchStatus`) writes the load-error detail. Both are the app's
 * own top-level functions, so this module wraps them exactly the way the
 * announcement bar wraps `renderUpdateBadge`: the app still writes the value it
 * always wrote, and the reveal rides along on top.
 *
 *   revealText  — the FIRST resolve (a loading label becomes real text): each
 *                 character unveils in a staggered rise, then settles to the
 *                 plain string so the DOM never keeps two copies and a reader
 *                 announces one value.
 *   morphText   — a LATER change (the timestamp rolls on a refresh, an error
 *                 replaces it): the old line cross-fades out as the new one
 *                 arrives, within the existing box so nothing below shifts.
 *
 * Reduced motion swaps the text instantly in both cases. There is no observer
 * and no global hook: only the two writers above are wrapped, so the blast
 * radius is the one element they share.
 */

const REVEAL_DUR = 340;
const REVEAL_STAGGER = 22;
const REVEAL_MAX_STEPS = 20;
const MORPH_DUR = 300;

const revealTimers = new WeakMap();
const morphTimers = new WeakMap();

function prefersReducedMotion() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Unveil `text` character by character, then settle to the plain string.
 *
 * Returns whether anything moved. A reveal writes the characters as inline
 * spans of the very same text, so the line's width never changes and nothing
 * under it shifts.
 */
export function revealText(element, text, { duration = REVEAL_DUR, stagger = REVEAL_STAGGER } = {}) {
  if (!element) return false;
  const value = text == null ? '' : String(text);
  element.dataset.revealPrev = value;
  if (!value) { element.textContent = ''; return false; }
  if (prefersReducedMotion()) { element.textContent = value; return false; }

  const chars = [...value];
  const frag = (element.ownerDocument || document).createDocumentFragment();
  chars.forEach((ch, index) => {
    const span = (element.ownerDocument || document).createElement('span');
    span.className = 'tokdash-reveal-char';
    // A space becomes a non-breaking span so it holds its box while invisible;
    // it settles back to a plain string anyway.
    span.textContent = ch === ' ' ? '\u00A0' : ch;
    span.style.setProperty('--rd', `${Math.min(index, REVEAL_MAX_STEPS) * stagger}ms`);
    frag.appendChild(span);
  });
  element.textContent = '';
  element.appendChild(frag);

  if (revealTimers.get(element)) clearTimeout(revealTimers.get(element));
  const settle = duration + Math.min(chars.length, REVEAL_MAX_STEPS) * stagger;
  revealTimers.set(element, setTimeout(() => {
    revealTimers.delete(element);
    // Only the current writer's text is kept: a newer render owns the element.
    if (element.dataset.revealPrev === value) element.textContent = value;
  }, settle));
  return true;
}

/**
 * Cross-fade `element` from its previous line to `next`, within the same box.
 *
 * `from` is the text that was on screen before the writer ran (the wrapper read
 * it first); left out, the element's current text is treated as the outgoing
 * line. The new text is the element's real text for the whole transition — the
 * outgoing copy is an aria-hidden overlay that fades up and away.
 */
export function morphText(element, next, { from, duration = MORPH_DUR } = {}) {
  if (!element) return false;
  const to = next == null ? '' : String(next);
  const prev = from != null ? String(from) : (element.textContent || '');
  element.dataset.revealPrev = to;
  if (prev === to) return false;
  if (prefersReducedMotion()) { element.textContent = to; return false; }

  const doc = element.ownerDocument || document;
  const outgoing = doc.createElement('span');
  outgoing.className = 'tokdash-morph-out';
  outgoing.setAttribute('aria-hidden', 'true');
  outgoing.textContent = prev;

  element.textContent = to;
  element.classList.add('tokdash-morph', 'is-morphing');
  element.insertBefore(outgoing, element.firstChild);

  if (morphTimers.get(element)) clearTimeout(morphTimers.get(element));
  morphTimers.set(element, setTimeout(() => {
    morphTimers.delete(element);
    element.classList.remove('is-morphing', 'tokdash-morph');
    outgoing.remove();
  }, duration + 60));
  return true;
}

/** The element as data, for tests. */
export function textRevealState(element) {
  if (!element) return null;
  return {
    revealing: !!revealTimers.get(element),
    morphing: !!morphTimers.get(element),
    hasOutgoing: !!element.querySelector('.tokdash-morph-out'),
    revealChars: element.querySelectorAll('.tokdash-reveal-char').length,
    text: element.textContent,
    prev: element.dataset.revealPrev ?? null,
  };
}

function wrapStatusWriter(global, name) {
  const original = global[name];
  if (typeof original !== 'function' || original.__tokdashTextReveal) return;
  const wrapper = function (...args) {
    const el = global.document ? global.document.getElementById('lastUpdate') : null;
    // Read the "before" state BEFORE the app overwrites it: whether this call is
    // the first resolve (a loading label is still present) decides reveal vs morph.
    const before = el ? (el.dataset.revealPrev ?? el.textContent ?? '') : '';
    const wasLoading = !!(el && el.querySelector('.tokdash-loading-label'));
    const result = original.apply(this, args);
    try {
      if (el) {
        const after = el.textContent || '';
        if (after && after !== before) {
          if (wasLoading) revealText(el, after);
          else morphText(el, after, { from: before });
        }
      }
    } catch (_) { /* the status stays exactly as the app wrote it */ }
    return result;
  };
  wrapper.__tokdashTextReveal = true;
  global[name] = wrapper;
}

/**
 * Wrap the app's two `#lastUpdate` writers so the topbar status reveals on the
 * first resolve and morphs on every later change. Idempotent. A host without
 * either function is left untouched.
 */
export function mountTextReveal() {
  if (typeof window === 'undefined') return false;
  wrapStatusWriter(window, 'updateTimestamp');
  wrapStatusWriter(window, 'setDashboardFetchStatus');
  return true;
}

export default { mountTextReveal, revealText, morphText, textRevealState };
