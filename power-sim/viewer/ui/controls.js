// Controls built from a component's parameter schema (dtpower.params). The
// same schema the Python model resolves its values through, served as JSON, so
// a new component arrives with its sliders already defined.
//
//   const c = controls(schema, values, (key, value) => ...);
//   card.append(c.el); c.set(values);

let uid = 0;

function control(f, value, onChange, prefix, showHelp = true) {
  const id = `${prefix}-${f.key}`;
  const row = document.createElement('div');
  row.className = `ctl ${f.kind}`;
  const label = document.createElement('label');
  label.htmlFor = id;
  const name = document.createElement('span');
  name.textContent = f.label;
  label.append(name);
  let input, show;

  if (f.kind === 'range') {
    // A slider for feel, and a number box for an exact value: a 0 to 15,000
    // range cannot be dragged to $250 precisely.
    const wrap = document.createElement('span');
    wrap.className = 'num-wrap';
    const box = document.createElement('input');
    Object.assign(box, { type: 'number', className: 'num', min: f.min, max: f.max, step: f.step ?? 1 });
    box.setAttribute('aria-label', `${f.label} value`);
    const unit = document.createElement('span');
    unit.className = 'unit';
    unit.textContent = f.unit ?? '';
    wrap.append(box, unit);
    label.append(wrap);
    input = document.createElement('input');
    Object.assign(input, { type: 'range', id, min: f.min, max: f.max, step: f.step ?? 1 });
    show = (v) => { input.value = v; box.value = v; };
    input.addEventListener('input', () => { box.value = input.value; onChange(f.key, Number(input.value)); });
    box.addEventListener('change', () => {
      let v = Number(box.value);
      if (!Number.isFinite(v)) v = Number(input.value);
      v = Math.min(f.max ?? v, Math.max(f.min ?? v, v));
      show(v);
      onChange(f.key, v);
    });
    row.append(label, input);
  } else if (f.kind === 'toggle') {
    input = document.createElement('input');
    Object.assign(input, { type: 'checkbox', id, className: 'switch' });
    input.setAttribute('role', 'switch');
    show = (v) => { input.checked = Boolean(v); };
    input.addEventListener('change', () => onChange(f.key, input.checked));
    label.append(input);
    row.append(label);
  } else {
    input = document.createElement('select');
    input.id = id;
    for (const o of f.options) input.append(new Option(o.label, o.value));
    show = (v) => { input.value = v; };
    input.addEventListener('change', () => onChange(f.key, input.value));
    row.append(label, input);
  }
  if (f.help && showHelp) {
    const h = document.createElement('div');
    h.className = 'help';
    h.textContent = f.help;
    row.append(h);
  }
  show(value ?? f.default);
  return { row, show };
}

export function controls(schema, values, onChange, { prefix = `c${++uid}`, only = null, help = true } = {}) {
  const el = document.createElement('div');
  el.className = 'controls';
  const more = document.createElement('details');
  more.className = 'more';
  const summary = document.createElement('summary');
  summary.textContent = 'More settings';
  const moreBody = document.createElement('div');
  moreBody.className = 'controls';
  more.append(summary, moreBody);

  const shows = {};
  for (const f of schema) {
    if (only && !only.includes(f.key)) continue;
    const { row, show } = control(f, values[f.key], onChange, prefix, help);
    shows[f.key] = show;
    (f.advanced ? moreBody : el).append(row);
  }
  if (moreBody.childElementCount) el.append(more);

  return {
    el,
    set(next) { for (const [k, show] of Object.entries(shows)) show(next[k]); },
  };
}

/** Defaults for a schema, overlaid with partial values. */
export function resolve(schema, values = {}) {
  const out = {};
  for (const f of schema) out[f.key] = values[f.key] ?? f.default;
  return out;
}
