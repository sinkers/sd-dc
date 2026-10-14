// Single-line diagram, laid out from the model itself: the cables give a tree
// rooted at the supply, each depth is a row, busbars span their feeders, and a
// controller sits under the asset it drives. Nothing here knows about any one
// simulation. A model from a drag-and-drop editor lays out the same way.
//
// Power flow is animated along each conductor: direction is the direction of
// flow, colour says whether it is storage charging or discharging, and the
// figure beside it is kW.

import { kindOf } from '../views/kinds.js';
import { kw } from './format.js';

const NS = 'http://www.w3.org/2000/svg';
const BOX_W = 200, BOX_H = 64, COL = 250, ROW = 118, M = 24;

function s(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
}

function glyph(g, kind, x, y) {
  const G = s('g', { class: 'glyph', transform: `translate(${x},${y})` }, g);
  switch (kind) {
    case 'grid':
      s('circle', { cx: 14, cy: 14, r: 13 }, G);
      s('path', { d: 'M4,14 C8,6 11,6 14,14 S20,22 24,14' }, G);
      break;
    case 'battery':
      s('path', { d: 'M3,9 H25 M8,15 H20 M3,21 H25 M8,27 H20 M14,1 V9 M14,27 V31' }, G);
      break;
    case 'converter':
      s('rect', { x: 1, y: 1, width: 26, height: 26 }, G);
      s('path', { d: 'M27,1 L1,27 M4,8 C6,5 8,5 10,8 S14,11 16,8 M15,21 H24 M15,24 H24' }, G);
      break;
    case 'rack':
      s('rect', { x: 4, y: 0, width: 20, height: 28 }, G);
      s('path', { d: 'M7,6 H21 M7,11 H21 M7,16 H21 M7,21 H21' }, G);
      break;
    case 'gen': {
      s('circle', { cx: 14, cy: 14, r: 13 }, G);
      const t = s('text', { x: 14, y: 19, 'text-anchor': 'middle', class: 'glyph-text' }, G);
      t.textContent = 'G';
      break;
    }
    case 'controller':
      s('rect', { x: 1, y: 5, width: 26, height: 18, rx: 2 }, G);
      s('path', { d: 'M7,14 h0 M14,14 h0 M21,14 h0', 'stroke-width': 4, 'stroke-linecap': 'round' }, G);
      break;
    default:
      s('rect', { x: 1, y: 1, width: 26, height: 26 }, G);
  }
}

export function oneline(container, desc, { onSelect = () => {} } = {}) {
  const model = desc.model;
  const meta = desc.assets;
  const role = (id) => meta[id]?.role;
  const kindKey = (id) => meta[id]?.kind;

  const children = Object.fromEntries(model.assets.map((a) => [a.id, []]));
  const parent = {};
  const controllerOf = {};
  const genOf = {};   // generator id -> the bus it lands on, through the transfer switch
  const owner = (iface) => iface.split('.')[0];
  for (const c of model.connections) {
    const a = owner(c.from), b = owner(c.to);
    if (c.type === 'cable' && role(a) === 'generator') genOf[a] = b;
    else if (c.type === 'cable') { children[a].push(b); parent[b] = a; }
    else if (role(a) === 'controller') controllerOf[b] = a;
    else if (role(b) === 'controller') controllerOf[a] = b;
  }
  const root = model.assets.find((a) => role(a.id) === 'source')?.id;

  // depth, then leaf columns, then parents centred over their children
  const pos = {};
  let col = 0, maxRow = 0;
  (function place(id, depth) {
    const kids = children[id];
    let x;
    if (!kids.length) x = col++;
    else {
      const xs = kids.map((k) => place(k, depth + 1));
      x = (Math.min(...xs) + Math.max(...xs)) / 2;
    }
    pos[id] = { col: x, row: depth };
    maxRow = Math.max(maxRow, depth);
    return x;
  })(root, 0);
  for (const [target, ctrl] of Object.entries(controllerOf)) {
    pos[ctrl] = { col: pos[target].col, row: pos[target].row + 1 };
    maxRow = Math.max(maxRow, pos[ctrl].row);
  }
  // A generator sits beside the supply that feeds its bus, one column over.
  for (const [g, bus] of Object.entries(genOf)) {
    const above = parent[bus] ?? bus;
    pos[g] = { col: pos[above].col + 1, row: Math.max(0, pos[bus].row - 1) };
  }
  const cols = Math.max(1, col, ...Object.values(pos).map((p) => p.col + 1));
  const W = cols * COL + 2 * M, H = (maxRow + 1) * ROW + M;
  const X = (id) => M + COL / 2 + pos[id].col * COL;
  const Y = (id) => M + BOX_H / 2 + pos[id].row * ROW;

  container.replaceChildren();
  const svgEl = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'sld', style: `width:${Math.round(W * 1.25)}px`, role: 'img', 'aria-label': 'Single-line diagram' });
  container.append(svgEl);
  const gLines = s('g', {}, svgEl), gFlow = s('g', {}, svgEl), gEquip = s('g', {}, svgEl);

  // busbars
  const busY = {};
  for (const a of model.assets) {
    if (role(a.id) !== 'bus') continue;
    const xs = [...children[a.id], ...Object.keys(genOf).filter((g) => genOf[g] === a.id)].map(X);
    const x0 = Math.min(X(a.id) - 60, ...xs) - 50, x1 = Math.max(X(a.id) + 60, ...xs) + 50;
    busY[a.id] = Y(a.id);
    s('line', { x1: x0, x2: x1, y1: busY[a.id], y2: busY[a.id], class: 'busbar' }, gLines);
    const t = s('text', { x: x0, y: busY[a.id] - 12, class: 'name' }, gEquip);
    t.textContent = a.name;
    const tag = s('text', { x: x0, y: busY[a.id] + 22, class: 'tagid' }, gEquip);
    tag.textContent = `${a.id} · ${a.kind}`;
  }

  // conductors
  const edges = [];
  for (const [p, kids] of Object.entries(children)) {
    for (const c of kids) {
      const sx = role(p) === 'bus' ? X(c) : X(p);
      const sy = role(p) === 'bus' ? busY[p] : Y(p) + BOX_H / 2;
      const ex = role(c) === 'bus' ? X(p) : X(c);
      const ey = role(c) === 'bus' ? busY[c] : Y(c) - BOX_H / 2;
      const my = (sy + ey) / 2;
      const fwd = sx === ex ? `M${sx},${sy} V${ey}` : `M${sx},${sy} V${my} H${ex} V${ey}`;
      const rev = sx === ex ? `M${ex},${ey} V${sy}` : `M${ex},${ey} V${my} H${sx} V${sy}`;
      const line = s('path', { d: fwd, class: 'conductor' }, gLines);
      const flow = s('path', { d: fwd, class: 'flow fwd' }, gFlow);
      const label = s('text', { x: ex + 8, y: (sy + ey) / 2 + 4, class: 'kw' }, gEquip);
      edges.push({ child: c, line, flow, label, fwd, rev });
    }
  }
  for (const [g, bus] of Object.entries(genOf)) {
    const sx = X(g), sy = Y(g) + BOX_H / 2, ey = busY[bus];
    const fwd = `M${sx},${sy} V${ey}`, rev = `M${sx},${ey} V${sy}`;
    const line = s('path', { d: fwd, class: 'conductor' }, gLines);
    const flow = s('path', { d: fwd, class: 'flow gen' }, gFlow);
    const label = s('text', { x: sx + 8, y: (sy + ey) / 2 + 4, class: 'kw' }, gEquip);
    const ats = s('text', { x: sx + 8, y: ey - 8, class: 'tagid' }, gEquip);
    ats.textContent = 'ATS';
    edges.push({ child: g, line, flow, label, fwd, rev, gen: true });
  }
  for (const [target, ctrl] of Object.entries(controllerOf)) {
    s('path', { d: `M${X(ctrl)},${Y(ctrl) - BOX_H / 2} V${Y(target) + BOX_H / 2}`, class: 'datalink' }, gLines);
  }

  // equipment
  const boxes = {};
  for (const a of model.assets) {
    if (role(a.id) === 'bus') continue;
    const k = kindOf(a.kind);
    const x = X(a.id) - BOX_W / 2, y = Y(a.id) - BOX_H / 2;
    const g = s('g', { tabindex: 0, role: 'button', 'aria-label': `${a.name}, show settings`, style: 'cursor:pointer' }, gEquip);
    const rect = s('rect', { x, y, width: BOX_W, height: BOX_H, rx: 4, class: 'equip' }, g);
    glyph(g, k.glyph, x + 10, y + 17);
    const name = s('text', { x: x + 48, y: y + 20, class: 'name' }, g);
    name.textContent = a.name;
    const tag = s('text', { x: x + 48, y: y + 35, class: 'tagid' }, g);
    tag.textContent = `${a.id} · ${a.kind}${meta[a.id]?.kind_proposed ? '*' : ''}`;
    const state = s('text', { x: x + 48, y: y + 52, class: 'state' }, g);
    const kwText = s('text', { x: x + BOX_W - 10, y: y + 52, 'text-anchor': 'end', class: 'kw' }, g);
    // State of charge, for anything with a battery: a figure top right and a
    // bar along the bottom edge of the box.
    // A badge sits above the box, clear of its name and of any neighbour: the grid's price.
    const badge = k.badge ? s('text', { x: x + BOX_W / 2, y: y - 7, 'text-anchor': 'middle', class: 'price' }, g) : null;
    let soc = null;
    if (k.soc) {
      const text = s('text', { x: x + BOX_W - 10, y: y + 20, 'text-anchor': 'end', class: 'soc' }, g);
      s('rect', { x: x + 1.5, y: y + BOX_H - 7, width: BOX_W - 3, height: 5, class: 'soc-track' }, g);
      const bar = s('rect', { x: x + 1.5, y: y + BOX_H - 7, width: 0, height: 5, class: 'soc-bar' }, g);
      soc = { text, bar };
    }
    g.addEventListener('click', () => onSelect(a.id));
    g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(a.id); } });
    boxes[a.id] = { rect, state, kwText, soc, badge, kind: k };
  }

  function update(row) {
    const A = row.assets;
    for (const e of edges) {
      const snap = A[e.child];
      const k = kindOf(kindKey(e.child));
      const v = (k.draw ?? k.kw)(snap) ?? 0;
      const live = Math.abs(v) > 0.05;
      e.flow.style.display = live ? '' : 'none';
      e.line.classList.toggle('dead', !row.grid_up && !live);
      if (live) {
        const storage = role(e.child) === 'storage';
        e.flow.setAttribute('d', v >= 0 ? e.fwd : e.rev);
        e.flow.setAttribute('class', `flow ${e.gen ? 'gen' : storage ? (v > 0 ? 'chg' : 'rev') : v >= 0 ? 'fwd' : 'rev'}`);
        e.flow.style.setProperty('--dur', `${Math.max(0.35, 2.2 - Math.log10(Math.abs(v) + 1) * 0.7).toFixed(2)}s`);
      }
      e.label.textContent = live ? `${kw(Math.abs(v))} kW` : '';
    }
    for (const [id, b] of Object.entries(boxes)) {
      const snap = A[id];
      if (!snap) continue;
      const st = b.kind.state(snap);
      b.state.textContent = st.text;
      b.state.setAttribute('class', `state ${st.cls}`);
      const v = b.kind.kw(snap);
      b.kwText.textContent = v == null ? '' : `${kw(v)} kW`;
      if (b.badge) {
        const bd = b.kind.badge(snap);
        b.badge.textContent = bd.text;
        b.badge.setAttribute('class', bd.cls);
      }
      if (b.soc) {
        const { pct, cls } = b.kind.soc(snap);
        b.soc.text.textContent = `SoC ${Math.round(pct)} %`;
        b.soc.bar.setAttribute('width', ((BOX_W - 3) * Math.max(0, Math.min(100, pct))) / 100);
        b.soc.bar.setAttribute('class', `soc-bar ${cls}`);
      }
      b.rect.setAttribute('class', `equip${st.cls === 'alarm' ? ' alarm' : ''}${snap.enabled === false ? ' off' : ''}`);
    }
  }

  return { update };
}
