/**
 * TokDash v4 Animation System - Animated counter
 *
 * When a range switch or a refresh replaces one figure with another of the same
 * kind — 4.7B becoming 144.2B, $10,091.56 becoming $294,687.27 — a slot morph
 * shows the change but not its *size*. A count shows both: the figure travels from
 * where it was to where it is, and the direction of travel is legible in a way two
 * static readings are not.
 *
 * What counts is the number, not the string. The figure is split once into the unit
 * around it and the number inside it, the intermediate frames are rendered with the
 * app's own locale formatter (the same one the writer used, so a frame is never in
 * a different number style than the value it lands on), and the last frame writes
 * the target string *verbatim* — the counter cannot settle a rounding away from the
 * figure the API returned.
 *
 * Two figures are only countable as a pair: different units ("5/31" and "235/365")
 * or a different shape (a date, a model name) fall to slot text instead, because
 * counting between two unrelated numbers is a made-up quantity.
 */

// Long enough to read the travel, short enough that a range switch does not feel
// like it is waiting on the card.
const COUNT_MS = 520;
// A frame every 16ms is 60fps's budget. Driven by a timer rather than
// requestAnimationFrame so the count also runs where frames are not being painted —
// a background tab, a headless check — and so the settle is observable rather than
// implied by a paint that never came.
const FRAME_MS = 16;
// Beyond this the count is a blur of digits nobody can read as progress.
const MAX_MAGNITUDE = 1e15;

const runs = new WeakMap();

function prefersReducedMotion() {
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Which character the app's formatter groups with, and which it points decimals
 * with, learned by formatting one number through it.
 *
 * Read rather than assumed, because "1,234" is a thousand in en and one and a bit
 * in most of Europe, and a counter that misreads a figure counts to the wrong
 * place before landing on the right one. A locale that groups nothing reports no
 * grouping separator, which is a fact about it and not a failure.
 */
export function figureSeparators(format) {
  if (typeof format !== 'function') return null;
  let sample = '';
  try {
    sample = String(format(1234567.5));
  } catch (_) {
    return null;
  }
  const marks = [...sample.matchAll(/[^\d]/g)].map((mark) => ({ char: mark[0], index: mark.index }));
  if (!marks.length) return { group: '', decimal: '' };
  const tail = marks[marks.length - 1];
  const afterTail = sample.slice(tail.index + 1);
  // "1,234,567.5": the last mark precedes a single digit, so it points decimals and
  // whatever character repeats earlier is the grouping one. "1.234.567,5" reads the
  // same way with the roles swapped, without knowing which locale this is.
  const decimal = /^\d{1,3}$/.test(afterTail) ? tail.char : '';
  const group = marks.map((mark) => mark.char).find((char) => char !== decimal) || '';
  return { group, decimal };
}

/**
 * A figure split into the text around its number and the number itself.
 *
 * Returns null for anything without digits on both ends, which is what excludes
 * dates, weekday names and model names from being counted. `separators` is what
 * `figureSeparators` read out of the app's formatter; without it the separators are
 * guessed from the text, and a four-digit grouped number can only be read one way.
 */
export function parseFigure(text, separators = null) {
  const value = text == null ? '' : String(text);
  const first = value.search(/\d/);
  const last = value.search(/\d(?=[^\d]*$)/);
  if (first < 0 || last < 0 || last < first) return null;
  const prefix = value.slice(0, first);
  const body = value.slice(first, last + 1);
  const suffix = value.slice(last + 1);

  let decimal = separators && typeof separators.decimal === 'string' ? separators.decimal : null;
  if (decimal == null || !decimal) {
    // No formatter to ask: a mark followed by one or two digits points decimals;
    // a mark followed by exactly three is grouping when digits precede it.
    const marks = [...body.matchAll(/[^\d]/g)];
    const tail = marks[marks.length - 1];
    const afterTail = tail ? body.slice(tail.index + 1) : '';
    const beforeTail = tail ? body.slice(0, tail.index) : '';
    const looksGrouped = afterTail.length === 3 && beforeTail.replace(/\D/g, '').length > 0;
    decimal = tail && !looksGrouped ? tail[0] : '.';
  }
  const decimalAt = decimal ? body.lastIndexOf(decimal) : -1;
  const fraction = decimalAt >= 0 ? body.slice(decimalAt + 1) : '';
  const fractional = decimalAt >= 0 && /^\d{1,6}$/.test(fraction) ? fraction : '';
  const wholePart = fractional ? body.slice(0, decimalAt) : body;
  // Only characters that can be a grouping separator are removed, and everything
  // else inside the number disqualifies it. "5/31" and "235/365" look countable
  // once a slash is stripped — the counter would read 531 and travel to 235365 —
  // and no reading of that is a quantity anybody asked for.
  const knownGroup = separators && typeof separators.group === 'string' ? separators.group : '';
  const groupChars = knownGroup ? [knownGroup] : [',', '.', '\u00a0', '\u202f', ' '];
  const whole = [...wholePart].filter((char) => !groupChars.includes(char)).join('');
  if (!/^\d+$/.test(whole)) return null;
  const number = Number(fractional ? `${whole}.${fractional}` : `${whole}`);
  if (!Number.isFinite(number)) return null;
  return {
    prefix,
    suffix,
    number,
    decimals: fractional.length,
  };
}

/** Whether two figures are the same kind of quantity, so counting is honest. */
export function countablePair(from, to, separators = null) {
  const before = parseFigure(from, separators);
  const after = parseFigure(to, separators);
  if (!before || !after) return null;
  if (before.prefix !== after.prefix || before.suffix !== after.suffix) return null;
  if (!Number.isFinite(before.number) || !Number.isFinite(after.number)) return null;
  if (before.number === after.number) return null;
  if (Math.abs(before.number) > MAX_MAGNITUDE || Math.abs(after.number) > MAX_MAGNITUDE) return null;
  return { from: before, to: after };
}

function easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3);
}

/**
 * Count `element`'s figure from `options.from` to `next`.
 *
 * `options.format` renders an intermediate frame (a number in, a string out) and
 * should be the app's own number formatter. It is also what says how the figure's
 * separators are read, unless `options.separators` already carries that. Without a
 * formatter frames are plain decimal text, which is still correct and only less
 * localised. Returns whether a count ran.
 */
export function renderCountedValue(element, next, options = {}) {
  if (!element) return false;
  const text = next == null ? '' : String(next);
  const format = typeof options.format === 'function' ? options.format : null;
  const separators = options.separators || figureSeparators(format);
  const pair = countablePair(options.from != null ? options.from : text, text, separators);
  if (!pair) return false;
  if (prefersReducedMotion() || options.animate === false) {
    element.textContent = text;
    return false;
  }

  const duration = Number.isFinite(options.duration) ? options.duration : COUNT_MS;
  const id = Symbol('count');
  const run = { id, target: text, timer: null };
  runs.set(element, run);
  const started = performance.now();
  const point = (separators && separators.decimal) || '.';
  // A frame keeps the target's own number of decimal places. Handing the fraction
  // to the formatter would drop its trailing zeros, so the fraction is written here
  // and only the whole part is formatted — which is also the only part that groups.
  const frame = (value) => {
    if (pair.to.decimals > 0) {
      const [whole, fraction] = value.toFixed(pair.to.decimals).split('.');
      return `${format ? format(Number(whole)) : whole}${point}${fraction}`;
    }
    const rounded = Math.round(value);
    return format ? format(rounded) : String(rounded);
  };

  const tick = () => {
    // A newer figure, or a writer that replaced the content, owns this slot now.
    if (runs.get(element)?.id !== id) return;
    const elapsed = performance.now() - started;
    const progress = Math.min(1, elapsed / duration);
    if (progress >= 1) {
      runs.delete(element);
      // The target verbatim: whatever the formatter would have said, this is the
      // figure the writer wrote, and it is what the card is left showing.
      element.textContent = text;
      return;
    }
    const value = pair.from.number + (pair.to.number - pair.from.number) * easeOutCubic(progress);
    element.textContent = `${pair.to.prefix}${frame(value)}${pair.to.suffix}`;
    run.timer = setTimeout(tick, FRAME_MS);
  };
  // First frame immediately, so the card does not sit on the old figure for a tick.
  element.textContent = `${pair.to.prefix}${frame(pair.from.number)}${pair.to.suffix}`;
  run.timer = setTimeout(tick, FRAME_MS);
  return true;
}

/** Whether a count is running, and where it is going. Exposed for tests. */
export function counterState(element) {
  if (!element) return null;
  const run = runs.get(element);
  return run
    ? { counting: true, target: run.target, shown: element.textContent }
    : { counting: false, target: null, shown: element.textContent };
}
