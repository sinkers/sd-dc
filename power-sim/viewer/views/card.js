// An equipment card: name and kind, a state pill, the kind's dials and
// readouts, and the controls built from the component's schema. One function
// for every kind, driven by views/kinds.js.

import { dial } from '../ui/dial.js';
import { controls } from '../ui/controls.js';
import { kindOf } from './kinds.js';

export function card(id, meta, values, onChange) {
  const k = kindOf(meta.kind);
  const el = document.createElement('section');
  el.className = 'panel card';
  el.id = `asset-${id}`;

  const h = document.createElement('h2');
  const title = document.createElement('span');
  title.className = 'tag';
  title.textContent = meta.name;
  const kind = document.createElement('span');
  kind.className = `kind${meta.kind_proposed ? ' proposed' : ''}`;
  kind.textContent = `${id} · ${meta.kind}`;
  const spacer = document.createElement('span');
  spacer.className = 'spacer';
  const pill = document.createElement('span');
  pill.className = 'pill';
  h.append(title, kind, spacer, pill);

  const body = document.createElement('div');
  body.className = 'body';

  const dialRow = document.createElement('div');
  dialRow.className = 'dials';
  const dials = k.dials.map((d) => {
    const g = dial({ label: d.label, unit: d.unit, format: d.format, centerZero: d.centerZero, scale: d.scale,
                     limLabels: d.limLabels });
    dialRow.append(g.el);
    return { def: d, g, key: '' };
  });
  if (dials.length) body.append(dialRow);

  const dl = document.createElement('dl');
  dl.className = 'stats';
  const stats = k.stats.map(([label, fn]) => {
    const div = document.createElement('div');
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    div.append(dt, dd);
    dl.append(div);
    return { fn, dd };
  });
  if (stats.length) body.append(dl);

  const ctl = controls(meta.schema, values, onChange, { prefix: id });
  if (meta.schema.length) body.append(ctl.el);
  el.append(h, body);

  function update(snap, ctx) {
    if (!snap) return;
    const st = k.state(snap);
    pill.textContent = st.text || '—';
    pill.className = `pill ${st.cls}`;
    for (const d of dials) {
      const [lo, hi] = d.def.range(snap, ctx);
      const bands = d.def.bands ? d.def.bands(snap, ctx) : [];
      const key = `${lo}|${hi}|${bands.map((b) => `${b.from}-${b.to}`).join()}`;
      if (key !== d.key) { d.g.setRange(lo, hi, bands); d.key = key; }
      d.g.set(d.def.value(snap, ctx), d.def.cls ? d.def.cls(snap, ctx) : '');
    }
    for (const s of stats) s.dd.textContent = s.fn(snap);
  }

  return { el, update, set: ctl.set };
}
