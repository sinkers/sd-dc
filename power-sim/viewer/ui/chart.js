// Time-of-day trend chart, SVG, no library. One x axis spanning the run (a day,
// or a 45-minute window around a disturbance), any number of series, optional
// reference lines and shaded bands, and a cursor shared with the rest of the
// page. Drag on it to scrub.
//
//   const c = chart({ title: 'Power', unit: 'kW', series: [{ label, cls, get: (r) => r.x }] , onCursor });
//   el.append(c.el); c.update(rows); c.cursor(i);

import { fix } from './format.js';

const NS = 'http://www.w3.org/2000/svg';
const PAD = { l: 58, r: 14, t: 10, b: 24 };

function s(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
}

function niceStep(span, target = 5) {
  const raw = span / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * mag).find((m) => m >= raw) ?? raw;
}

export function chart({ title, unit = '', height = 160, series, scale = null, yMin = null, yMax = null,
                        fmt = (v) => fix(v, 0), onCursor = () => {} }) {
  const el = document.createElement('div');
  el.className = 'chart';
  const legend = document.createElement('div');
  legend.className = 'legend';
  const svgEl = s('svg', { height, role: 'img', 'aria-label': title });
  el.append(legend, svgEl);

  const head = document.createElement('b');
  head.textContent = title;
  legend.append(head);
  const vals = series.map((se) => {
    const span = document.createElement('span');
    span.className = se.cls;
    const i = document.createElement('i');
    const name = document.createElement('span');
    name.textContent = se.label;
    name.style.color = 'var(--muted)';
    const v = document.createElement('span');
    v.className = 'val';
    span.append(i, name, v);
    if (!se.hideLegend) legend.append(span);
    return v;
  });

  let rows = [], refs = [], bands = [], cur = 0, w = 600, geom = null, useScale = scale;
  const f = () => useScale?.f ?? ((x) => x);

  function draw() {
    svgEl.replaceChildren();
    w = Math.max(320, el.clientWidth || 600);
    svgEl.setAttribute('width', w);
    svgEl.setAttribute('viewBox', `0 0 ${w} ${height}`);
    if (!rows.length || el.hidden) return;

    const values = series.flatMap((se) => rows.map(se.get)).filter(Number.isFinite);
    for (const r of refs) values.push(r.value);
    let lo = yMin ?? Math.min(0, ...values), hi = yMax ?? Math.max(...values);
    if (hi - lo < 1e-9) hi = lo + 1;
    const F = f();
    const flo = F(lo), fhi = F(hi);
    const pad = (fhi - flo) * 0.06;
    const y0 = yMin != null ? flo : flo - (lo < 0 ? pad : 0), y1 = yMax != null ? fhi : fhi + pad;
    const dtR = rows.length > 1 ? rows[1].t - rows[0].t : 1 / 12;
    const t0 = rows[0].t, t1 = rows.at(-1).t + dtR;
    const X = (t) => PAD.l + ((t - t0) / (t1 - t0)) * (w - PAD.l - PAD.r);
    const Y = (v) => PAD.t + (1 - (F(v) - y0) / (y1 - y0)) * (height - PAD.t - PAD.b);
    geom = { X, t0, dtR };

    const grid = s('g', { class: 'grid' }, svgEl);
    const axis = s('g', { class: 'axis' }, svgEl);
    // y ticks: linear steps, or decades on the price scale
    let ticks = [];
    if (useScale) {
      const decades = [-10000, -1000, -100, 0, 100, 1000, 10000];
      ticks = decades.filter((v) => F(v) >= y0 - 1e-9 && F(v) <= y1 + 1e-9);
      if (ticks.length < 3) ticks = [lo, 0, hi].filter((v, i, a) => a.indexOf(v) === i);
    } else {
      const st = niceStep(hi - lo);
      for (let v = Math.ceil(lo / st) * st; v <= hi + 1e-9; v += st) ticks.push(v);
    }
    for (const v of ticks) {
      const y = Y(v);
      s('line', { x1: PAD.l, x2: w - PAD.r, y1: y, y2: y }, grid);
      const t = s('text', { x: PAD.l - 6, y: y + 4, 'text-anchor': 'end' }, axis);
      t.textContent = fmt(v);
    }
    // time ticks: the coarsest step that still gives a handful of them
    const span = t1 - t0;
    const tickH = [1 / 60, 2 / 60, 5 / 60, 10 / 60, 0.25, 0.5, 1, 3, 6].find((st) => span / st <= 8) ?? 6;
    for (let h = Math.ceil(t0 / tickH - 1e-9) * tickH; h <= t1 + 1e-9; h += tickH) {
      const x = X(h);
      s('line', { x1: x, x2: x, y1: PAD.t, y2: height - PAD.b }, grid);
      const m = Math.round(h * 60) % 1440;
      const t = s('text', { x, y: height - 7, 'text-anchor': x < PAD.l + 20 ? 'start' : x > w - PAD.r - 20 ? 'end' : 'middle' }, axis);
      t.textContent = `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
    }
    const u = s('text', { x: 6, y: PAD.t + 9, class: 'tick' }, axis);
    u.textContent = unit;

    for (const b of bands) {
      // a 150 ms sag is narrower than a pixel; draw it at least 3 px wide
      s('rect', { x: X(b.from) - 1, y: PAD.t, width: Math.max(3, X(b.to) - X(b.from)), height: height - PAD.t - PAD.b,
                  class: `band ${b.cls ?? ''}` }, svgEl);
    }
    if (lo < 0 && hi > 0) s('line', { x1: PAD.l, x2: w - PAD.r, y1: Y(0), y2: Y(0), class: 'zero' }, svgEl);

    const dt = rows.length > 1 ? rows[1].t - rows[0].t : 1 / 12;
    for (const se of series) {
      const pts = rows.map((r) => [r.t, se.get(r)]);
      let d = '';
      if (se.kind === 'area') {
        d = `M${X(pts[0][0])},${Y(0)}`;
        for (const [t, v] of pts) d += `L${X(t)},${Y(v)}L${X(t + dt)},${Y(v)}`;
        d += `L${X(pts.at(-1)[0] + dt)},${Y(0)}Z`;
        s('path', { d, class: se.cls, fill: 'currentColor', 'fill-opacity': 0.35, stroke: 'none' }, svgEl);
        continue;
      }
      pts.forEach(([t, v], i) => {
        if (!Number.isFinite(v)) return;
        const cmd = i === 0 || !Number.isFinite(pts[i - 1][1]) ? 'M' : 'L';
        if (se.kind === 'step') d += `${cmd}${X(t)},${Y(v)}L${X(t + dt)},${Y(v)}`;
        else d += `${cmd}${X(t)},${Y(v)}`;
      });
      s('path', { d, class: se.cls, fill: 'none', 'stroke-width': se.width ?? 1.75, 'stroke-linejoin': 'round',
                  ...(se.dash ? { 'stroke-dasharray': se.dash } : {}) }, svgEl);
    }
    for (const r of refs) {
      const y = Y(r.value);
      s('line', { x1: PAD.l, x2: w - PAD.r, y1: y, y2: y, class: `ref ${r.cls}` }, svgEl);
      const t = s('text', { x: w - PAD.r - 4, y: r.below ? y + 13 : y - 4, 'text-anchor': 'end', class: 'tick' }, svgEl);
      t.textContent = r.label;
    }
    const cx = X(rows[cur]?.t ?? 0);
    geom.cursor = s('line', { x1: cx, x2: cx, y1: PAD.t, y2: height - PAD.b, class: 'cursor' }, svgEl);
    paintLegend();
  }

  function paintLegend() {
    const r = rows[cur];
    series.forEach((se, i) => { vals[i].textContent = r ? (se.fmt ?? fmt)(se.get(r)) : ''; });
  }

  function cursor(i) {
    cur = Math.max(0, Math.min(rows.length - 1, i));
    if (geom?.cursor && rows[cur]) {
      const x = geom.X(rows[cur].t);
      geom.cursor.setAttribute('x1', x);
      geom.cursor.setAttribute('x2', x);
    }
    paintLegend();
  }

  function pick(ev) {
    if (!rows.length || !geom) return;
    const box = svgEl.getBoundingClientRect();
    const frac = (ev.clientX - box.left - PAD.l) / (box.width - PAD.l - PAD.r);
    onCursor(Math.max(0, Math.min(rows.length - 1, Math.floor(frac * rows.length))));
  }
  svgEl.addEventListener('pointerdown', (e) => { svgEl.setPointerCapture(e.pointerId); pick(e); });
  svgEl.addEventListener('pointermove', (e) => { if (e.buttons) pick(e); });

  new ResizeObserver(() => { if (Math.abs((el.clientWidth || 0) - w) > 2) draw(); }).observe(el);

  return {
    el,
    show(on) { el.hidden = !on; if (on) draw(); },
    update(nextRows, opts = {}) {
      rows = nextRows;
      refs = opts.refs ?? refs;
      bands = opts.bands ?? bands;
      if ('scale' in opts) useScale = opts.scale;
      cur = Math.min(cur, rows.length - 1);
      draw();
    },
    cursor,
  };
}
