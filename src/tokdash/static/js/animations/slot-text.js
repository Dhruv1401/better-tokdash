/**
 * TokDash v4 Animation System - Slot text
 *
 * A figure that changes should change where it changed. Written as plain text,
 * "4.7B" becoming "144.2B" is one string replaced by another: the browser repaints
 * the whole line and the eye has to re-read it from the start — and because the
 * new string is longer, everything after it in the row moves.
 *
 * Slot text is the same change seen character by character. Each position owns a
 * slot as wide as the wider of the two characters it holds, and keeps that width
 * for the whole morph, so the characters that did not change do not move at all
 * and the ones that did roll over in place. The element's plain text goes back
 * when the morph lands, so the DOM never keeps two copies of the figure, a reader
 * announces one value, and anything that reads `textContent` afterwards reads the
 * figure itself rather than the animation.
 *
 * The old character leaves upward while the new one arrives from below, with a
 * per-slot delay so the change reads as a wave across the digits instead of a
 * single flip. Everything is disabled under `prefers-reduced-motion`, where the
 * new text is simply written.
 */

// The morph's own clock, in one place: the CSS reads the duration and the delay
// from these numbers, so the stylesheet cannot drift out of step with the timer
// that puts the plain text back.
const MORPH_MS = 240;
const STAGGER_MS = 22;
const MAX_STAGGER_STEPS = 6;

let sequence = 0;
// Element -> the morph currently allowed to settle. A second render, or a writer
// that replaced the content outright, invalidates the first one.
const active = new WeakMap();

function prefersReducedMotion() {
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Width of every distinct character, measured in the element's own font.
 *
 * Measured rather than assumed: the value is monospace today, but a themed card
 * may not be, and a slot sized from the wrong advance width is exactly the jump
 * this component exists to remove. A space measures as a space because the probe
 * keeps `white-space: pre`.
 */
function measureCharacters(element, characters) {
  const doc = element.ownerDocument || document;
  const styles = getComputedStyle(element);
  const probe = doc.createElement('span');
  probe.setAttribute('aria-hidden', 'true');
  probe.style.cssText = 'position:absolute;left:-9999px;top:0;visibility:hidden;white-space:pre;pointer-events:none;';
  probe.style.fontFamily = styles.fontFamily;
  probe.style.fontSize = styles.fontSize;
  probe.style.fontWeight = styles.fontWeight;
  probe.style.fontStyle = styles.fontStyle;
  probe.style.letterSpacing = styles.letterSpacing;
  probe.style.fontVariantNumeric = styles.fontVariantNumeric;
  (doc.body || doc.documentElement).appendChild(probe);

  const widths = new Map();
  characters.forEach((character) => {
    if (widths.has(character)) return;
    probe.textContent = character;
    widths.set(character, probe.getBoundingClientRect().width);
  });
  probe.remove();
  return widths;
}

/**
 * The line the slots have to occupy, in pixels.
 *
 * A slot is an inline-block with `overflow: hidden`, and an inline-block like that
 * takes its baseline from its bottom margin edge rather than from the text inside
 * it — so left on the baseline a 30px slot hangs 30px above the text baseline, the
 * line box grows by the descender, and the card under it moves. The slot is aligned
 * to the top of the line box instead and given this exact height, which is why the
 * height is measured here rather than written as a constant: the value line is 30px
 * in a card, 24px for a text-kind value and 26px in a bare cell.
 */
function lineHeightOf(element) {
  const reported = parseFloat(getComputedStyle(element).lineHeight);
  if (Number.isFinite(reported) && reported > 0) return reported;
  return Math.round((parseFloat(getComputedStyle(element).fontSize) || 16) * 1.4);
}

function buildSlots(element, previous, next) {
  const doc = element.ownerDocument || document;
  const characters = [...new Set([...previous, ...next])];
  const widths = measureCharacters(element, characters);
  element.style.setProperty('--metric-slot-h', `${lineHeightOf(element)}px`);
  const wrap = doc.createElement('span');
  wrap.className = 'metric-slot-text';
  wrap.setAttribute('aria-hidden', 'true');
  let changed = 0;

  for (let index = 0; index < Math.max(previous.length, next.length); index += 1) {
    const before = previous[index] || '';
    const after = next[index] || '';
    if (before === after) {
      // An unchanged character is written as itself: no slot, no motion, and the
      // line cannot reflow because this character never moved.
      wrap.appendChild(doc.createTextNode(after));
      continue;
    }
    const width = Math.max(widths.get(before) || 0, widths.get(after) || 0);
    const slot = doc.createElement('span');
    slot.className = 'metric-slot';
    slot.style.width = `${width}px`;
    slot.style.setProperty('--slot-duration', `${MORPH_MS}ms`);
    slot.style.setProperty('--slot-delay', `${Math.min(changed, MAX_STAGGER_STEPS) * STAGGER_MS}ms`);
    if (before) {
      const leaving = doc.createElement('span');
      leaving.className = 'metric-slot-char';
      leaving.dataset.role = 'old';
      leaving.textContent = before;
      slot.appendChild(leaving);
    }
    const arriving = doc.createElement('span');
    arriving.className = 'metric-slot-char';
    arriving.dataset.role = 'new';
    arriving.textContent = after;
    slot.appendChild(arriving);
    wrap.appendChild(slot);
    changed += 1;
  }
  return { wrap, changed };
}

/**
 * Morph `element`'s text from `options.from` to `next`, character by character.
 *
 * `from` is passed in rather than read off the element because a writer has
 * already replaced the text before this runs: what is on screen is the new value,
 * and the old one only exists in the caller's bookkeeping. Left out, the last text
 * this element was rendered with is used, and an element that has never been
 * rendered shows its new value with nothing to animate.
 *
 * Returns whether anything moved. An unchanged value is not a change at all, and
 * an element showing its first figure has no previous figure to leave.
 */
export function renderSlotText(element, next, options = {}) {
  if (!element) return false;
  const text = next == null ? '' : String(next);
  const fallback = element.dataset.slotTextPrev;
  const previous = options.from != null ? String(options.from) : (fallback != null ? fallback : text);
  if (previous === text) {
    element.dataset.slotTextPrev = text;
    return false;
  }
  if (prefersReducedMotion() || options.animate === false) {
    element.textContent = text;
    element.dataset.slotTextPrev = text;
    return false;
  }

  const id = (sequence += 1);
  active.set(element, { id, text });
  const { wrap, changed } = buildSlots(element, previous, text);
  element.textContent = '';
  element.appendChild(wrap);
  element.dataset.slotTextPrev = text;
  // One style pass with the slots in their starting state, so the flip below has
  // something to move from rather than snapping to the end.
  void element.offsetWidth;
  wrap.querySelectorAll('.metric-slot').forEach((slot) => {
    slot.dataset.arriving = 'true';
    slot.dataset.leaving = 'true';
  });

  const settleAfter = MORPH_MS + Math.min(changed, MAX_STAGGER_STEPS) * STAGGER_MS + 40;
  setTimeout(() => {
    // A newer value, or a writer that replaced the content while this ran, owns
    // the element now: the plain text is written by whoever is current.
    if (active.get(element)?.id !== id) return;
    active.delete(element);
    element.textContent = text;
    element.dataset.slotTextPrev = text;
  }, settleAfter);
  return true;
}

/** Whether a morph is on screen, and how much of it moved. Exposed for tests. */
export function slotTextState(element) {
  if (!element) return null;
  const wrap = element.querySelector('.metric-slot-text');
  return {
    morphing: !!wrap,
    slots: wrap ? wrap.querySelectorAll('.metric-slot').length : 0,
    settled: !wrap,
    text: element.textContent,
    target: element.dataset.slotTextPrev ?? null,
  };
}
