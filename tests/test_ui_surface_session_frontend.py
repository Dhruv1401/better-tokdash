"""One session through every surface the UI work shipped, on one page state.

Each surface has its own test, and each of those tests mounts its module against
a stub DOM built for that module alone. Nothing walks them *together*, so nothing
would catch a surface breaking its neighbour: two layers claiming the same id, a
second mount stacking listeners on a trigger the first already owns, a key written
under a name another surface also uses, a mount order that attaches a hint twice,
or a surface that works alone and stops working once the settings dialog is up.

This file is that walk. It builds one page with the markup the app really has —
the same ids, classes and data attributes, taken from `index.html` — mounts every
module from the barrel the page imports, and then does what a session does:
load with a skeleton, resolve the status line, read the cards, hover a hint, open
the refresh report, clear a search, drag a switch, move the range, open the
calendar, open settings, change the theme, dismiss an announcement, drag a column
divider, and reload. Assertions are on the observable contracts the modules expose
(`*State`, the rendered boxes, what landed in `localStorage`, whether an event was
stopped) rather than on markup presence, and the closing block asserts the
invariants that only exist *between* surfaces: one shared layer each, mounts that
are idempotent, a key space that does not collide, and a reload that restores
everything the session chose.

Motion is deliberately out of the oracle's reach: this is a state walk. The one
place timing is awaited is where a module's own contract is delivered by a timer
(`onComplete` clearing a residual transform, a count settling on its target), and
what is asserted there is the end state, not the smoothing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import tokdash

STATIC = Path(tokdash.__file__).parent / "static"
MODULES = STATIC / "js" / "animations"
BARREL = MODULES / "index.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available"
)


def _plain(text: str) -> str:
    """The reveal holds its spaces open with a no-break space: read the words."""
    return text.replace("\u00a0", " ")

_HARNESS = r"""
// ---------------------------------------------------------------------------
// A mini-DOM. Small, but a real one: a tree, attributes, text nodes, and event
// dispatch that runs capture listeners before target listeners and stops when
// asked to. The dialog's scrim guard and the theme grid's press tracking are
// capture-phase behaviour, so a stubbed addEventListener would not exercise them.
// ---------------------------------------------------------------------------

const TEXT_NODE = 3;
const ELEMENT_NODE = 1;

function splitTop(text, separator) {
  const parts = [];
  let depth = 0;
  let bracket = 0;
  let current = '';
  for (const char of text) {
    if (char === '(') depth += 1;
    if (char === ')') depth -= 1;
    if (char === '[') bracket += 1;
    if (char === ']') bracket -= 1;
    if (char === separator && depth === 0 && bracket === 0) {
      parts.push(current);
      current = '';
      continue;
    }
    current += char;
  }
  parts.push(current);
  return parts;
}

function parseCompound(text) {
  const compound = { tag: null, id: null, classes: [], attrs: [], nots: [], scope: false };
  let rest = text.trim();
  while (rest.length) {
    const char = rest[0];
    if (char === ':') {
      const not = rest.match(/^:not\((.*)\)/);
      if (not) {
        compound.nots.push(parseCompound(not[1].replace(/^:scope\s*>\s*/, '')));
        rest = rest.slice(not[0].length);
        continue;
      }
      const pseudo = rest.match(/^:scope/);
      if (pseudo) {
        compound.scope = true;
        rest = rest.slice(pseudo[0].length);
        continue;
      }
      rest = rest.replace(/^:[a-z-]+/, '');
      continue;
    }
    if (char === '.') {
      const match = rest.match(/^\.([A-Za-z0-9_-]+)/);
      compound.classes.push(match[1]);
      rest = rest.slice(match[0].length);
      continue;
    }
    if (char === '#') {
      const match = rest.match(/^#([A-Za-z0-9_-]+)/);
      compound.id = match[1];
      rest = rest.slice(match[0].length);
      continue;
    }
    if (char === '[') {
      const match = rest.match(/^\[([^\]]*)\]/);
      const body = match[1];
      const equals = body.indexOf('=');
      if (equals < 0) {
        compound.attrs.push({ name: body.trim(), value: null, operator: '=' });
      } else {
        const rawName = body.slice(0, equals).trim();
        const substring = rawName.endsWith('*');
        const value = body.slice(equals + 1).trim().replace(/^["']|["']$/g, '');
        compound.attrs.push({
          name: substring ? rawName.slice(0, -1).trim() : rawName,
          value,
          operator: substring ? '*=' : '=',
        });
      }
      rest = rest.slice(match[0].length);
      continue;
    }
    const tag = rest.match(/^[A-Za-z][A-Za-z0-9-]*/);
    if (!tag) {
      rest = rest.slice(1);
      continue;
    }
    compound.tag = tag[0].toLowerCase();
    rest = rest.slice(tag[0].length);
  }
  return compound;
}

function parseComplex(text) {
  const tokens = [];
  let child = false;
  splitTop(text.trim(), '>').forEach((chunk, index) => {
    if (index > 0) child = true;
    const selector = chunk.trim();
    if (!selector) return;
    tokens.push({ selector, child });
    child = false;
  });
  // A `>` inside a longer selector ("a > b > c") arrives as one chunk per `>`,
  // so re-mark the following token when the chunk ended with a combinator.
  const rebuilt = [];
  tokens.forEach((token, index) => {
    const trimmed = token.selector.trim();
    if (!trimmed) return;
    rebuilt.push({ selector: trimmed, child: token.child || (index > 0 && /\s>\s*$/.test(tokens[index - 1].selector)) });
  });
  return rebuilt;
}

function matchCompound(scopeEl, el, compound) {
  if (compound.scope && el !== scopeEl) return false;
  if (compound.tag && String(el.tagName || '').toLowerCase() !== compound.tag) return false;
  if (compound.id && el.getAttribute('id') !== compound.id) return false;
  for (const name of compound.classes) {
    if (!el.classList.contains(name)) return false;
  }
  for (const attr of compound.attrs) {
    if (!el.hasAttribute(attr.name)) return false;
    if (attr.value === null) continue;
    const actual = el.getAttribute(attr.name) || '';
    if (attr.operator === '*=' ? !actual.includes(attr.value) : actual !== attr.value) return false;
  }
  for (const not of compound.nots) {
    if (matchCompound(scopeEl, el, not)) return false;
  }
  return true;
}

function matchesComplex(scopeEl, el, tokens) {
  if (!tokens.length) return false;
  const last = tokens[tokens.length - 1];
  if (!matchCompound(scopeEl, el, parseCompound(last.selector))) return false;
  let node = el;
  for (let index = tokens.length - 2; index >= 0; index -= 1) {
    const token = tokens[index];
    const compound = parseCompound(token.selector);
    if (last.childAt === index) return false;
    if (tokens[index + 1].child) {
      node = node.parentNode;
      if (!node || node.nodeType !== ELEMENT_NODE || !matchCompound(scopeEl, node, compound)) return false;
    } else {
      let up = node.parentNode;
      let found = null;
      while (up && up.nodeType === ELEMENT_NODE) {
        if (matchCompound(scopeEl, up, compound)) { found = up; break; }
        up = up.parentNode;
      }
      if (!found) return false;
      node = found;
    }
  }
  return true;
}

function parseSelectorGroups(selector) {
  return splitTop(selector, ',').map((part) => parseComplex(part)).filter((tokens) => tokens.length);
}

function descendantsOf(root, list = []) {
  (root.children || []).forEach((child) => {
    if (child.nodeType !== ELEMENT_NODE) return;
    list.push(child);
    descendantsOf(child, list);
  });
  return list;
}

// ---------------------------------------------------------------------------
// Just enough HTML to read markup the modules write with innerHTML: the
// calendar's day grid and weekday row, the toast's icon, a tile's check. A
// browser parses that string into elements, so a mini-DOM that only remembers
// the string cannot see the surface at all -- and the grid is exactly what the
// picker's contract is made of.
// ---------------------------------------------------------------------------

const VOID_TAGS = new Set([
  'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
  'param', 'source', 'track', 'wbr', 'path', 'circle', 'line', 'polyline',
  'polygon', 'rect', 'stop', 'use', 'ellipse',
]);

function decodeEntities(text) {
  return String(text)
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, '\u00a0')
    .replace(/&amp;/g, '&');
}

function elementFromToken(doc, token) {
  const body = token.slice(1).replace(/\/?>$/, '');
  const name = (body.match(/^[A-Za-z][A-Za-z0-9-]*/) || ['div'])[0];
  const node = doc.createElement(name);
  const attrPattern = /([^\s=/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
  let match = attrPattern.exec(body.slice(name.length));
  while (match) {
    if (match[1]) node.setAttribute(match[1], decodeEntities(match[2] ?? match[3] ?? match[4] ?? ''));
    match = attrPattern.exec(body.slice(name.length));
  }
  return node;
}

function parseHTML(doc, html) {
  const fragment = doc.createElement('#fragment');
  const stack = [fragment];
  const tokens = String(html).match(/<[^>]*>|[^<]+/g) || [];
  tokens.forEach((token) => {
    if (token[0] !== '<') {
      const text = decodeEntities(token);
      if (text) stack[stack.length - 1].appendChild(doc.createTextNode(text));
      return;
    }
    if (token.startsWith('</')) {
      if (stack.length > 1) stack.pop();
      return;
    }
    const name = (token.slice(1).match(/^[A-Za-z][A-Za-z0-9-]*/) || [''])[0];
    const node = elementFromToken(doc, token);
    stack[stack.length - 1].appendChild(node);
    if (!/\/>$/.test(token) && !VOID_TAGS.has(name.toLowerCase())) stack.push(node);
  });
  return fragment;
}

let orderCounter = 0;
function documentOrder(doc) {
  const order = new Map();
  orderCounter = 0;
  const walk = (node) => {
    order.set(node, (orderCounter += 1));
    (node.children || []).forEach((child) => {
      if (child.nodeType === ELEMENT_NODE) walk(child);
    });
  };
  walk(doc.documentElement);
  return order;
}

class StyleDecl {
  constructor() { this._props = new Map(); }
  setProperty(name, value) { this._props.set(String(name), String(value)); }
  getPropertyValue(name) {
    if (this._props.has(name)) return this._props.get(name);
    const inline = this[name];
    return inline === undefined || inline === null ? '' : String(inline);
  }
  removeProperty(name) { this._props.delete(String(name)); }
  get cssText() { return [...this._props].map(([key, value]) => `${key}: ${value}`).join('; '); }
  set cssText(text) {
    this._props = new Map();
    String(text || '').split(';').forEach((chunk) => {
      const at = chunk.indexOf(':');
      if (at > 0) this._props.set(chunk.slice(0, at).trim(), chunk.slice(at + 1).trim());
    });
  }
}

class DomEvent {
  constructor(type, init = {}) {
    Object.assign(this, init);
    this.type = type;
    this.bubbles = Boolean(init.bubbles);
    this.cancelable = Boolean(init.cancelable);
    this.defaultPrevented = false;
    this.__stopped = false;
    this.__immediate = false;
    this.target = null;
    this.currentTarget = null;
  }
  preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
  stopPropagation() { this.__stopped = true; }
  stopImmediatePropagation() { this.__stopped = true; this.__immediate = true; }
  composedPath() { return this.__path || []; }
}

class MouseEvent extends DomEvent {}
class PointerEvent extends DomEvent {}
class KeyboardEvent extends DomEvent {}
class CustomEvent extends DomEvent {}

class TextNode {
  constructor(data, doc) {
    this.nodeType = TEXT_NODE;
    this.data = String(data);
    this.ownerDocument = doc;
    this.parentNode = null;
    this.children = [];
  }
  get textContent() { return this.data; }
  set textContent(value) { this.data = String(value); }
  get isConnected() { return Boolean(this.parentNode); }
}

class El {
  constructor(tag, doc) {
    this.nodeType = ELEMENT_NODE;
    this.tagName = String(tag).toUpperCase();
    this.ownerDocument = doc;
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.listeners = new Map();
    this.style = new StyleDecl();
    this.computed = new Map();
    this.tabIndex = 0;
    this.text = '';
    this.rect = { x: 0, y: 0, width: 120, height: 24, top: 0, left: 0, right: 120, bottom: 24 };
    const self = this;
    this.classList = {
      add: (...names) => names.forEach((name) => self.#classes().add(name)),
      remove: (...names) => names.forEach((name) => self.#classes().delete(name)),
      toggle: (name, force) => {
        const on = force === undefined ? !self.classList.contains(name) : Boolean(force);
        if (on) self.classList.add(name);
        else self.classList.remove(name);
        return on;
      },
      contains: (name) => self.#classes().has(name),
    };
    this.dataset = new Proxy({}, {
      get: (_, key) => self.getAttribute(attributeNameOf(key)),
      set: (_, key, value) => {
        if (value === undefined) self.removeAttribute(attributeNameOf(key));
        else self.setAttribute(attributeNameOf(key), String(value));
        return true;
      },
      deleteProperty: (_, key) => { self.removeAttribute(attributeNameOf(key)); return true; },
      has: (_, key) => self.hasAttribute(attributeNameOf(key)),
    });
  }
  #classes() {
    if (!this._classes) this._classes = new Set();
    return this._classes;
  }
  get className() { return [...this.#classes()].join(' '); }
  set className(value) {
    this._classes = new Set(String(value || '').split(/\s+/).filter(Boolean));
  }
  get id() { return this.getAttribute('id') || ''; }
  set id(value) { this.setAttribute('id', value); }
  get hidden() { return this.hasAttribute('hidden'); }
  set hidden(value) { if (value) this.setAttribute('hidden', ''); else this.removeAttribute('hidden'); }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children[this.children.length - 1] || null; }
  get childNodes() { return this.children; }
  get previousSibling() {
    if (!this.parentNode) return null;
    const index = this.parentNode.children.indexOf(this);
    return index > 0 ? this.parentNode.children[index - 1] : null;
  }
  get nextSibling() {
    if (!this.parentNode) return null;
    const index = this.parentNode.children.indexOf(this);
    return this.parentNode.children[index + 1] || null;
  }
  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node === this.ownerDocument || node === this.ownerDocument.documentElement;
  }
  get parentElement() { return this.parentNode && this.parentNode.nodeType === ELEMENT_NODE ? this.parentNode : null; }
  get textContent() {
    if (this.children.length) return this.children.map((child) => child.textContent).join('');
    return this.text;
  }
  set textContent(value) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    this.text = value == null ? '' : String(value);
  }
  get innerHTML() { return this._innerHTML != null ? this._innerHTML : this.textContent; }
  set innerHTML(value) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    this.text = '';
    this._innerHTML = String(value);
    this.appendChild(parseHTML(this.ownerDocument, value));
  }
  get outerHTML() { return this.innerHTML; }
  getAttribute(name) {
    if (name === 'class') return this.className || null;
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }
  setAttribute(name, value) {
    if (name === 'class') { this.className = String(value); return; }
    const text = String(value);
    this.attributes.set(name, text);
    // The tabindex content attribute is what the platform's tabIndex IDL reads,
    // so the picker's roving tab stop is only visible here if they agree.
    if (name === 'tabindex') {
      const parsed = Number.parseInt(text, 10);
      this.tabIndex = Number.isFinite(parsed) ? parsed : 0;
    }
  }
  removeAttribute(name) {
    if (name === 'class') { this.className = ''; return; }
    if (name === 'tabindex') this.tabIndex = 0;
    this.attributes.delete(name);
  }
  hasAttribute(name) {
    if (name === 'class') return this.#classes().size > 0;
    return this.attributes.has(name);
  }
  appendChild(node) {
    if (!node) return node;
    if (node.tagName === '#FRAGMENT') {
      [...node.children].forEach((child) => this.appendChild(child));
      return node;
    }
    if (node.parentNode) node.parentNode.removeChild(node);
    node.parentNode = this;
    this.children.push(node);
    return node;
  }
  append(...nodes) { nodes.forEach((node) => this.appendChild(node)); }
  prepend(node) {
    if (node.parentNode) node.parentNode.removeChild(node);
    node.parentNode = this;
    this.children.unshift(node);
    return node;
  }
  insertBefore(node, reference) {
    if (!reference) return this.appendChild(node);
    if (node.parentNode) node.parentNode.removeChild(node);
    node.parentNode = this;
    const index = this.children.indexOf(reference);
    this.children.splice(index < 0 ? this.children.length : index, 0, node);
    return node;
  }
  removeChild(node) {
    const index = this.children.indexOf(node);
    if (index >= 0) this.children.splice(index, 1);
    node.parentNode = null;
    return node;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  replaceChildren(...nodes) {
    [...this.children].forEach((child) => { child.parentNode = null; });
    this.children = [];
    this.text = '';
    this.innerHTML = '';
    nodes.forEach((node) => this.appendChild(node));
  }
  replaceWith(node) {
    const parent = this.parentNode;
    if (parent) parent.insertBefore(node, this);
    this.remove();
  }
  before(node) { if (this.parentNode) this.parentNode.insertBefore(node, this); }
  after(node) {
    const parent = this.parentNode;
    if (!parent) return;
    const index = parent.children.indexOf(this);
    parent.children.splice(index + 1, 0, node);
    node.parentNode = parent;
  }
  matches(selector) {
    if (!selector) return false;
    return parseSelectorGroups(selector).some((tokens) => matchesComplex(this.ownerDocument.documentElement, this, tokens));
  }
  closest(selector) {
    let node = this;
    while (node && node.nodeType === ELEMENT_NODE) {
      if (node.matches(selector)) return node;
      node = node.parentNode;
    }
    return null;
  }
  contains(node) {
    let cursor = node || null;
    while (cursor) {
      if (cursor === this) return true;
      cursor = cursor.parentNode || null;
    }
    return false;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const doc = this.ownerDocument;
    const order = documentOrder(doc);
    const scopeEl = this;
    const found = new Set();
    parseSelectorGroups(selector).forEach((tokens) => {
      const needsRoot = tokens[0].selector.includes(':scope');
      const candidates = needsRoot ? [this, ...descendantsOf(this)] : descendantsOf(this);
      candidates.forEach((candidate) => {
        if (!matchesComplex(scopeEl, candidate, tokens)) return;
        found.add(candidate);
      });
    });
    return [...found].sort((a, b) => (order.get(a) || 0) - (order.get(b) || 0));
  }
  getBoundingClientRect() { return { ...this.rect }; }
  getClientRects() { return [this.getBoundingClientRect()]; }
  get offsetWidth() { return this.rect.width; }
  get offsetHeight() { return this.rect.height; }
  get offsetLeft() { return this.rect.left; }
  get offsetTop() { return this.rect.top; }
  get offsetParent() { return this.isConnected ? this.parentElement : null; }
  get clientWidth() { return this.rect.width; }
  get clientHeight() { return this.rect.height; }
  // A real <select> hands back its option list as an iterable collection, and
  // the theme switcher builds one tile per option from exactly that.
  get options() {
    if (this.tagName !== 'SELECT') return undefined;
    return this.querySelectorAll('option');
  }
  get scrollHeight() { return this.rect.height; }
  get scrollWidth() { return this.rect.width; }
  scrollTop = 0;
  scrollIntoView() {}
  addEventListener(type, fn, capture) {
    if (!fn) return;
    const list = this.listeners.get(type) || [];
    list.push({ fn, capture: capture === true });
    this.listeners.set(type, list);
  }
  removeEventListener(type, fn, capture) {
    const list = this.listeners.get(type) || [];
    this.listeners.set(type, list.filter((entry) => entry.fn !== fn || entry.capture !== (capture === true)));
  }
  dispatchEvent(event) {
    const path = [];
    let node = this;
    while (node) { path.push(node); node = node.parentNode || null; }
    const doc = this.ownerDocument;
    if (!path.includes(doc)) path.push(doc);
    path.push(doc.defaultView);
    event.__path = path;
    event.target = this;
    const invoke = (target, phase) => {
      const list = target.listeners ? target.listeners.get(event.type) : null;
      if (!list) return;
      event.currentTarget = target;
      for (const entry of [...list]) {
        if (phase === 'capture' && !entry.capture) continue;
        if (phase === 'bubble' && entry.capture) continue;
        entry.fn.call(target, event);
        if (event.__immediate) break;
      }
      event.currentTarget = null;
    };
    for (let index = path.length - 1; index >= 1 && !event.__stopped; index -= 1) invoke(path[index], 'capture');
    if (!event.__stopped) invoke(this, 'target');
    if (event.bubbles) {
      for (let index = 1; index < path.length && !event.__stopped; index += 1) invoke(path[index], 'bubble');
    }
    return !event.defaultPrevented;
  }
  click() { return this.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); }
  focus() {
    this.ownerDocument.activeElement = this;
    this.dispatchEvent(new DomEvent('focus'));
  }
  blur() {
    if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = this.ownerDocument.body;
    this.dispatchEvent(new DomEvent('blur'));
  }
  setPointerCapture() {}
  releasePointerCapture() {}
  hasPointerCapture() { return false; }
  animate() { return { cancel() {}, finished: Promise.resolve() }; }
}

function attributeNameOf(key) {
  return `data-${String(key).replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`;
}

class Document extends El {
  constructor() {
    super('#document', null);
    this.ownerDocument = this;
    this.documentElement = new El('html', this);
    this.body = new El('body', this);
    this.appendChild(this.documentElement);
    this.documentElement.appendChild(this.body);
    this.activeElement = this.body;
    this.defaultView = null;
    this.hidden = false;
  }
  createElement(tag) { return new El(tag, this); }
  createElementNS(_ns, tag) { return new El(tag, this); }
  createTextNode(data) { return new TextNode(data, this); }
  createDocumentFragment() { return new El('#fragment', this); }
  getElementById(id) { return this.querySelector(`#${id}`); }
  get parentNode() { return null; }
  set parentNode(_value) {}
}

class WindowTarget {
  constructor() {
    this.listeners = new Map();
    this.innerWidth = 1440;
    this.innerHeight = 900;
    this.devicePixelRatio = 1;
    this.PointerEvent = PointerEvent;
  }
  addEventListener(type, fn, capture) {
    const list = this.listeners.get(type) || [];
    list.push({ fn, capture: capture === true });
    this.listeners.set(type, list);
  }
  removeEventListener(type, fn, capture) {
    const list = this.listeners.get(type) || [];
    this.listeners.set(type, list.filter((entry) => entry.fn !== fn || entry.capture !== (capture === true)));
  }
  dispatchEvent(event) { return true; }
}

class Storage {
  constructor() { this.map = new Map(); }
  getItem(key) { return this.map.has(String(key)) ? this.map.get(String(key)) : null; }
  setItem(key, value) { this.map.set(String(key), String(value)); }
  removeItem(key) { this.map.delete(String(key)); }
  clear() { this.map.clear(); }
  key(index) { return [...this.map.keys()][index] ?? null; }
  get length() { return this.map.size; }
}

class ObserverStub {
  constructor(callback) { this.callback = callback; this.targets = []; }
  observe(target) { if (!this.targets.includes(target)) this.targets.push(target); }
  unobserve(target) { this.targets = this.targets.filter((each) => each !== target); }
  disconnect() { this.targets = []; }
  takeRecords() { return []; }
}

const intersectionObservers = [];
class IntersectionObserverStub extends ObserverStub {
  constructor(callback, options) { super(callback); this.options = options || {}; intersectionObservers.push(this); }
}
const resizeObservers = [];
class ResizeObserverStub extends ObserverStub {
  constructor(callback) { super(callback); resizeObservers.push(this); }
}
class MutationObserverStub extends ObserverStub {
  constructor(callback) { super(callback); this.records = []; }
}

let reducedMotion = false;
const mediaListeners = new Map();

function installGlobals(doc, win, storage) {
  globalThis.document = doc;
  globalThis.window = win;
  globalThis.localStorage = storage;
  win.document = doc;
  win.localStorage = storage;
  doc.defaultView = win;
  globalThis.Event = DomEvent;
  globalThis.MouseEvent = MouseEvent;
  globalThis.PointerEvent = PointerEvent;
  globalThis.KeyboardEvent = KeyboardEvent;
  globalThis.CustomEvent = CustomEvent;
  globalThis.HTMLElement = El;
  globalThis.Element = El;
  globalThis.Node = El;
  // The anime adapter that drives the loader only needs `instanceof` to tell a
  // collection from a single node, and this mini-DOM's querySelectorAll answers
  // with an Array; Array is therefore the faithful stand-in for both collection
  // interfaces rather than an invented class that would always fail the check.
  globalThis.NodeList = Array;
  globalThis.HTMLCollection = Array;
  globalThis.IntersectionObserver = IntersectionObserverStub;
  globalThis.ResizeObserver = ResizeObserverStub;
  globalThis.MutationObserver = MutationObserverStub;
  globalThis.requestAnimationFrame = (callback) => setTimeout(() => callback(performance.now()), 16);
  globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
  globalThis.getComputedStyle = (el) => {
    const computed = el.computed || new Map();
    return {
      position: computed.get('position') || (el.style.getPropertyValue('position') || 'static'),
      display: computed.get('display') || '',
      opacity: computed.get('opacity') || el.style.getPropertyValue('opacity') || '1',
      transform: el.style.getPropertyValue('transform') || 'none',
      fontFamily: computed.get('fontFamily') || 'monospace',
      fontSize: computed.get('fontSize') || '16px',
      fontWeight: computed.get('fontWeight') || '400',
      fontStyle: computed.get('fontStyle') || 'normal',
      lineHeight: computed.get('lineHeight') || '22px',
      letterSpacing: computed.get('letterSpacing') || 'normal',
      fontVariantNumeric: computed.get('fontVariantNumeric') || 'normal',
      width: computed.get('width') || `${el.rect.width}px`,
      height: computed.get('height') || `${el.rect.height}px`,
      getPropertyValue: (name) => computed.get(name) ?? el.style.getPropertyValue(name) ?? '',
    };
  };
  win.getComputedStyle = globalThis.getComputedStyle;
  win.matchMedia = (query) => {
    const matches = /prefers-reduced-motion/.test(query) ? reducedMotion : true;
    const entry = { matches, media: query };
    mediaListeners.set(query, mediaListeners.get(query) || []);
    return {
      ...entry,
      addEventListener(type, fn) { mediaListeners.get(query).push(fn); },
      removeEventListener() {},
      addListener(fn) { mediaListeners.get(query).push(fn); },
      removeListener() {},
    };
  };
  win.requestAnimationFrame = globalThis.requestAnimationFrame;
  win.cancelAnimationFrame = globalThis.cancelAnimationFrame;
  // Node defines `navigator` as a getter-only global, so the stub has to be
  // installed around it rather than assigned over it.
  const navigatorStub = { userAgent: 'node', language: 'en' };
  Object.defineProperty(globalThis, 'navigator', { value: navigatorStub, writable: true, configurable: true });
  win.navigator = navigatorStub;
}

// ---------------------------------------------------------------------------
// The page: the markup the app really has, so the modules meet the shape (ids,
// classes, data attributes) they were written against in index.html.
// ---------------------------------------------------------------------------

function el(doc, tag, options = {}) {
  const node = doc.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.id) node.id = options.id;
  if (options.text != null) node.textContent = options.text;
  Object.entries(options.attrs || {}).forEach(([name, value]) => node.setAttribute(name, value));
  Object.entries(options.data || {}).forEach(([name, value]) => { node.dataset[name] = value; });
  (options.children || []).forEach((child) => node.appendChild(child));
  return node;
}

// A trigger exactly the way index.html declares one: `data-tooltip`, plus the
// placement and the words (`data-tooltip-text` for the pieces that carry none).
function tooltipTrigger(doc, node, { placement = null, tooltipText = null, title = null } = {}) {
  node.dataset.tooltip = '';
  if (placement) node.setAttribute('data-tooltip-placement', placement);
  if (tooltipText != null) node.setAttribute('data-tooltip-text', tooltipText);
  if (title != null) node.setAttribute('title', title);
  return node;
}

const THEMES = [
  'classic', 'elevated', 'paper', 'liquid', 'vibrant', 'midnight', 'terminal', 'brutalist',
  'arcade', 'studio', 'obsidian', 'graphite', 'nordic', 'amber', 'navy', 'soft', 'flat',
];

// The same 8-step ramp shape the app ships: surface -> accent, per theme, per mode.
function themeConfig() {
  const heatColorsMap = {};
  THEMES.forEach((theme, index) => {
    const base = 24 + index * 11;
    heatColorsMap[theme] = {
      dark: Array.from({ length: 8 }, (_, step) => `hsl(${base} 60% ${12 + step * 5}%)`),
      light: Array.from({ length: 8 }, (_, step) => `hsl(${base} 60% ${92 - step * 6}%)`),
    };
  });
  return { heatColorsMap };
}

const APP_KEYS = {
  theme: 'tokdash-theme',
  legacy: 'tokdash-style-theme',
  announcement: 'tokdash-announcement-dismissed',
  split: 'tokdash-sessions-split',
};

function buildPage() {
  const doc = new Document();
  const win = new WindowTarget();
  const storage = new Storage();
  installGlobals(doc, win, storage);
  win.TOKDASH_THEME_CONFIG = themeConfig();

  const page = {};

  // Announcement bar: the slot the update check fills.
  page.announcementText = el(doc, 'p', { className: 'announcement-text' });
  page.announcementAction = el(doc, 'button', { className: 'announcement-action', text: 'Details' });
  page.announcementClose = el(doc, 'button', { className: 'announcement-close' });
  page.announcementBar = el(doc, 'div', {
    id: 'announcementBar',
    className: 'announcement-slot',
    data: { state: 'empty' },
    children: [el(doc, 'div', { className: 'announcement-bar', attrs: { role: 'status' }, children: [
      el(doc, 'div', { className: 'announcement-card', children: [page.announcementText, page.announcementAction, page.announcementClose] }),
    ] })],
  });
  page.body = doc.body;
  doc.body.appendChild(page.announcementBar);

  // Topbar: the refresh action button, its report panel, the status line.
  page.refreshBtn = el(doc, 'button', {
    id: 'refreshBtn',
    className: 'btn btn-primary action-btn',
    attrs: { 'aria-label': 'Refresh dashboard' },
    children: [el(doc, 'span', { className: 'action-btn-label', text: 'Refresh' })],
  });
  page.refreshReport = el(doc, 'section', {
    id: 'refreshReport',
    className: 'refresh-report',
    attrs: { role: 'status' },
  });
  page.refreshReport.hidden = true;
  page.lastUpdate = el(doc, 'p', {
    id: 'lastUpdate',
    className: 'tokdash-loading-placeholder',
    children: [el(doc, 'span', { className: 'tokdash-loading-label', text: 'Loading...' })],
  });
  const topbar = el(doc, 'header', { className: 'surface', children: [page.refreshBtn, page.refreshReport, page.lastUpdate] });
  doc.body.appendChild(topbar);

  // The skeleton the whole dashboard sits behind while it loads.
  page.loaderCore = el(doc, 'circle', { className: 'ap-core' });
  page.loaderRings = ['ap-r1', 'ap-r2', 'ap-r3', 'ap-halo'].map((name) => el(doc, 'circle', { className: name }));
  const loaderSvg = el(doc, 'svg', { className: 'ap', children: [page.loaderCore, ...page.loaderRings] });
  page.loader = el(doc, 'div', { id: 'tokdash-loader', children: [loaderSvg] });
  page.loader.hidden = true;
  doc.body.appendChild(page.loader);

  // Metric cards, with the hint chip the tooltip primitive adopts.
  page.tokenValue = el(doc, 'div', { id: 'statTotalTokens', className: 'metric-card-value', text: '1.2B' });
  page.tokenHint = tooltipTrigger(
    doc,
    el(doc, 'span', { className: 'metric-hint' }),
    { title: 'Tokens counted across every tool' },
  );
  page.modelValue = el(doc, 'div', { id: 'statFavoriteModel', className: 'metric-card-value', text: 'gpt-5.5' });
  page.costValue = el(doc, 'div', { id: 'statCost', className: 'metric-card-value', text: '$1,204.00' });
  page.cardsRoot = el(doc, 'section', { id: 'statsSummaryCards', children: [
    el(doc, 'div', { className: 'metric-card', data: { metricCard: '' }, children: [
      el(doc, 'span', { className: 'metric-card-label', text: 'Total Tokens' }),
      page.tokenValue,
      page.tokenHint,
    ] }),
    el(doc, 'div', { className: 'metric-card', data: { metricCard: '', valueKind: 'text' }, children: [
      el(doc, 'span', { className: 'metric-card-label', text: 'Top Model' }),
      page.modelValue,
      tooltipTrigger(doc, el(doc, 'span', { className: 'metric-card-hint', attrs: { tabindex: '0' } }), {
        title: 'The model you spent the most tokens on in this window.',
      }),
    ] }),
    el(doc, 'div', { className: 'metric-card', data: { metricCard: '' }, children: [
      el(doc, 'span', { className: 'metric-card-label', text: 'Cost' }),
      page.costValue,
      tooltipTrigger(doc, el(doc, 'span', { className: 'metric-card-hint', attrs: { tabindex: '0' } }), {
        title: 'Estimated spend across every tool in the selected range.',
      }),
    ] }),
  ] });
  doc.body.appendChild(page.cardsRoot);

  // Range switcher: every preset a segment of one control.
  page.segments = ['today', 'yesterday', 'last7days', 'lastWeek'].map((range) => el(doc, 'button', {
    className: 'range-switcher-segment',
    text: range,
    data: { range },
    attrs: { type: 'button', 'aria-pressed': range === 'today' ? 'true' : 'false' },
  }));
  page.rangeRoot = el(doc, 'div', {
    id: 'overviewQuickRanges',
    className: 'range-switcher',
    data: { rangeSwitcher: '' },
    children: page.segments,
  });
  doc.body.appendChild(page.rangeRoot);

  // Donut chart: a canvas inside its wrapper.
  page.donutCanvas = el(doc, 'canvas', { id: 'toolChart' });
  page.donutWrap = el(doc, 'div', { className: 'chart-wrap', children: [page.donutCanvas] });
  doc.body.appendChild(page.donutWrap);

  // The composition bar: four segments whose detail is a `data-tooltip-text`,
  // exactly as index.html declares them.
  page.compBars = ['Prompt Tokens', 'Cache Read Tokens', 'Output Tokens', 'Reasoning Tokens'].map((label) => tooltipTrigger(
    doc,
    el(doc, 'div', { className: 'composition-bar' }),
    { tooltipText: label },
  ));
  page.compRoot = el(doc, 'div', { id: 'compositionBar', className: 'flex h-full w-full', children: page.compBars });
  doc.body.appendChild(page.compRoot);

  // Activity heatmap: the profile band's cells, painted from the theme ramp.
  page.heatCells = [0, 1, 2, 3, 4, 2, 1, 0].map((level) => {
    const cell = el(doc, 'button', { className: 'profile-activity-cell', attrs: { role: 'gridcell' } });
    cell.dataset.level = String(level);
    return cell;
  });
  page.heatRoot = el(doc, 'div', { id: 'overviewProfileBand', className: 'overview-profile-band', children: page.heatCells });
  doc.body.appendChild(page.heatRoot);

  // Date range control: one trigger, one panel, one grid.
  page.drTrigger = tooltipTrigger(doc, el(doc, 'button', {
    id: 'dateRangeTrigger',
    className: 'date-range-trigger',
    attrs: { type: 'button', 'aria-haspopup': 'dialog', 'aria-expanded': 'false', title: 'Select range' },
    data: { daterangeTrigger: '' },
    children: [el(doc, 'strong', { text: 'Today' })],
  }), { placement: 'bottom' });
  page.drDays = el(doc, 'div', { className: 'date-range-days', data: { daterangeDays: '' }, attrs: { role: 'group' } });
  page.drPanel = el(doc, 'div', {
    className: 'date-range-panel',
    data: { daterangePanel: '' },
    attrs: { id: 'dateRangePanel', role: 'dialog', 'aria-label': 'Select range' },
    children: [
      el(doc, 'div', { className: 'date-range-head', children: [
        tooltipTrigger(doc, el(doc, 'button', { className: 'date-range-nav', data: { daterangePrev: '' } }), { placement: 'bottom', title: 'Previous month' }),
        el(doc, 'span', { className: 'date-range-month', data: { daterangeMonth: '' }, text: '' }),
        tooltipTrigger(doc, el(doc, 'button', { className: 'date-range-nav', data: { daterangeNext: '' } }), { placement: 'bottom', title: 'Next month' }),
      ] }),
      el(doc, 'div', { className: 'date-range-weekdays', data: { daterangeWeekdays: '' } }),
      page.drDays,
      el(doc, 'div', { className: 'date-range-foot', children: [
        el(doc, 'span', { className: 'date-range-summary', data: { daterangeSummary: '' } }),
        el(doc, 'button', { className: 'btn', data: { daterangeReset: '' }, text: 'Reset' }),
        el(doc, 'button', { className: 'btn', data: { daterangeApply: '' }, text: 'Apply' }),
      ] }),
    ],
  });
  page.drPanel.hidden = true;
  page.daterangeControl = el(doc, 'div', {
    id: 'dateRangeControl',
    className: 'date-range',
    children: [page.drTrigger, page.drPanel],
  });
  doc.body.appendChild(page.daterangeControl);

  // Sessions Explorer: search field, switch, one panel with a session table.
  page.searchInput = el(doc, 'input', {
    id: 'sessionSearchInput',
    className: 'search-field-input',
    attrs: { type: 'search', placeholder: 'Search sessions/projects...' },
  });
  page.searchClear = tooltipTrigger(doc, el(doc, 'button', {
    id: 'sessionSearchClear',
    className: 'search-field-clear',
    data: { searchFieldClear: '' },
    attrs: { type: 'button', 'aria-label': 'Clear search', tabindex: '-1', 'aria-hidden': 'true', title: 'Clear search' },
  }), { placement: 'bottom' });
  page.searchField = el(doc, 'div', {
    id: 'sessionSearchField',
    className: 'search-field',
    data: { searchField: '' },
    children: [page.searchInput, page.searchClear],
  });
  page.switchTrack = el(doc, 'span', { className: 'switch-track', attrs: { 'aria-hidden': 'true' } });
  page.switchTrack.rect = { x: 0, y: 0, width: 40, height: 20, top: 0, left: 0, right: 40, bottom: 20 };
  page.switchTrack.computed.set('--switch-inset', '2px');
  page.switchTrack.computed.set('--switch-thumb-size', '18px');
  page.readableSwitch = el(doc, 'button', {
    id: 'readableTokensToggle',
    className: 'overview-readable-tokens-toggle',
    attrs: { type: 'button', role: 'switch', 'aria-checked': 'true' },
    children: [page.switchTrack],
  });
  page.searchWrap = el(doc, 'div', { className: 'sessions-controls', children: [page.searchField, page.readableSwitch] });
  doc.body.appendChild(page.searchWrap);

  page.sessionColgroup = el(doc, 'colgroup', { children: [
    el(doc, 'col', { attrs: { width: '40%' } }),
    el(doc, 'col', { attrs: { width: '30%' } }),
    el(doc, 'col', { attrs: { width: '30%' } }),
  ] });
  [0, 1, 2].forEach((index, i) => {
    page.sessionColgroup.children[i].style.width = ['40%', '30%', '30%'][index];
  });
  page.sessionHead = el(doc, 'thead', { children: [
    el(doc, 'tr', { children: [
      el(doc, 'th', { text: 'Session' }),
      el(doc, 'th', { text: 'Tokens' }),
      el(doc, 'th', { text: 'Cost' }),
    ] }),
  ] });
  page.sessionBody = el(doc, 'tbody', { children: [
    el(doc, 'tr', { children: [el(doc, 'td', { text: 'a session' }), el(doc, 'td', { text: '12.4M' }), el(doc, 'td', { text: '$12.40' })] }),
  ] });
  page.sessionTable = el(doc, 'table', {
    className: 'session-table',
    data: { panel: 'codex' },
    children: [page.sessionColgroup, page.sessionHead, page.sessionBody],
  });
  page.sessionTable.rect = { x: 0, y: 0, width: 1000, height: 200, top: 0, left: 0, right: 1000, bottom: 200 };
  page.sessionScroller = el(doc, 'div', { className: 'overflow-x-auto', children: [page.sessionTable] });
  page.sessionDetails = el(doc, 'details', {
    className: 'session-panel',
    data: { panelDetails: 'codex' },
    children: [el(doc, 'summary', { text: 'Codex Sessions' }), page.sessionScroller],
  });
  page.sessionDetails.open = true;
  doc.body.appendChild(page.sessionDetails);

  // Settings: the sidebar trigger, the dialog, the theme grid and its select.
  page.settingsBtn = el(doc, 'button', {
    id: 'sidebarSettingsBtn',
    attrs: { type: 'button', 'aria-controls': 'settingsPanel', 'aria-expanded': 'false', onclick: 'openSettingsModal()' },
    text: 'Settings',
  });
  page.styleSelect = el(doc, 'select', { id: 'styleThemeSelect', className: 'settings-select' });
  THEMES.forEach((theme) => {
    const option = el(doc, 'option', { text: theme });
    option.value = theme;
    page.styleSelect.appendChild(option);
  });
  page.styleSelect.value = 'elevated';
  page.themeGrid = el(doc, 'div', {
    id: 'styleThemeSwitcher',
    className: 'theme-switcher',
    attrs: { role: 'radiogroup' },
    data: { ready: 'false' },
  });
  page.updateBadge = el(doc, 'button', { id: 'updateBadge', className: 'update-badge' });
  page.updateBadge.hidden = true;
  page.settingsPanel = el(doc, 'section', {
    id: 'settingsPanel',
    className: 'settings-panel',
    attrs: { tabindex: '-1' },
    children: [
      el(doc, 'h2', { text: 'Settings' }),
      page.styleSelect,
      page.themeGrid,
      page.updateBadge,
    ],
  });
  page.settingsBackdrop = el(doc, 'dialog', {
    id: 'settingsBackdrop',
    className: 'app-modal-backdrop',
    attrs: { 'aria-modal': 'true', 'aria-labelledby': 'settingsPanelTitle' },
    children: [page.settingsPanel],
  });
  page.settingsBackdrop.hidden = true;
  page.settingsBackdrop.open = false;
  page.settingsBackdrop.showModal = function showModal() { this.open = true; this.showCount = (this.showCount || 0) + 1; };
  page.settingsBackdrop.close = function close() {
    if (!this.open) return;
    this.open = false;
    this.closeCount = (this.closeCount || 0) + 1;
    (this.listeners.get('close') || []).forEach((entry) => entry.fn.call(this, new DomEvent('close')));
  };
  page.settingsBtn.addEventListener('click', () => {
    if (typeof window.openSettingsModal === 'function') window.openSettingsModal();
  });
  doc.body.append(page.settingsBtn, page.settingsBackdrop);

  page.doc = doc;
  page.win = win;
  page.storage = storage;

  // The app's own dialog path, written the way index.html writes it: once the
  // panel is marked as the bundle's, the bundle drives the element, and all
  // three platform-level ways out -- the scrim, a click outside the panel, and
  // Escape -- funnel through this one function.
  window.openSettingsModal = () => page.setSettingsPanelOpen(true, true);
  page.setSettingsPanelOpen = (open, returnFocus = false) => {
    const animations = window.TokDashAnimations;
    if (page.settingsPanel.dataset.dialogMode === 'module'
      && animations && typeof animations.settingsDialogState === 'function') {
      if (open) animations.openSettingsDialog({ opener: page.settingsBtn });
      else animations.closeSettingsDialog({ restoreFocus: returnFocus });
      return;
    }
    if (open) {
      page.settingsBackdrop.removeAttribute('hidden');
      if (typeof page.settingsBackdrop.showModal === 'function' && !page.settingsBackdrop.open) page.settingsBackdrop.showModal();
    } else {
      if (typeof page.settingsBackdrop.close === 'function' && page.settingsBackdrop.open) page.settingsBackdrop.close();
      page.settingsBackdrop.setAttribute('hidden', '');
    }
    page.settingsPanel.hidden = !open;
    page.settingsBtn.setAttribute('aria-expanded', String(Boolean(open)));
  };

  // A click that landed on the scrim itself is a click outside the panel.
  page.settingsBackdrop.addEventListener('click', (event) => {
    if (event.target === page.settingsBackdrop) page.setSettingsPanelOpen(false, true);
  });
  doc.addEventListener('click', (event) => {
    // A control that re-renders its own list is detached by the time the event
    // bubbles here, and `contains()` reads that as a click outside; only a target
    // still in the document can prove an outside click. The trigger that opens
    // the panel is not an outside click either, however far it sits from it.
    if (!page.settingsPanel.hidden && event.target?.isConnected
      && !page.settingsPanel.contains(event.target)
      && !event.target.closest('button[onclick*="openSettingsModal"]')) {
      page.setSettingsPanelOpen(false);
    }
  });
  doc.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !page.settingsBackdrop.hidden) page.setSettingsPanelOpen(false, true);
  });
  return page;
}

// ---------------------------------------------------------------------------
// The app's own half: the single theme key, the heat palette the theme drives,
// the two status writers the reveal wraps, and the update signal the bar wraps.
// Written here the way index.html writes it, because that is what the surfaces
// share — the point of this file is the seams, not the modules alone.
// ---------------------------------------------------------------------------

function makeApp(doc, page) {
  const app = {
    theme: 'elevated',
    mode: 'dark',
    filters: 0,
    reveals: [],
  };
  app.storage = page.storage;
  page.win.t = (key, fallback) => fallback || key;

  app.heatColors = () => {
    const map = page.win.TOKDASH_THEME_CONFIG.heatColorsMap || {};
    const entry = map[app.theme] || map.elevated;
    return [...(app.mode === 'dark' ? entry.dark : entry.light)];
  };

  app.paintHeat = () => {
    const ramp = app.heatColors();
    page.heatCells.forEach((cell) => {
      const level = Math.max(0, Math.min(4, Number(cell.dataset.level) || 0));
      const index = Math.round((level / 4) * Math.max(0, ramp.length - 1));
      cell.style.background = ramp[index] || 'var(--color-border)';
    });
  };

  app.writeTheme = (patch = {}) => {
    if (patch.style) app.theme = patch.style;
    if (patch.mode) app.mode = patch.mode;
    page.storage.setItem(APP_KEYS.theme, JSON.stringify({ style: app.theme, mode: app.mode }));
    page.storage.removeItem(APP_KEYS.legacy);
  };

  app.applyTheme = (style, mode) => {
    app.theme = style;
    app.mode = mode;
    doc.documentElement.dataset.uiTheme = style;
    doc.documentElement.classList.toggle('dark', mode === 'dark');
    page.styleSelect.value = style;
    app.paintHeat();
    syncThemeSwitcher(style);
  };

  app.boot = () => {
    const raw = page.storage.getItem(APP_KEYS.theme) || page.storage.getItem(APP_KEYS.legacy);
    let preference = null;
    try { preference = raw ? JSON.parse(raw) : null; } catch (_) { preference = null; }
    if (preference && typeof preference === 'object') {
      app.applyTheme(preference.style || 'elevated', preference.mode || 'dark');
    } else {
      // The legacy key held the style; the mode fell to the system.
      app.applyTheme(page.storage.getItem(APP_KEYS.legacy) || 'elevated', 'dark');
      if (raw) app.writeTheme({});
    }
  };

  // The style select stays the value carrier: whoever commits a theme hands it
  // to this control, and this listener is the only writer of the key.
  page.styleSelect.addEventListener('change', () => {
    app.writeTheme({ style: page.styleSelect.value });
    app.applyTheme(page.styleSelect.value, app.mode);
  });

  // The two writers #lastUpdate has, and the signal the announcement bar wraps.
  let minutes = 22;
  page.win.updateTimestamp = () => {
    page.lastUpdate.textContent = `Last updated: 09:${String(minutes).padStart(2, '0')}`;
    minutes += 1;
  };
  page.win.setDashboardFetchStatus = (detail) => {
    page.lastUpdate.textContent = String(detail || 'Load failed');
  };
  page.win.renderUpdateBadge = (info) => {
    const available = Boolean(info && info.update_available);
    page.updateBadge.hidden = !available;
    page.updateBadge.textContent = available ? `New version v${info.latest}` : '';
  };

  page.win.filterSessionsBySearch = () => { app.filters += 1; };
  page.searchInput.addEventListener('input', () => { app.filters += 1; });

  // The app's own switch handler: the module never writes this state.
  page.readableSwitch.addEventListener('click', () => {
    const next = page.readableSwitch.getAttribute('aria-checked') !== 'true';
    page.readableSwitch.setAttribute('aria-checked', String(next));
  });

  page.win.TokDashAnimations = {
    syncThemeSwitcher,
    setActionButtonLabel,
    setActionButtonBusy,
    setActionButtonDisabled,
    syncRangeSwitcher,
    openSettingsDialog,
    closeSettingsDialog,
    settingsDialogState,
  };
  return app;
}

// ---------------------------------------------------------------------------
// Session helpers: real event paths, never a direct state poke.
// ---------------------------------------------------------------------------

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Wait for a module's own state to say it is done, rather than for a guessed
 * number of milliseconds: every settle below is delivered by a timer the module
 * owns, and the oracle here is the end state that timer produces -- not the
 * smoothing on the way to it.
 */
async function until(predicate, timeoutMs = 4000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (predicate()) return true;
    await sleep(20);
  }
  return Boolean(predicate());
}

function pressOn(target, init = {}) {
  target.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 1, button: 0, pointerType: 'mouse', ...init }));
  target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, pointerId: 1, button: 0, ...init }));
}

function releaseOn(target, init = {}) {
  target.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1, button: 0, pointerType: 'mouse', ...init }));
  target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, pointerId: 1, button: 0, ...init }));
}

/**
 * The click a browser dispatches at the nearest common ancestor of a press and
 * a release. `target` is that ancestor, which is what the dispatch loop needs --
 * the browser computes the target; the harness names it.
 */
function clickDispatchedOn(target) {
  const event = new MouseEvent('click', { bubbles: true, cancelable: true, composed: true });
  target.dispatchEvent(event);
  return { stopped: event.__stopped, defaultPrevented: event.defaultPrevented };
}

function hintState() { return tooltipState(); }

function tooltipLayerCount(doc) { return doc.querySelectorAll('.tooltip').length; }
function popoverLayerCount(doc) { return doc.querySelectorAll('.popover-layer').length; }

function keySpace(storage) { return [...storage.map.keys()].sort(); }

// ---------------------------------------------------------------------------
// The session.
// ---------------------------------------------------------------------------

const MODULE_URI = process.argv[2];
const barrel = await import(MODULE_URI);

const {
  mountTooltips, attachTooltip, detachTooltip, tooltipState, dismissTooltip,
  attachPopover, openPopover, closePopover, popoverState,
  showToast, dismissToast, clearToasts,
  mountActionButton, setActionButtonLabel, setActionButtonBusy, setActionButtonDisabled, actionButtonIsBlocked,
  showLoader, hideLoader, setLoaderRate,
  mountAnnouncementBar, announceUpdate, hideAnnouncement, announcementState,
  mountMetricCards, metricCardsState, metricValueState, animateMetricValues,
  renderSlotText, slotTextState,
  renderCountedValue, counterState,
  observeCharts, animateChartEntry,
  mountTextReveal, morphText, revealText, textRevealState,
  mountThemeSwitcher, syncThemeSwitcher, placeThemeSwitcher, themeSwitcherTiles,
  mountSearchFields, searchFieldState,
  mountSwitches, switchState,
  mountRangeSwitcher, syncRangeSwitcher, rangeSwitcherState,
  mountDateRangeControl, dateRangePickerState, dismissDateRangePicker,
  mountResizablePanels,
  mountSettingsDialog, openSettingsDialog, closeSettingsDialog, settingsDialogState,
} = barrel;

const report = {};
const page = buildPage();
const doc = page.doc;
const app = makeApp(doc, page);

// --- 1. Boot: the preference is on disk, the skeleton is up -----------------
page.storage.setItem(APP_KEYS.theme, JSON.stringify({ style: 'elevated', mode: 'dark' }));
app.boot();
report.boot = {
  theme: doc.documentElement.dataset.uiTheme,
  dark: doc.documentElement.classList.contains('dark'),
  keys: keySpace(page.storage),
};

// The status line is a loading placeholder; the reveal wraps its writers.
mountTextReveal();
showLoader({ initialRate: 0.8 });
report.loaderVisible = { hidden: page.loader.hidden, display: page.loader.style.display };
page.win.updateTimestamp();
report.statusReveal = textRevealState(page.lastUpdate);
await until(() => !textRevealState(page.lastUpdate).revealing);
report.statusSettled = { text: page.lastUpdate.textContent, revealing: textRevealState(page.lastUpdate).revealing };

// A later resolve is a change, not a first read: it morphs.
page.win.updateTimestamp();
report.statusMorph = textRevealState(page.lastUpdate);
await until(() => !textRevealState(page.lastUpdate).hasOutgoing);
report.statusMorphSettled = { text: page.lastUpdate.textContent, hasOutgoing: textRevealState(page.lastUpdate).hasOutgoing };

// The skeleton finishes: the loader's own completion contract.
hideLoader();
await until(() => page.loader.hidden);
report.loaderHidden = { hidden: page.loader.hidden, display: page.loader.style.display };

// --- 2. Cards, hints and the shared tooltip layer --------------------------
// The page-wide pass runs first, then the cards mount: the order that used to
// let a card's hint get a second attachment.
report.tooltipsFirstPass = mountTooltips(doc);
report.cardsMounted = mountMetricCards(doc);
report.tooltipsSecondPass = mountTooltips(doc);
report.cardsRemounted = mountMetricCards(doc);
report.cardStates = metricCardsState(doc);

// A hover opens the card's own hint text, from the adopted title.
page.tokenHint.dispatchEvent(new PointerEvent('pointerenter'));
await until(() => Boolean(hintState() && hintState().open));
report.hintOpen = hintState();
doc.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
report.hintAfterEscape = hintState();

// A trigger registered after the page-wide pass -- how a donut wedge or a
// freshly rendered cell declares itself -- opens the same one bubble.
const dynamicTrigger = doc.createElement('button');
dynamicTrigger.className = 'profile-activity-cell';
doc.body.appendChild(dynamicTrigger);
report.dynamicAttach = Boolean(attachTooltip(dynamicTrigger, { content: 'Oct 20, 2025: 390.2M tokens', placement: 'bottom' }));
dynamicTrigger.dispatchEvent(new PointerEvent('pointerenter'));
await until(() => Boolean(hintState() && hintState().open));
report.dynamicHintOpen = hintState();
report.tooltipLayers = tooltipLayerCount(doc);
dismissTooltip();

// The resizable handles declare their hint the same way, so by the end of the
// session three surfaces are sharing this one layer.
report.handlesBuilt = mountResizablePanels(doc);
const divider = doc.querySelector('.tokdash-col-divider');
divider.dispatchEvent(new PointerEvent('pointerenter'));
await until(() => Boolean(hintState() && hintState().open));
report.handleHint = hintState();
dismissTooltip();
report.tooltipLayersAfterHandles = tooltipLayerCount(doc);

// --- 3. Figures: a first sight is adopted, a change is animated -------------
// The app's own formatter (index.html's `formatNumber`), which is also what tells
// the counter how these figures separate thousands from decimals.
const format = (value) => Number(value ?? 0).toLocaleString('en-US');
report.metricAdopt = animateMetricValues(doc, { format });
page.tokenValue.textContent = '2.4B';
report.metricChange = animateMetricValues(doc, { format });
report.counterStart = counterState(page.tokenValue);
await until(() => !counterState(page.tokenValue).counting);
report.counterSettled = counterState(page.tokenValue);
page.costValue.textContent = '$2,408.00';
report.metricCountAfter = animateMetricValues(doc, { format });
await until(() => !counterState(page.costValue).counting);
report.costSettled = counterState(page.costValue);

// A figure that changed kind morphs instead of counting.
page.modelValue.textContent = 'claude-sonnet-5';
report.metricMorph = animateMetricValues(doc, { format });
report.modelMorphState = metricValueState(page.modelValue);
await until(() => !metricValueState(page.modelValue).morphing);
report.modelMorphSettled = metricValueState(page.modelValue);

// --- 4. Charts and the heatmap --------------------------------------------
observeCharts(doc);
report.chartEntryPrep = {
  opacity: page.donutWrap.style.opacity,
  transform: page.donutWrap.style.transform,
  observed: intersectionObservers.some((observer) => observer.targets.includes(page.donutCanvas)),
};
intersectionObservers.forEach((observer) => {
  if (observer.targets.includes(page.donutCanvas)) {
    observer.callback([{ target: page.donutCanvas, isIntersecting: true }], observer);
  }
});
report.chartEntryStarted = { animated: page.donutWrap.dataset.chartAnimated || null };
await until(() => page.donutWrap.style.transform === '' && page.donutWrap.style.opacity === '');
report.chartEntrySettled = { transform: page.donutWrap.style.transform, opacity: page.donutWrap.style.opacity };

// The heatmap and the theme switcher previews read the same ramp, so a theme
// change has to move both.
report.heatBefore = { cell: page.heatCells[4].style.background, ramp: app.heatColors()[7] };

// --- 5. Refresh: the action button and the toast stack ---------------------
mountActionButton(page.refreshBtn, 'Refresh');
setActionButtonBusy(page.refreshBtn, true);
setActionButtonDisabled(page.refreshBtn, true);
setActionButtonLabel(page.refreshBtn, 'Refreshing…', { tone: 'muted' });
report.refreshPending = {
  busy: page.refreshBtn.getAttribute('aria-busy'),
  blocked: actionButtonIsBlocked(page.refreshBtn),
  layers: page.refreshBtn.querySelectorAll('.action-btn-label-layer').length,
};
setActionButtonBusy(page.refreshBtn, false);
setActionButtonDisabled(page.refreshBtn, false);
// One region, one stack, capped at three: the fourth toast retires the oldest
// through the same exit animation a dismissal uses, so eviction reads as a
// departure rather than as a flag left on a node that is still on screen.
showToast({ title: 'Dashboard refreshed', duration: 0 });
showToast({ title: 'Second', duration: 0 });
showToast({ title: 'Third', duration: 0 });
const actionToast = showToast({
  title: 'Fourth',
  meta: '12 tools · 1,204 sessions',
  duration: 0,
  actions: [{ label: 'Details', onClick: () => { report.toastAction = true; } }],
});
const region = doc.getElementById('tokdashToastRegion');
const titleOf = (toast) => toast.querySelector('.toast-title').textContent;
const liveToasts = () => region.children.filter((toast) => toast.dataset.leaving !== 'true');
report.toastStack = {
  region: Boolean(region),
  live: region.getAttribute('aria-live'),
  count: liveToasts().length,
  titles: liveToasts().map(titleOf),
  leaving: region.children.length - liveToasts().length,
};
await until(() => region.children.length === 3);
report.toastCapSettled = { count: region.children.length, titles: [...region.children].map(titleOf) };
report.toastActionButton = Boolean(actionToast.querySelector('.toast-action'));
actionToast.querySelector('.toast-action').click();
await until(() => !actionToast.parentNode);
report.toastAfterAction = { actionRan: Boolean(report.toastAction), dismissed: !actionToast.parentNode };
clearToasts();
report.toastCleared = region.children.length;

// --- 6. Announcement, on its own key ---------------------------------------
mountAnnouncementBar(doc);
page.win.renderUpdateBadge({ update_available: true, latest: '9.9.9' });
report.announcementShown = announcementState();
page.announcementClose.click();
report.announcementDismissed = { state: announcementState(), key: page.storage.getItem(APP_KEYS.announcement) };
page.win.renderUpdateBadge({ update_available: true, latest: '9.9.9' });
report.announcementStaysHidden = announcementState();

// --- 7. Search, switch, range ---------------------------------------------
report.searchMounted = mountSearchFields(doc);
page.searchInput.value = 'codex';
page.searchInput.dispatchEvent(new DomEvent('input', { bubbles: true }));
report.searchTyped = searchFieldState(page.searchField);
page.searchClear.click();
report.searchCleared = { state: searchFieldState(page.searchField), filters: app.filters };

report.switchesMounted = mountSwitches(doc);
pressOn(page.switchTrack, { clientX: 0 });
page.readableSwitch.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 1, clientX: 14 }));
releaseOn(page.readableSwitch, { clientX: 14 });
const committedClick = clickDispatchedOn(page.readableSwitch);
report.switchDragCommit = { state: switchState(page.readableSwitch), clickPassed: !committedClick.stopped, checked: page.readableSwitch.getAttribute('aria-checked') };

// A drag that retreats must veto the trailing click: the finger took it back.
// The commit above left the switch off, so a short forward drag ends short of
// halfway and the app must never hear the toggle.
pressOn(page.switchTrack, { clientX: 0 });
page.readableSwitch.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 1, clientX: 5 }));
releaseOn(page.readableSwitch, { clientX: 5 });
const vetoedClick = clickDispatchedOn(page.readableSwitch);
report.switchDragRetreat = { stopped: vetoedClick.stopped, checked: page.readableSwitch.getAttribute('aria-checked') };
// The veto lives only as long as the click it was waiting for: once the grace
// timer has run out the preview is gone and the next tap lands.
await until(() => switchState(page.readableSwitch).preview === null);

report.rangeMounted = mountRangeSwitcher(page.rangeRoot);
report.rangeInitial = rangeSwitcherState(page.rangeRoot);
page.segments[2].click();
report.rangeAfterClick = rangeSwitcherState(page.rangeRoot);
page.rangeRoot.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
report.rangeAfterArrow = rangeSwitcherState(page.rangeRoot);

// --- 8. The calendar, on the shared popover layer --------------------------
mountDateRangeControl(page.daterangeControl, { onApply: () => { report.applied = true; } });
page.drTrigger.click();
report.calendarOpen = dateRangePickerState(page.daterangeControl);
report.popoverShared = popoverState();
page.drDays.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
report.calendarClosed = { state: dateRangePickerState(page.daterangeControl), popover: popoverState() };

// The refresh report is the second consumer of that layer, and only one panel
// may be open at a time.
const reportHandle = attachPopover(page.refreshBtn, page.refreshReport, { align: 'end' });
openPopover(reportHandle);
report.reportOpen = popoverState();
page.drTrigger.click();
report.reportSuperseded = { report: page.refreshReport.dataset.popover, picker: dateRangePickerState(page.daterangeControl).open, popover: popoverState() };
doc.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
report.afterEscapeBoth = { picker: dateRangePickerState(page.daterangeControl).open, popover: popoverState(), report: page.refreshReport.dataset.popover };
report.popoverLayers = popoverLayerCount(doc);

// --- 9. Settings, the theme grid, and the two keys they share --------------
mountSettingsDialog(page.settingsBackdrop, page.settingsPanel);
page.settingsPanel.dataset.dialogMode = 'module';
mountThemeSwitcher(page.themeGrid, { select: page.styleSelect });
report.switcherTiles = themeSwitcherTiles().length;

page.settingsBtn.click();
const checkedTile = doc.querySelector('.theme-swatch[aria-checked="true"]');
const ring = page.themeGrid.querySelector('.theme-switcher-indicator');
report.dialogOpen = settingsDialogState();
report.ringOnOpen = {
  checked: checkedTile ? checkedTile.dataset.theme : null,
  aligned: ring ? Math.abs(ring.rect.left - checkedTile.rect.left) < 1 && Math.abs(ring.rect.top - checkedTile.rect.top) < 1 : false,
  ready: page.themeGrid.dataset.ready,
};

// A quiet click on a tile: the press and the release land together.
const tileFor = (theme) => doc.querySelector(`.theme-swatch[data-theme="${theme}"]`);
tileFor('terminal').click();
report.tileClick = { theme: doc.documentElement.dataset.uiTheme, stored: JSON.parse(page.storage.getItem(APP_KEYS.theme)), open: page.settingsBackdrop.open };

// A press that drifts off the tile: the click is dispatched on the grid.
pressOn(tileFor('paper').querySelector('.theme-swatch-preview'));
clickDispatchedOn(page.themeGrid);
report.tileDriftOnGrid = { theme: doc.documentElement.dataset.uiTheme, checked: doc.querySelector('.theme-swatch[aria-checked="true"]').dataset.theme, open: page.settingsBackdrop.open };

// A press whose release lands on the scrim: the dialog must stay up, and the
// choice must still be the user's.
pressOn(tileFor('nordic').querySelector('.theme-swatch-preview'));
clickDispatchedOn(page.settingsBackdrop);
report.tileDriftOnScrim = { theme: doc.documentElement.dataset.uiTheme, checked: doc.querySelector('.theme-swatch[aria-checked="true"]').dataset.theme, open: page.settingsBackdrop.open };

// And a click that really began on the scrim still closes it.
pressOn(page.settingsBackdrop);
releaseOn(page.settingsBackdrop);
clickDispatchedOn(page.settingsBackdrop);
report.scrimClickCloses = { open: page.settingsBackdrop.open };

// The theme the heatmap is showing moved with the choice above.
report.heatAfter = { cell: page.heatCells[4].style.background, ramp: app.heatColors()[7] };

// Back to elevated through the grid, so the reload has one clear expectation.
page.settingsBtn.click();
tileFor('elevated').click();
report.finalTheme = { theme: doc.documentElement.dataset.uiTheme, stored: JSON.parse(page.storage.getItem(APP_KEYS.theme)), open: page.settingsBackdrop.open };

// --- 10. The column divider, and the session's own key space ---------------
const dividerAfterMount = doc.querySelector('.tokdash-col-divider');
dividerAfterMount.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 1, button: 0, clientX: 400 }));
dividerAfterMount.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 1, clientX: 470 }));
dividerAfterMount.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1, clientX: 470 }));
const storedSplit = page.storage.getItem(APP_KEYS.split);
const colsAfterDrag = page.sessionColgroup.children.map((col) => col.style.width);
report.dividerDrag = {
  dragging: dividerAfterMount.dataset.dragging,
  stored: storedSplit ? JSON.parse(storedSplit) : null,
  cols: colsAfterDrag,
  pairTotal: Number.parseFloat(colsAfterDrag[0]) + Number.parseFloat(colsAfterDrag[1]),
  dividers: doc.querySelectorAll('.tokdash-col-divider').length,
};
dividerAfterMount.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
report.dividerReset = {
  stored: page.storage.getItem(APP_KEYS.split),
  cols: page.sessionColgroup.children.map((col) => col.style.width),
};

// --- 11. Idempotence: every mount again, on the same page ------------------
report.remount = {
  tooltips: mountTooltips(doc),
  cards: mountMetricCards(doc),
  panels: mountResizablePanels(doc),
  switches: mountSwitches(doc),
  search: mountSearchFields(doc),
  range: mountRangeSwitcher(page.rangeRoot),
  announcement: announcementState().mounted,
  dialog: mountSettingsDialog(page.settingsBackdrop, page.settingsPanel),
};
report.layersAtEnd = {
  tooltips: tooltipLayerCount(doc),
  popovers: popoverLayerCount(doc),
  toasts: doc.querySelectorAll('#tokdashToastRegion').length,
  indicators: doc.querySelectorAll('.theme-switcher-indicator').length,
  dividers: doc.querySelectorAll('.tokdash-col-divider').length,
};
report.keysAtEnd = keySpace(page.storage);

// --- 12. Reload: a fresh document, the same storage ------------------------
const reloaded = buildPage();
installGlobals(reloaded.doc, reloaded.win, page.storage);
const reloadApp = makeApp(reloaded.doc, reloaded);
reloaded.win.TOKDASH_THEME_CONFIG = themeConfig();
mountTooltips(reloaded.doc);
reloadApp.boot();
mountSettingsDialog(reloaded.settingsBackdrop, reloaded.settingsPanel);
reloaded.settingsPanel.dataset.dialogMode = 'module';
mountThemeSwitcher(reloaded.themeGrid, { select: reloaded.styleSelect });
mountAnnouncementBar(reloaded.doc);
mountResizablePanels(reloaded.doc);
reloaded.settingsBtn.click();
const reloadRing = reloaded.themeGrid.querySelector('.theme-switcher-indicator');
const reloadChecked = reloaded.doc.querySelector('.theme-swatch[aria-checked="true"]');
report.reload = {
  theme: reloaded.doc.documentElement.dataset.uiTheme,
  dark: reloaded.doc.documentElement.classList.contains('dark'),
  checked: reloadChecked ? reloadChecked.dataset.theme : null,
  ringAligned: reloadRing && reloadChecked
    ? Math.abs(reloadRing.rect.left - reloadChecked.rect.left) < 1 && Math.abs(reloadRing.rect.top - reloadChecked.rect.top) < 1
    : false,
  dialogOpen: reloaded.settingsBackdrop.open,
  announcement: announcementState(),
  cols: reloaded.sessionColgroup.children.map((col) => col.style.width),
  dividers: reloaded.doc.querySelectorAll('.tokdash-col-divider').length,
  toastRegion: reloaded.doc.querySelectorAll('#tokdashToastRegion').length,
  keys: keySpace(page.storage),
};

process.stdout.write(JSON.stringify(report));
"""


def _run(tmp_path: Path) -> dict:
    harness = tmp_path / "session.mjs"
    harness.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), BARREL.as_uri()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def session_report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    return _run(tmp_path_factory.mktemp("ui-session"))


@needs_node
def test_boot_and_the_loading_surfaces_share_one_page_state(session_report: dict) -> None:
    report = session_report

    # The stored preference is the only theme input, and boot applies it.
    assert report["boot"] == {"theme": "elevated", "dark": True, "keys": ["tokdash-theme"]}, report["boot"]

    # Skeleton up while the dashboard resolves, down when it lands.
    assert report["loaderVisible"] == {"hidden": False, "display": "flex"}, report["loaderVisible"]
    assert report["loaderHidden"] == {"hidden": True, "display": "none"}, report["loaderHidden"]

    # The status line: a reveal on the first resolve, a morph on every later one,
    # and the plain text left behind in both cases.
    assert report["statusReveal"]["revealing"] is True, report["statusReveal"]
    assert _plain(report["statusReveal"]["text"]) == "Last updated: 09:22", report["statusReveal"]
    assert report["statusSettled"]["revealing"] is False, report["statusSettled"]
    assert _plain(report["statusSettled"]["text"]) == "Last updated: 09:22", report["statusSettled"]
    assert report["statusMorph"]["morphing"] is True, report["statusMorph"]
    assert report["statusMorph"]["hasOutgoing"] is True, report["statusMorph"]
    assert report["statusMorphSettled"]["hasOutgoing"] is False, report["statusMorphSettled"]
    assert _plain(report["statusMorphSettled"]["text"]) == "Last updated: 09:23", report["statusMorphSettled"]


@needs_node
def test_one_tooltip_layer_serves_every_surface(session_report: dict) -> None:
    report = session_report

    # The page-wide pass attaches; the cards mounting afterwards attach nothing
    # new, and a third pass still finds nothing new. A trigger owns one hint.
    assert report["tooltipsFirstPass"] >= 4, report["tooltipsFirstPass"]
    assert report["cardsMounted"] == 3, report["cardsMounted"]
    assert report["tooltipsSecondPass"] == 0, report["tooltipsSecondPass"]
    assert report["cardsRemounted"] == 0, report["cardsRemounted"]
    assert [card["label"] for card in report["cardStates"]] == ["Total Tokens", "Top Model", "Cost"], report["cardStates"]

    # A hover shows the card's adopted title in the shared bubble, and Escape
    # withdraws it without moving focus.
    assert report["hintOpen"]["open"] is True, report["hintOpen"]
    assert report["hintOpen"]["text"] == "Tokens counted across every tool", report["hintOpen"]
    assert report["hintOpen"]["describedBy"] == "tokdashTooltip", report["hintOpen"]
    assert report["hintAfterEscape"] is None, report["hintAfterEscape"]

    # A trigger registered later opens the same one bubble, and by the end of the
    # session the metric hint, the dynamic trigger and the column handle have all
    # used it — one layer, not three.
    assert report["dynamicAttach"] is True, report
    assert report["dynamicHintOpen"]["text"] == "Oct 20, 2025: 390.2M tokens", report["dynamicHintOpen"]
    assert report["tooltipLayers"] == 1, report["tooltipLayers"]
    assert report["handleHint"]["text"] == "Drag to resize columns", report["handleHint"]
    assert report["tooltipLayersAfterHandles"] == 1, report["tooltipLayersAfterHandles"]


@needs_node
def test_the_press_decides_a_theme_and_only_a_scrim_click_closes(session_report: dict) -> None:
    report = session_report

    # The dialog opens from the app's own trigger with the ring already on the
    # chosen tile, and the single key carries both halves.
    assert report["switcherTiles"] == 17, report["switcherTiles"]
    assert report["dialogOpen"]["open"] is True, report["dialogOpen"]
    assert report["ringOnOpen"]["checked"] == "elevated", report["ringOnOpen"]
    assert report["ringOnOpen"]["aligned"] is True, report["ringOnOpen"]
    assert report["ringOnOpen"]["ready"] == "true", report["ringOnOpen"]

    # An unbroken click commits through the select, which writes the one key.
    assert report["tileClick"]["theme"] == "terminal", report["tileClick"]
    assert report["tileClick"]["stored"] == {"style": "terminal", "mode": "dark"}, report["tileClick"]
    assert report["tileClick"]["open"] is True, report["tileClick"]

    # A press that drifts off the tile is still a choice: the click lands on the
    # grid, the theme still applies, and the dialog stays up.
    assert report["tileDriftOnGrid"] == {"theme": "paper", "checked": "paper", "open": True}, report["tileDriftOnGrid"]

    # A release on the scrim is not a scrim click: the dialog survives and the
    # theme the finger asked for is the one that lands.
    assert report["tileDriftOnScrim"] == {"theme": "nordic", "checked": "nordic", "open": True}, report["tileDriftOnScrim"]

    # A click that began on the scrim still closes the dialog.
    assert report["scrimClickCloses"] == {"open": False}, report["scrimClickCloses"]

    # The heatmap is painted from the theme's ramp, and the theme change moved it
    # to the new theme's ramp -- the two surfaces read one source.
    assert report["heatBefore"]["cell"] == report["heatBefore"]["ramp"], report["heatBefore"]
    assert report["heatAfter"]["cell"] == report["heatAfter"]["ramp"], report["heatAfter"]
    assert report["heatAfter"]["cell"] != report["heatBefore"]["cell"], report

    assert report["finalTheme"] == {"theme": "elevated", "stored": {"style": "elevated", "mode": "dark"}, "open": True}, report["finalTheme"]


@needs_node
def test_figures_refresh_and_announcements_stay_in_their_own_keys(session_report: dict) -> None:
    report = session_report

    # A first sight of a figure is adopted silently; a change of the same kind
    # counts, settles on the writer's own string, and leaves no run behind.
    assert report["metricAdopt"] == {"values": 3, "morphed": 0, "counted": 0, "changed": 0}, report["metricAdopt"]
    assert report["metricChange"]["counted"] == 1, report["metricChange"]
    assert report["counterStart"]["counting"] is True, report["counterStart"]
    assert report["counterSettled"]["counting"] is False, report["counterSettled"]
    assert report["counterSettled"]["shown"] == "2.4B", report["counterSettled"]
    assert report["metricCountAfter"]["counted"] == 1, report["metricCountAfter"]
    assert report["costSettled"]["shown"] == "$2,408.00", report["costSettled"]

    # A figure that changed kind morphs, and settles back to plain text.
    assert report["metricMorph"]["morphed"] == 1, report["metricMorph"]
    assert report["modelMorphState"]["morphing"] is True, report["modelMorphState"]
    assert report["modelMorphSettled"]["morphing"] is False, report["modelMorphSettled"]
    assert report["modelMorphSettled"]["text"] == "claude-sonnet-5", report["modelMorphSettled"]

    # Charts: held until they are seen, animated once, then released -- the
    # residual transform is cleared, which is what keeps a fixed overlay from
    # being positioned against the wrapper afterwards.
    assert report["chartEntryPrep"]["opacity"] == "0", report["chartEntryPrep"]
    assert report["chartEntryPrep"]["transform"] == "scale(0.95)", report["chartEntryPrep"]
    assert report["chartEntryPrep"]["observed"] is True, report["chartEntryPrep"]
    assert report["chartEntryStarted"]["animated"] == "true", report["chartEntryStarted"]
    assert report["chartEntrySettled"] == {"transform": "", "opacity": ""}, report["chartEntrySettled"]

    # Refresh: the button's label stack, the toast stack's cap and its actions.
    assert report["refreshPending"]["busy"] == "true", report["refreshPending"]
    assert report["refreshPending"]["blocked"] is True, report["refreshPending"]
    assert report["refreshPending"]["layers"] >= 1, report["refreshPending"]
    assert report["toastStack"]["region"] is True, report["toastStack"]
    assert report["toastStack"]["live"] == "polite", report["toastStack"]
    assert report["toastStack"]["count"] == 3, report["toastStack"]
    assert report["toastStack"]["titles"] == ["Second", "Third", "Fourth"], report["toastStack"]
    assert report["toastStack"]["leaving"] == 1, report["toastStack"]
    # ... and it really goes away, through the exit animation a dismissal uses.
    assert report["toastCapSettled"] == {"count": 3, "titles": ["Second", "Third", "Fourth"]}, report["toastCapSettled"]
    assert report["toastActionButton"] is True, report
    assert report["toastAfterAction"] == {"actionRan": True, "dismissed": True}, report["toastAfterAction"]
    assert report["toastCleared"] == 0, report["toastCleared"]

    # The announcement reads its words off the settings badge, and its dismissal
    # is remembered on its own key -- not the theme's.
    assert report["announcementShown"]["shown"] is True, report["announcementShown"]
    assert report["announcementShown"]["message"] == "New version v9.9.9", report["announcementShown"]
    assert report["announcementDismissed"]["state"]["shown"] is False, report["announcementDismissed"]
    assert report["announcementDismissed"]["key"] == "9.9.9", report["announcementDismissed"]
    assert report["announcementStaysHidden"]["shown"] is False, report["announcementStaysHidden"]


@needs_node
def test_search_switch_range_and_the_calendar_on_one_page(session_report: dict) -> None:
    report = session_report

    # The clear control arrives with a query, leaves with the query, and the way
    # out runs the app's own filter path exactly once.
    assert report["searchTyped"]["hasQuery"] is True, report["searchTyped"]
    assert report["searchTyped"]["clearVisible"] is True, report["searchTyped"]
    assert report["searchTyped"]["clearTabIndex"] == 0, report["searchTyped"]
    assert report["searchCleared"]["state"]["hasQuery"] is False, report["searchCleared"]
    assert report["searchCleared"]["state"]["query"] == "", report["searchCleared"]
    assert report["searchCleared"]["filters"] == 2, report["searchCleared"]

    # A drag past halfway is the decision and the platform's click commits it; a
    # retreat is vetoed before the click can reach the app's handler.
    assert report["switchDragCommit"]["state"]["dragging"] is False, report["switchDragCommit"]
    assert report["switchDragCommit"]["clickPassed"] is True, report["switchDragCommit"]
    assert report["switchDragCommit"]["checked"] == "false", report["switchDragCommit"]
    assert report["switchDragRetreat"]["stopped"] is True, report["switchDragRetreat"]
    assert report["switchDragRetreat"]["checked"] == "false", report["switchDragRetreat"]

    # The range switcher: one pill, one value, moved by click and by arrow key.
    assert report["rangeMounted"] == 4, report["rangeMounted"]
    assert report["rangeInitial"]["value"] == "today", report["rangeInitial"]
    assert report["rangeAfterClick"]["value"] == "last7days", report["rangeAfterClick"]
    assert report["rangeAfterArrow"]["value"] == "lastWeek", report["rangeAfterArrow"]

    # The calendar opens through the shared popover layer with a real grid, and
    # Escape closes it without leaving the layer behind.
    assert report["calendarOpen"]["open"] is True, report["calendarOpen"]
    assert report["calendarOpen"]["days"] >= 28, report["calendarOpen"]
    assert report["calendarOpen"]["tabbable"] == 1, report["calendarOpen"]
    assert report["popoverShared"]["inLayer"] is True, report["popoverShared"]
    assert report["calendarClosed"]["state"]["open"] is False, report["calendarClosed"]
    assert report["calendarClosed"]["popover"] is None, report["calendarClosed"]

    # Two consumers, one layer, one open panel at a time.
    assert report["reportOpen"]["inLayer"] is True, report["reportOpen"]
    assert report["reportOpen"]["expanded"] == "true", report["reportOpen"]
    assert report["reportSuperseded"]["report"] == "closed", report["reportSuperseded"]
    assert report["reportSuperseded"]["picker"] is True, report["reportSuperseded"]
    assert report["afterEscapeBoth"]["picker"] is False, report["afterEscapeBoth"]
    assert report["afterEscapeBoth"]["popover"] is None, report["afterEscapeBoth"]
    assert report["popoverLayers"] == 1, report["popoverLayers"]


@needs_node
def test_column_dividers_and_the_invariants_between_surfaces(session_report: dict) -> None:
    report = session_report

    # The drag moves the pair and preserves its total, so nothing beside the
    # divider moved; the split is remembered under its own key, as the left
    # column's share of the 70% pair that was actually painted.
    drag = report["dividerDrag"]
    assert drag["dividers"] == 2, drag
    assert drag["dragging"] == "false", drag
    assert drag["cols"] == ["47%", "23%", "30%"], drag
    assert abs(drag["pairTotal"] - 70) < 0.05, drag
    stored = drag["stored"]["sessions-split:codex:col:0-1"]
    assert abs(stored - 47 / 70) < 0.001, drag
    # Escape resets the split: the pair's own entry goes back to absent, and the
    # columns are painted at the widths they declared.
    assert json.loads(report["dividerReset"]["stored"]) == {}, report["dividerReset"]
    assert report["dividerReset"]["cols"] == ["40%", "30%", "30%"], report["dividerReset"]

    # Idempotence: a second pass over every mount adds nothing to a page that is
    # already mounted -- no second hint, handle, switch binding or search binding.
    assert report["remount"] == {
        "tooltips": 0,
        "cards": 0,
        "panels": 0,
        "switches": 1,
        "search": 1,
        "range": 4,
        "announcement": True,
        "dialog": 1,
    }, report["remount"]
    assert report["layersAtEnd"] == {"tooltips": 1, "popovers": 1, "toasts": 1, "indicators": 1, "dividers": 2}, report["layersAtEnd"]

    # One key per concern, and the theme is still a single JSON value.
    assert report["keysAtEnd"] == ["tokdash-announcement-dismissed", "tokdash-sessions-split", "tokdash-theme"], report["keysAtEnd"]


@needs_node
def test_a_reload_restores_everything_the_session_chose(session_report: dict) -> None:
    report = session_report["reload"]

    # The single key puts the theme and the mode back, the grid's ring lands on
    # the restored tile, and the layers are rebuilt empty.
    assert report["theme"] == "elevated", report
    assert report["dark"] is True, report
    assert report["checked"] == "elevated", report
    assert report["ringAligned"] is True, report
    assert report["dialogOpen"] is True, report
    assert report["keys"] == ["tokdash-announcement-dismissed", "tokdash-sessions-split", "tokdash-theme"], report

    # The dismissed announcement stays dismissed, and the column split that was
    # reset stays reset: each key owns its own state across the reload.
    assert report["announcement"]["shown"] is False, report["announcement"]
    assert report["cols"] == ["40%", "30%", "30%"], report
    assert report["dividers"] == 2, report
    assert report["toastRegion"] == 0, report
