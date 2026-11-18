// Equipment views, in two halves, driven by views/kinds.js for every kind:
//
//   readout()   name, state pill, dials and figures: what it is doing now.
//               Lives on the Simulation tab. Money (prices, bills, fuel cost)
//               is left out here; that belongs to the Reports tab.
//   settings()  the controls built from the component's schema.
//               Lives on the Config tab.

import { dial } from '../ui/dial.js';
import { controls } from '../ui/controls.js';
import { kindOf } from './kinds.js';

function header(id, meta, { pill = false } = {}) {
  const h = document.createElement('h2');
  const title = document.createElement('span');
  title.className = 'tag';
  title.textContent = meta.name;
  const kind = document.createElement('span');
  kind.className = `kind${meta.kind_proposed ? ' proposed' : ''}`;
  kind.textContent = `${id} · ${meta.kind}`;
  const spacer = document.createElement('span');
  spacer.className = 'spacer';
  h.append(title, kind, spacer);
  let p = null;
  if (pill) {
    p = document.createElement('span');
    p.className = 'pill';
    h.append(p);
  }
  return { h, pill: p };
}

export function readout(id, meta) {
  const k = kindOf(meta.kind);
  const el = document.createElement('section');
  el.className = 'panel card readout';
  el.id = `live-${id}`;
  const { h, pill } = header(id, meta, { pill: true });
  const body = document.createElement('div');
  body.className = 'body';

  const dialRow = document.createElement('div');
  dialRow.className = 'dials';
  const dials = k.dials.filter((d) => !d.pricing).map((d) => {
    const g = dial({ label: d.label, unit: d.unit, format: d.format, centerZero: d.centerZero, scale: d.scale,
                     limLabels: d.limLabels });
    dialRow.append(g.el);
    return { def: d, g, key: '' };
  });
  if (dials.length) body.append(dialRow);

  const dl = document.createElement('dl');
  dl.className = 'stats';
  const stats = k.stats.filter((s) => !s[2]?.pricing).map(([label, fn]) => {
    const div = document.createElement('div');
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    div.append(dt, dd);
    dl.append(div);
    return { fn, dd };
  });
  if (stats.length) body.append(dl);
  el.append(h, body);

  function update(snap, ctx) {
    if (!snap) return;
    const st = k.state(snap);
    const t = st.text || '—', c = `pill ${st.cls}`;
    if (pill.textContent !== t) pill.textContent = t;
    if (pill.className !== c) pill.className = c;
    for (const d of dials) {
      const [lo, hi] = d.def.range(snap, ctx);
      const bands = d.def.bands ? d.def.bands(snap, ctx) : [];
      const key = `${lo}|${hi}|${bands.map((b) => `${b.from}-${b.to}`).join()}`;
      if (key !== d.key) { d.g.setRange(lo, hi, bands); d.key = key; }
      d.g.set(d.def.value(snap, ctx), d.def.cls ? d.def.cls(snap, ctx) : '');
    }
    for (const s of stats) {
      const t = s.fn(snap);
      if (s.dd.textContent !== t) s.dd.textContent = t;
    }
  }

  return { el, update, empty: !dials.length && !stats.length };
}

export function settings(id, meta, values, onChange) {
  const el = document.createElement('section');
  el.className = 'panel card settings';
  el.id = `asset-${id}`;
  const { h } = header(id, meta);
  const body = document.createElement('div');
  body.className = 'body';
  const ctl = controls(meta.schema, values, onChange, { prefix: id });
  body.append(ctl.el);
  el.append(h, body);
  return { el, set: ctl.set };
}
