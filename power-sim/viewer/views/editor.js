// Scenario editor. A scenario is a price day, a window, a step and a list of
// injected events on a timeline: voltage sags, grid outages, price spikes and
// load changes, one lane each. Drag an event type from the palette onto its
// lane, drag a placed event to move it, select it to set its details. Every
// change re-runs the scenario.
//
// The editor always mirrors the scenario in view: picking a preset loads its
// events here, and editing them makes it a custom scenario.

import { controls } from '../ui/controls.js';

const LANES = ['sag', 'outage', 'price', 'load'];
const LANE_LABEL = { sag: 'Voltage sags', outage: 'Grid outages', price: 'Price spikes', load: 'Load changes' };

export const toClock = (h, secs = true) => {
  const s = Math.round(h * 3600) % 86400;
  const hh = String(Math.floor(s / 3600)).padStart(2, '0');
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  return secs ? `${hh}:${mm}:${String(s % 60).padStart(2, '0')}` : `${hh}:${mm}`;
};
const fromClock = (v) => {
  const [h = 0, m = 0, s = 0] = String(v).split(':').map(Number);
  return (h * 3600 + m * 60 + s) / 3600;
};

/** How long an event lasts, in hours, for drawing it. */
function spanH(e) {
  if (e.type === 'sag') return e.duration_ms / 3.6e6;
  if (e.type === 'outage') return e.duration_s / 3600;
  return e.duration_min / 60;
}

function summary(e) {
  if (e.type === 'sag') return `${e.residual_pct} % for ${e.duration_ms} ms`;
  if (e.type === 'outage') return e.duration_s >= 120 ? `${Math.round(e.duration_s / 60)} min` : `${e.duration_s} s`;
  if (e.type === 'price') return `$${Number(e.price).toLocaleString('en-AU')}/MWh, ${e.duration_min} min`;
  return `${e.utilisation_pct} % for ${e.duration_min} min`;
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else e.setAttribute(k, v);
  }
  e.append(...kids);
  return e;
}

export function editor(host, desc, { onChange, getCursorH = () => null }) {
  const meta = desc.editor;
  let spec = null, selected = null, uid = 0, fromPreset = null;

  // ── layout ───────────────────────────────────────────────────────────
  const name = el('input', { type: 'text', id: 'ed-name', maxlength: '120' });
  const price = el('select', { id: 'ed-price' });
  for (const p of meta.price_sources) price.append(new Option(p.label, p.value));
  const flat = el('input', { type: 'number', id: 'ed-flat', step: '5', min: '-1000', max: '17500' });
  const flatWrap = el('label', { class: 'field-inline', for: 'ed-flat' }, el('span', { text: 'Flat price, $/MWh' }), flat);
  const from = el('input', { type: 'time', id: 'ed-from', step: '60' });
  const to = el('input', { type: 'time', id: 'ed-to', step: '60' });
  const step = el('select', { id: 'ed-step' });
  for (const s of meta.dt_choices) step.append(new Option(s < 60 ? `${s} s` : `${s / 60} min`, s));
  const steps = el('span', { class: 'n', id: 'ed-steps' });

  const row = el('div', { class: 'ed-row' },
    el('label', { class: 'field-inline grow2', for: 'ed-name' }, el('span', { text: 'Name' }), name),
    el('label', { class: 'field-inline grow2', for: 'ed-price' }, el('span', { text: 'Price day' }), price),
    flatWrap,
    el('label', { class: 'field-inline', for: 'ed-from' }, el('span', { text: 'From' }), from),
    el('label', { class: 'field-inline', for: 'ed-to' }, el('span', { text: 'To' }), to),
    el('label', { class: 'field-inline', for: 'ed-step' }, el('span', { text: 'Step' }), step),
    steps);

  const palette = el('div', { class: 'ed-palette', role: 'group', 'aria-label': 'Event types' },
    el('span', { class: 'k', text: 'Add an event' }));
  for (const type of LANES) {
    const chip = el('button', { type: 'button', class: `chip ev-${type}`, draggable: 'true', 'data-type': type,
                                title: 'Drag onto the timeline, or click to add at the playback time' },
      el('i'), meta.event_types[type].label);
    chip.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/plain', type); e.dataTransfer.effectAllowed = 'copy'; });
    chip.addEventListener('click', () => add(type, getCursorH() ?? (spec.window[0] + spec.window[1]) / 2));
    palette.append(chip);
  }
  const clear = el('button', { type: 'button', class: 'ghost', text: 'Clear events' });
  clear.addEventListener('click', () => { spec.events = []; selected = null; render(); emit(); });
  palette.append(el('span', { class: 'grow' }), clear);

  const axis = el('div', { class: 'ed-axis' });
  const lanes = el('div', { class: 'ed-lanes' });
  const cursor = el('div', { class: 'ed-cursor' });
  const tracks = {};
  for (const type of LANES) {
    const track = el('div', { class: 'ed-track', 'data-type': type });
    track.addEventListener('dragover', (e) => { e.preventDefault(); track.classList.add('over'); });
    track.addEventListener('dragleave', () => track.classList.remove('over'));
    track.addEventListener('drop', (e) => {
      e.preventDefault();
      track.classList.remove('over');
      const t = e.dataTransfer.getData('text/plain');
      if (LANES.includes(t)) add(t, timeAt(track, e.clientX));
    });
    tracks[type] = track;
    lanes.append(el('div', { class: 'ed-lane' }, el('span', { class: 'ed-lane-label', text: LANE_LABEL[type] }), track));
  }
  const timeline = el('div', { class: 'ed-timeline' }, axis, lanes);
  lanes.append(cursor);

  const props = el('div', { class: 'ed-props' });
  const body = el('div', { class: 'body ed-body' }, row, palette, timeline, props);
  host.append(body);

  // ── behaviour ────────────────────────────────────────────────────────
  const span = () => spec.window[1] - spec.window[0];
  const pct = (t) => ((t - spec.window[0]) / span()) * 100;
  const snap = (t) => {
    const st = spec.dt_s / 3600;
    return Math.min(spec.window[1] - st, Math.max(spec.window[0], Math.round(t / st) * st));
  };
  function timeAt(track, clientX) {
    const r = track.getBoundingClientRect();
    return snap(spec.window[0] + ((clientX - r.left) / r.width) * span());
  }

  function add(type, t) {
    const fields = Object.fromEntries(meta.event_types[type].schema.map((f) => [f.key, f.default]));
    const ev = { _id: ++uid, type, t: snap(t), ...fields };
    spec.events.push(ev);
    selected = ev._id;
    render();
    emit();
  }

  function emit() {
    // The first change to a preset makes it a different scenario; say so in
    // its name, so a report cannot be mistaken for the preset's.
    if (fromPreset && spec.label === fromPreset) {
      spec.label = `${fromPreset} (edited)`;
      name.value = spec.label;
    }
    fromPreset = null;
    validate();
    if (!steps.classList.contains('neg')) onChange(clean());
  }

  function clean() {
    return {
      label: spec.label, price: spec.price, flat_price: spec.flat_price, window: [...spec.window], dt_s: spec.dt_s,
      events: spec.events.map(({ _id, ...e }) => e).sort((a, b) => a.t - b.t),
    };
  }

  function validate() {
    const n = Math.round((span() * 3600) / spec.dt_s);
    const over = n > meta.max_steps;
    steps.textContent = over ? `${n.toLocaleString('en-AU')} steps: over the ${meta.max_steps.toLocaleString('en-AU')} limit, use a longer step`
      : `${n.toLocaleString('en-AU')} steps`;
    steps.classList.toggle('neg', over);
  }

  function renderAxis() {
    axis.replaceChildren();
    const sp = span();
    const tick = [1 / 60, 5 / 60, 10 / 60, 0.25, 0.5, 1, 2, 3, 6].find((s) => sp / s <= 8) ?? 6;
    for (let h = Math.ceil(spec.window[0] / tick - 1e-9) * tick; h <= spec.window[1] + 1e-9; h += tick) {
      axis.append(el('span', { style: `left:${pct(h)}%`, text: toClock(h, false) }));
    }
  }

  function renderEvents() {
    for (const tr of Object.values(tracks)) tr.replaceChildren();
    for (const ev of spec.events) {
      const w = (spanH(ev) / span()) * 100;
      const m = el('div', {
        class: `ev ev-${ev.type}${ev._id === selected ? ' sel' : ''}`, tabindex: '0', role: 'button',
        style: `left:${pct(ev.t)}%; width:max(10px, ${w}%)`,
        title: `${toClock(ev.t)} ${meta.event_types[ev.type].label}: ${summary(ev)}`,
        'aria-label': `${meta.event_types[ev.type].label} at ${toClock(ev.t)}, ${summary(ev)}`,
      }, el('span', { text: `${toClock(ev.t, spec.dt_s < 60)} · ${summary(ev)}` }));
      drag(m, ev);
      m.addEventListener('keydown', (e) => {
        const st = (spec.dt_s / 3600) * (e.shiftKey ? 10 : 1);
        if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
          e.preventDefault();
          ev.t = snap(ev.t + (e.key === 'ArrowRight' ? st : -st));
          render(); emit();
          tracks[ev.type].querySelector('.ev.sel')?.focus();
        } else if (e.key === 'Delete' || e.key === 'Backspace') {
          e.preventDefault(); remove(ev);
        }
      });
      tracks[ev.type].append(m);
    }
    fitLabels();
  }

  // A label may run on past its marker, but only as far as the next event in
  // the same lane; the full text is in the tooltip.
  function fitLabels() {
    for (const tr of Object.values(tracks)) {
      const w = tr.getBoundingClientRect().width;
      const ms = [...tr.children].sort((a, b) => parseFloat(a.style.left) - parseFloat(b.style.left));
      ms.forEach((m, i) => {
        const left = (parseFloat(m.style.left) / 100) * w;
        const next = ms[i + 1] ? (parseFloat(ms[i + 1].style.left) / 100) * w : w;
        m.style.setProperty('--room', `${Math.max(0, next - left - 10)}px`);
      });
    }
  }
  new ResizeObserver(() => spec && fitLabels()).observe(lanes);

  function drag(m, ev) {
    let start = null;
    m.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      try { m.setPointerCapture(e.pointerId); } catch { /* synthetic or stale pointer */ }
      const r = tracks[ev.type].getBoundingClientRect();
      start = { x: e.clientX, t: ev.t, w: r.width, moved: false };
      selected = ev._id;
      for (const x of host.querySelectorAll('.ev.sel')) x.classList.remove('sel');
      m.classList.add('sel');
      renderProps();
    });
    m.addEventListener('pointermove', (e) => {
      if (!start) return;
      const dx = e.clientX - start.x;
      if (Math.abs(dx) > 2) start.moved = true;
      ev.t = snap(start.t + (dx / start.w) * span());
      m.style.left = `${pct(ev.t)}%`;
      m.firstChild.textContent = `${toClock(ev.t, spec.dt_s < 60)} · ${summary(ev)}`;
    });
    const end = () => {
      if (start?.moved) { render(); emit(); }
      start = null;
    };
    m.addEventListener('pointerup', end);
    m.addEventListener('pointercancel', end);
  }

  function remove(ev) {
    spec.events = spec.events.filter((x) => x !== ev);
    selected = null;
    render();
    emit();
  }

  function renderProps() {
    props.replaceChildren();
    const ev = spec.events.find((x) => x._id === selected);
    if (!ev) {
      props.append(el('p', { class: 'n', text: spec.events.length
        ? 'Select an event to set its time and details. Arrow keys move a selected event; Delete removes it.'
        : 'No events yet. Drag one from the palette onto its lane.' }));
      return;
    }
    const time = el('input', { type: 'time', id: 'ed-ev-time', step: '1', value: toClock(ev.t) });
    time.addEventListener('change', () => { ev.t = snap(fromClock(time.value)); render(); emit(); });
    const del = el('button', { type: 'button', class: 'ghost danger', text: 'Delete event' });
    del.addEventListener('click', () => remove(ev));
    const ctl = controls(meta.event_types[ev.type].schema, ev, (k, v) => { ev[k] = v; renderEvents(); emit(); },
                         { prefix: `ed-ev-${ev._id}`, help: false });
    props.append(el('div', { class: 'ed-props-head' },
      el('span', { class: `chip static ev-${ev.type}` }, el('i'), meta.event_types[ev.type].label),
      el('label', { class: 'field-inline', for: 'ed-ev-time' }, el('span', { text: 'Starts at' }), time),
      el('span', { class: 'grow' }), del), ctl.el);
  }

  function renderHeader() {
    name.value = spec.label;
    price.value = spec.price;
    flat.value = spec.flat_price;
    flatWrap.hidden = spec.price !== 'flat';
    from.value = toClock(spec.window[0], false);
    to.value = spec.window[1] >= 24 ? '23:59' : toClock(spec.window[1], false);
    step.value = String(spec.dt_s);
  }

  function render() {
    renderHeader();
    renderAxis();
    renderEvents();
    renderProps();
    validate();
  }

  // header inputs
  name.addEventListener('change', () => { spec.label = name.value.trim() || 'Custom scenario'; emit(); });
  price.addEventListener('change', () => { spec.price = price.value; flatWrap.hidden = spec.price !== 'flat'; emit(); });
  flat.addEventListener('change', () => { spec.flat_price = Number(flat.value) || 0; emit(); });
  const setWindow = () => {
    let a = fromClock(from.value), b = fromClock(to.value);
    if (to.value === '23:59') b = 24;
    if (!(b > a)) { from.value = toClock(spec.window[0], false); to.value = toClock(spec.window[1], false); return; }
    spec.window = [a, b];
    // keep the step if it fits, otherwise the finest one that does
    const fits = (s) => Math.round(((b - a) * 3600) / s) <= meta.max_steps;
    if (!fits(spec.dt_s)) spec.dt_s = meta.dt_choices.find(fits) ?? meta.dt_choices.at(-1);
    render();
    emit();
  };
  from.addEventListener('change', setWindow);
  to.addEventListener('change', setWindow);
  step.addEventListener('change', () => { spec.dt_s = Number(step.value); validate(); emit(); });

  return {
    load(s, { preset = true } = {}) {
      spec = { ...s, window: [...s.window], events: s.events.map((e) => ({ ...e, _id: ++uid })) };
      fromPreset = preset ? s.label : null;
      selected = null;
      render();
    },
    setCursor(h) {
      if (!spec || h == null) return;
      cursor.style.left = `calc(var(--lane-label) + (100% - var(--lane-label)) * ${pct(h) / 100})`;
    },
    get spec() { return clean(); },
  };
}
