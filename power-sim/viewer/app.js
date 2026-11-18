// The viewer. Fetches a simulation's description (model, schemas, scenarios),
// builds the page from it, and re-runs the day on the service whenever a
// setting changes. Playback is local: the whole day is already here, so the
// clock only moves a cursor through it.

import { chart } from './ui/chart.js';
import { controls, resolve } from './ui/controls.js';
import { fix, minutes, money, price, symlog } from './ui/format.js';
import { oneline } from './ui/oneline.js';
import { readout, settings } from './views/card.js';
import { editor } from './views/editor.js';
import { download, exportHtml, report } from './views/report.js';

const $ = (sel) => document.querySelector(sel);
const API = 'api';

const state = { desc: null, scenario: null, params: {}, result: null, i: 0, playing: false, speed: 3, logPrice: true, custom: null };
const ui = { cards: {}, readouts: {}, charts: [], priceChart: null, sld: null, dispatch: null, ctrlId: null, voltage: null, power: null, editor: null, report: null };

async function getJSON(url, body) {
  const res = await fetch(url, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function status(msg, err = false) {
  const el = $('#status');
  el.textContent = msg;
  el.classList.toggle('err', err);
}

// ── parameters ──────────────────────────────────────────────────────────

function paramsFor(scenario) {
  const out = {};
  for (const [id, meta] of Object.entries(state.desc.assets)) out[id] = resolve(meta.schema, scenario.params?.[id] ?? {});
  return out;
}

let pending = 0, timer = null;
function rerun(delay = 140) {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    const ticket = ++pending;
    status('Running…');
    try {
      const t0 = performance.now();
      const body = state.custom
        ? { scenario: 'custom', custom: state.custom, params: state.params }
        : { scenario: state.scenario.id, params: state.params };
      const result = await getJSON(`${API}/sims/${state.desc.id}/run`, body);
      if (ticket !== pending) return;
      state.result = result;
      state.i = Math.min(state.i, result.rows.length - 1);
      fitSpeed(result);
      $('#scrub').max = result.rows.length - 1;
      renderDay();
      renderAt(state.i);
      $('#current-scenario').textContent = result.scenario.label;
      status(`Solved ${result.rows.length} steps of ${result.scenario.dt_min < 1 ? `${Math.round(result.scenario.dt_min * 60)} s` : `${result.scenario.dt_min} min`} in ${Math.round(performance.now() - t0)} ms. Price data: ${result.price.name}.`);
    } catch (e) {
      status(`Could not run the simulation: ${e.message}`, true);
    }
  }, delay);
}

function onParam(id, key, value) {
  state.params[id][key] = value;
  if (state.custom) {
    try { localStorage.setItem('power-sim:custom', JSON.stringify({ spec: state.custom, params: state.params })); } catch { /* ignore */ }
  }
  if (id === ui.ctrlId) {
    ui.dispatch?.set(state.params[id]);
    ui.cards[id]?.set(state.params[id]);
    renderDispatchNote();
  }
  rerun();
}

function renderDispatchNote() {
  const dr = state.params[ui.ctrlId];
  const note = $('#dispatch-note');
  if (!dr) return;
  if (dr.strategy === 'optimal') {
    note.textContent = 'The DR controller is on the optimal strategy, which ignores these prices. Set its strategy to price thresholds to use them.';
    note.className = 'note warn';
  } else if (dr.charge_below >= dr.discharge_above) {
    note.textContent = 'The recharge price is at or above the discharge price, so the BESS will discharge whenever it can.';
    note.className = 'note warn';
  } else {
    note.textContent = `The BESS recharges at or below ${price(dr.charge_below)}/MWh, discharges at or above ${price(dr.discharge_above)}/MWh, and holds in between. It keeps ${fix(dr.reserve_pct, 0)} % in reserve.`;
    note.className = 'note';
  }
}

// A day opens on the afternoon; a disturbance window opens just before the first
// event, at a speed slow enough to watch the resync.
function startView(sc) {
  const first = Math.min(...(sc.sags ?? []).map((x) => x.t), ...(sc.outages ?? []).map((o) => o[0]));
  const dtH = sc.dt_min / 60;
  if (Number.isFinite(first) && sc.hours < 24) {
    return { i: Math.max(0, Math.round((first - sc.start_h) / dtH) - Math.round(10 / 3600 / dtH)), speed: 10 / 3600 };
  }
  return { i: Math.round((14.5 - sc.start_h) / dtH), speed: 3 };
}

function applyStartView(sc) {
  const v = startView(sc);
  state.i = v.i;
  state.speed = v.speed;
  const sp = $('#speed');
  const best = [...sp.options].reduce((b, o) => (Math.abs(Number(o.value) - v.speed) < Math.abs(Number(b.value) - v.speed) ? o : b));
  sp.value = best.value;
}

// The editor reports a changed timeline: the run becomes a custom scenario,
// keeping whatever equipment settings are in force.
function onEdit(spec) {
  state.custom = spec;
  $('#scenario').value = 'custom';
  $('#scenario-note').textContent = `${spec.label}. Built in the scenario timeline below; ` +
    'equipment settings carry over from the scenario it started from.';
  try {
    localStorage.setItem('power-sim:custom', JSON.stringify({ spec, params: state.params }));
    localStorage.setItem('power-sim:scenario', 'custom');
  }
  catch { /* storage may be blocked */ }
  rerun();
}

// ── tabs ────────────────────────────────────────────────────────────────

const TABS = ['scenarios', 'config', 'sim', 'reports'];
function setTab(name) {
  if (!TABS.includes(name)) name = 'sim';
  for (const t of TABS) {
    const on = t === name;
    document.getElementById(`tab-${t}`).hidden = !on;
    const b = document.getElementById(`tab-btn-${t}`);
    b.setAttribute('aria-selected', on);
    b.tabIndex = on ? 0 : -1;
  }
  try { localStorage.setItem('power-sim:tab', name); } catch { /* ignore */ }
  if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
}

function selectScenario(id) {
  if (id === 'custom') {
    if (!state.custom) state.custom = ui.editor.spec;
    onEdit(state.custom);
    return;
  }
  state.custom = null;
  state.scenario = state.desc.scenarios.find((s) => s.id === id) ?? state.desc.scenarios[0];
  ui.editor?.load(state.scenario.editor);
  state.params = paramsFor(state.scenario);
  for (const [aid, c] of Object.entries(ui.cards)) c.set(state.params[aid]);
  ui.dispatch?.set(state.params[ui.ctrlId]);
  renderDispatchNote();
  applyStartView(state.scenario);
  $('#scenario-note').textContent = state.scenario.description;
  try { localStorage.setItem('power-sim:scenario', state.scenario.id); } catch { /* storage may be blocked */ }
  rerun(0);
}

// ── rendering ───────────────────────────────────────────────────────────

function ctx() {
  const r = state.result;
  const dr = state.params['DR-1'] ?? {};
  const series = r?.price.series ?? [0];
  return {
    priceMin: Math.min(...series), priceMax: Math.max(...series),
    chargeBelow: dr.strategy === 'threshold' ? dr.charge_below : -Infinity,
    dischargeAbove: dr.strategy === 'threshold' ? dr.discharge_above : Infinity,
  };
}

function renderDay() {
  const r = state.result;
  const s = r.summary;
  const sign = (v) => (v > 0.005 ? 'pos' : v < -0.005 ? 'neg' : '');
  $('#sum-saving').textContent = money(s.saving, { sign: true });
  $('#sum-saving').className = `v ${sign(s.saving)}`;
  $('#sum-saving-note').textContent =
    `Bill ${money(s.bill_saving, { sign: true })}, wear ${money(-s.wear_cost, { sign: true })}, ` +
    `stored energy ${money(s.stored_energy_value, { sign: true })} (SoC ${fix(s.soc_start_pct, 0)} → ${fix(s.soc_end_pct, 0)} %, valued at the ${price(s.median_price)}/MWh median).`;
  $('#sum-bess').textContent = money(s.saving_bess, { sign: true });
  $('#sum-cap').textContent = money(s.saving_cap, { sign: true });
  $('#sum-cap-note').textContent = s.gpu_work_lost_server_h > 0.05 ? `costs ${fix(s.gpu_work_lost_server_h, 1)} server-hours of compute` : 'cap not triggered';
  $('#sum-gen').textContent = s.gen_enabled ? money(s.saving_gen, { sign: true }) : 'Off';
  $('#sum-gen-note').textContent = !s.gen_enabled ? 'not fitted in this scenario'
    : s.gen_trips ? `tripped on overload; ${fix(s.gen_kwh, 0)} kWh before it did`
    : s.gen_kwh > 0.05 ? `${fix(s.gen_kwh, 0)} kWh over ${minutes(s.gen_run_h * 60)}, fuel ${money(s.gen_fuel_cost)} (${price(s.gen_cost_per_mwh)}/MWh)`
    : 'did not run';
  $('#sum-gen').className = `v ${s.gen_trips ? 'neg' : ''}`;
  $('#sum-base').textContent = money(s.baseline_cost);
  $('#sum-cost').textContent = money(s.cost);
  $('#sum-spread').textContent = s.mean_charge_price == null ? '–' : `${price(s.mean_charge_price)} → ${price(s.mean_discharge_price ?? 0)}`;
  $('#sum-cycles').innerHTML = `${fix(s.bess_cycles, 2)}<small>cycles, ${fix(s.bess_discharged_kwh, 0)} kWh out</small>`;
  const risk = s.unserved_kwh > 0 ? `${fix(s.unserved_kwh, 1)} kWh unserved` : s.over_capacity_steps ? `${s.over_capacity_steps} steps over capacity` : 'None';
  $('#sum-risk').textContent = risk;
  $('#sum-risk').className = `v ${s.unserved_kwh > 0 || s.over_capacity_steps ? 'neg' : ''}`;
  $('#sum-saving-label').textContent = r.scenario.hours < 24 ? 'Net saved in this window' : 'Net saved today';

  if (!s.disturbances) {
    $('#sum-rt').textContent = 'No events';
    $('#sum-rt').className = 'v';
    $('#sum-rt-note').textContent = 'pick a grid disturbance scenario';
  } else {
    $('#sum-rt').innerHTML = s.ups_transfers
      ? `${fix(s.ups_on_battery_s, 0)} s<small>UPS on battery</small>` : 'Rode through<small>UPS stayed on grid</small>';
    $('#sum-rt').className = `v ${s.ups_transfers ? 'neg' : 'pos'}`;
    const limit = s.ups_max_demand_kw ? ` (max ${fix(s.ups_max_demand_kw, 0)})` : '';
    const site = s.site_max_demand_kw ? `, site peak ${fix(s.peak_import_kw, 0)} kW (max ${fix(s.site_max_demand_kw, 0)})` : `, site peak ${fix(s.peak_import_kw, 0)} kW`;
    $('#sum-rt-note').textContent =
      `UPS battery low point ${fix(s.ups_min_soc_pct, 0)} %, UPS input peak ${fix(s.ups_peak_input_kw, 0)} kW${limit}${site}, ` +
      `BESS ${s.bess_trips ? `tripped ${s.bess_trips}×` : 'stayed connected'}.`;
  }

  const c = ctx();
  const dr = state.params['DR-1'];
  const refs = dr.strategy === 'threshold' ? [
    { value: dr.charge_below, label: `charge ≤ ${price(dr.charge_below)}`, cls: 'c-charge', below: true },
    { value: dr.discharge_above, label: `discharge ≥ ${price(dr.discharge_above)}`, cls: 'c-discharge' },
  ] : [];
  const bands = [
    ...(r.scenario.outages ?? []).map(([from, to]) => ({ from, to })),
    ...(r.scenario.sags ?? []).map((x) => ({ from: x.t, to: x.t + x.duration_ms / 3.6e6, cls: 'sag' })),
  ];
  const ups = state.params['UPS-1'] ?? {};
  const powerRefs = [];
  if (ups.max_demand_enabled) powerRefs.push({ value: ups.max_demand_kw, label: `UPS max demand ${fix(ups.max_demand_kw, 0)} kW`, cls: 'c-ups' });
  if (dr.peak_shave) powerRefs.push({ value: dr.site_max_demand_kw, label: `site max demand ${fix(dr.site_max_demand_kw, 0)} kW`, cls: 'c-grid', below: true });
  ui.voltage.show(r.summary.disturbances > 0);
  ui.rptVoltage.show(true);     // the report carries the voltage record whether or not anything happened
  const capBands = (r.plant?.capping ?? []).flatMap((c) => c.periods.map((p) => ({ from: p.start, to: p.end })));
  const logPrice = state.logPrice && c.priceMax - c.priceMin > 600;
  $('#price-scale').textContent = logPrice ? 'Price scale: log' : 'Price scale: linear';
  ui.priceChart.update(r.rows, { refs, bands, scale: logPrice ? symlog : null });
  for (const ch of ui.charts) {
    if (ch === ui.priceChart) continue;
    const isPower = ch === ui.power || ch === ui.rptPower;
    const isCap = ch === ui.capChart || ch === ui.tputChart;
    ch.update(r.rows, { bands: isCap ? capBands : bands, refs: isPower ? powerRefs : [] });
  }
  ui.report.update(r, state.desc, state.params);
}

function renderAt(i) {
  const r = state.result;
  if (!r) return;
  state.i = i;
  const row = r.rows[i];
  $('#clock').textContent = row.clock;
  ui.editor?.setCursor(row.t);
  $('#price-now').textContent = `${price(row.price)}/MWh`;
  const dr = state.params[ui.ctrlId] ?? {};
  let zone = ['Hold', ''];
  if (dr.strategy === 'threshold') {
    if (row.price >= dr.discharge_above) zone = ['Discharge zone', 'discharge'];
    else if (row.price <= dr.charge_below) zone = ['Recharge zone', 'charge'];
  } else {
    const d = row.assets[ui.ctrlId]?.decision;
    zone = d === 'discharge' ? ['Discharging', 'discharge'] : d === 'charge' ? ['Recharging', 'charge'] : ['Hold', ''];
  }
  if (!row.grid_up) zone = ['Grid outage', 'alarm'];
  else if (row.v_pct < 90) zone = [`Voltage sag to ${Math.round(row.v_pct)} %`, 'alarm'];
  $('#price-zone').textContent = zone[0];
  $('#price-zone').className = `pill zone ${zone[1]}`;
  $('#price-source').textContent = `${r.price.name} · ${r.price.source === 'synthetic' ? 'synthetic tariff' : 'AEMO spot (RRP)'}`;
  $('#scrub').value = i;
  $('#sum-saving-now').textContent = `${money(row.saving, { sign: true })} by ${row.clock}`;
  const c = ctx();
  for (const [id, cd] of Object.entries(ui.readouts)) cd.update(row.assets[id], c);
  const g = row.assets.UTIL;
  if (g) {
    const state = !g.up ? ['Outage', 'neg'] : g.v_pct < 90 ? [`Sag to ${Math.round(g.v_pct)} %`, 'neg'] : ['Normal', ''];
    $('#grid-now').textContent = state[0];
    $('#grid-now').className = `v ${state[1]}`;
    $('#grid-now-note').textContent = g.up ? `importing ${fix(g.import_kw - g.export_kw, 0)} kW at ${row.clock}` : `at ${row.clock}`;
  }
  ui.sld.update(row);
  for (const ch of ui.charts) ch.cursor(i);
}

// ── playback ────────────────────────────────────────────────────────────

// One playback loop at a time: each Play starts a new loop id, and an older
// loop that wakes up after a pause and replay sees it is stale and stops.
let last = 0, acc = 0, loop = 0;
function tick(ts, id) {
  if (id !== loop || !state.playing || !state.result) return;
  const rows = state.result.rows;
  const dtH = rows.length > 1 ? rows[1].t - rows[0].t : 1;
  if (last) acc += ((ts - last) / 1000) * state.speed;  // sim-hours elapsed
  last = ts;
  const steps = Math.floor(acc / dtH);
  if (steps > 0) {
    acc -= steps * dtH;
    const next = state.i + steps;
    // Stop at the end of the run rather than lapping it: a lap at a fast
    // speed looks like the playhead jumping back and forth.
    if (next >= rows.length - 1) { renderAt(rows.length - 1); play(false); return; }
    renderAt(next);
  }
  requestAnimationFrame((t) => tick(t, id));
}
function play(on) {
  state.playing = on;
  $('#play').textContent = on ? 'Pause' : 'Play';
  $('#play').setAttribute('aria-pressed', on);
  last = 0; acc = 0;
  const id = ++loop;
  if (!on) return;
  if (state.result && state.i >= state.result.rows.length - 1) renderAt(0);   // replay from the start
  requestAnimationFrame((t) => tick(t, id));
}

// Keep a run watchable: at most a speed that plays the whole run in about
// eight seconds. Without this a 45-minute window at 3 h/s laps four times a second.
function fitSpeed(result) {
  const hours = result.scenario.hours;
  const cap = hours / 8;
  if (state.speed <= cap) return;
  const opts = [...$('#speed').options].map((o) => Number(o.value)).sort((x, y) => x - y);
  const pick = opts.filter((v) => v <= cap).pop() ?? opts[0];
  state.speed = pick;
  $('#speed').value = [...$('#speed').options].find((o) => Number(o.value) === pick).value;
}

// ── build ───────────────────────────────────────────────────────────────

// Chart builders. The plant charts appear twice: on Simulation, to watch, and
// on Reports, so the report (and its print and export) carries the data.
function plantCharts(cursor) {
  const A = (id) => (r) => r.assets[id];
  const bess = A('BESS-1'), ups = A('UPS-1'), gpu = A('GPU-1'), grid = A('UTIL');
  const kwf = (v) => fix(v, 0);
  const voltage = chart({ title: 'Grid voltage', unit: '%', height: 120, yMin: 0, yMax: 110, fmt: (v) => fix(v, 0),
    onCursor: cursor, series: [{ label: 'lowest in step', cls: 'c-alarm', kind: 'step', get: (r) => r.v_pct, width: 2 }] });
  const power = chart({ title: 'Power', unit: 'kW', height: 210, fmt: kwf, onCursor: cursor, series: [
      { label: 'BESS discharging', cls: 'c-discharge', kind: 'area', get: (r) => Math.max(0, bess(r).ac_kw) },
      { label: 'BESS charging', cls: 'c-charge', kind: 'area', get: (r) => Math.min(0, bess(r).ac_kw) },
      { label: 'GPU load', cls: 'c-load', get: (r) => gpu(r).kw },
      { label: 'UPS input', cls: 'c-ups', get: (r) => ups(r).input_kw, dash: '4 3' },
      { label: 'generator', cls: 'c-gen', get: (r) => r.assets['GEN-1']?.kw ?? 0, width: 2 },
      { label: 'grid import', cls: 'c-grid', get: (r) => grid(r).import_kw - grid(r).export_kw, width: 2.25 },
    ] });
  const soc = chart({ title: 'State of charge', unit: '%', height: 170, yMin: 0, yMax: 100, fmt: (v) => fix(v, 0), onCursor: cursor, series: [
      { label: 'BESS', cls: 'c-charge', get: (r) => bess(r).soc_pct, width: 2.25 },
      { label: 'UPS battery', cls: 'c-ups', get: (r) => ups(r).battery_soc_pct, dash: '4 3' },
    ] });
  return { voltage, power, soc };
}

function buildCharts() {
  const cursor = (i) => { play(false); renderAt(i); };
  const sim = plantCharts(cursor);
  ui.voltage = sim.voltage;
  ui.power = sim.power;
  $('#charts').replaceChildren(sim.voltage.el, sim.power.el, sim.soc.el);

  const rpt = plantCharts(cursor);
  ui.rptVoltage = rpt.voltage;
  ui.rptPower = rpt.power;
  const gpu = (r) => r.assets['GPU-1'];
  ui.capChart = chart({ title: 'GPU load and power cap', unit: 'kW', height: 170, fmt: (v) => fix(v, 0), onCursor: cursor, series: [
      { label: 'cut by the cap', cls: 'c-discharge', kind: 'area', get: (r) => gpu(r).uncapped_kw - gpu(r).kw },
      { label: 'demand before cap', cls: 'c-ups', get: (r) => gpu(r).uncapped_kw, dash: '4 3' },
      { label: 'GPU load', cls: 'c-load', get: (r) => gpu(r).kw, width: 2.25 },
    ] });
  ui.tputChart = chart({ title: 'Compute throughput', unit: '%', height: 120, yMin: 0, yMax: 105, fmt: (v) => fix(v, 0), onCursor: cursor, series: [
      { label: 'throughput', cls: 'c-ok', kind: 'step', get: (r) => gpu(r).throughput_pct, width: 2 },
    ] });
  $('#plant-charts').replaceChildren(rpt.voltage.el, rpt.power.el, rpt.soc.el, ui.capChart.el, ui.tputChart.el);

  ui.priceChart = chart({ title: 'Spot price', unit: '$/MWh', height: 190, fmt: (v) => price(v), onCursor: cursor,
            series: [{ label: 'price', cls: 'c-price', kind: 'step', get: (r) => r.price, width: 2 }] });
  const saving = chart({ title: 'Saving so far', unit: '$', height: 170, fmt: (v) => money(v), onCursor: cursor, series: [
      { label: 'net saving against no BESS', cls: 'c-ok', get: (r) => r.saving, width: 2.25 },
    ] });
  $('#price-charts').replaceChildren(ui.priceChart.el, saving.el);
  ui.charts = [sim.voltage, sim.power, sim.soc, rpt.voltage, rpt.power, rpt.soc, ui.capChart, ui.tputChart, ui.priceChart, saving];
}

async function main() {
  const qs = new URLSearchParams(location.search);
  const sims = await getJSON(`${API}/sims`);
  const simId = qs.get('sim') ?? sims[0].id;
  state.desc = await getJSON(`${API}/sims/${simId}`);
  document.title = state.desc.title;
  $('#title').textContent = state.desc.title;
  document.querySelector('#title').title = state.desc.description;

  const sel = $('#scenario');
  const groups = { day: 'Price days', dist: 'Grid disturbances' };
  for (const [key, label] of Object.entries(groups)) {
    const g = document.createElement('optgroup');
    g.label = label;
    for (const sc of state.desc.scenarios) {
      const isDist = (sc.sags?.length || sc.outages?.length) && sc.hours < 24;
      if ((key === 'dist') === Boolean(isDist)) g.append(new Option(sc.label, sc.id));
    }
    sel.append(g);
  }
  const cg = document.createElement('optgroup');
  cg.label = 'Your own';
  cg.append(new Option('Custom (scenario timeline)', 'custom'));
  sel.append(cg);
  let saved = null, savedCustom = null;
  try {
    saved = localStorage.getItem('power-sim:scenario');
    const c = JSON.parse(localStorage.getItem('power-sim:custom') || 'null');
    savedCustom = c?.spec ? c : null;      // older saves held the timeline alone; ignore them
  } catch { /* ignore */ }
  const first = state.desc.scenarios.find((s) => s.id === (qs.get('scenario') ?? saved)) ?? state.desc.scenarios[0];
  sel.value = saved === 'custom' && savedCustom ? 'custom' : first.id;
  sel.addEventListener('change', () => selectScenario(sel.value));

  state.scenario = first;
  state.params = paramsFor(first);
  if (sel.value === 'custom') {
    for (const [aid, v] of Object.entries(savedCustom.params ?? {})) if (state.params[aid]) Object.assign(state.params[aid], v);
  }

  ui.sld = oneline($('#sld'), state.desc, {
    onSelect: (id) => {
      const el = document.getElementById(`asset-${id}`);
      if (!el) return;
      setTab('config');
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      el.querySelector('input,select')?.focus({ preventScroll: true });
    },
  });

  for (const [id, meta] of Object.entries(state.desc.assets)) {
    if (meta.role === 'bus') continue;
    const s = settings(id, meta, state.params[id], (key, value) => onParam(id, key, value));
    ui.cards[id] = s;
    $('#settings').append(s.el);
    const r = readout(id, meta);
    if (!r.empty) { ui.readouts[id] = r; $('#readouts').append(r.el); }
  }
  ui.ctrlId = Object.entries(state.desc.assets).find(([, m]) => m.role === 'controller')?.[0];
  if (ui.ctrlId) {
    ui.dispatch = controls(state.desc.assets[ui.ctrlId].schema, state.params[ui.ctrlId],
      (key, value) => onParam(ui.ctrlId, key, value), { prefix: 'dispatch', only: ['charge_below', 'discharge_above'], help: false });
    $('#dispatch-controls').append(ui.dispatch.el);
    renderDispatchNote();
  }
  buildCharts();

  ui.editor = editor($('#editor'), state.desc, {
    onChange: onEdit,
    getCursorH: () => state.result?.rows[state.i]?.t ?? null,
  });
  ui.editor.load(first.editor);
  const jump = (i) => {
    play(false);
    renderAt(i);
    setTab('sim');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  ui.report = report($('#report'), { onJump: jump });
  const fname = (ext) => `${(ui.report.title || 'power-sim').replace(/[^\w.-]+/g, '-').slice(0, 60)}.${ext}`;
  $('#rpt-print').addEventListener('click', () => window.print());
  $('#rpt-html').addEventListener('click', async () => {
    const nodes = ['#summary', '#sim-status', '#sld-panel', '#plant-panel', '#price-charts-panel', '#report-panel'].map((q) => $(q));
    download(await exportHtml({ title: ui.report.title, nodes }), fname('html'));
  });
  $('#rpt-csv').addEventListener('click', () => download(new Blob([ui.report.csv()], { type: 'text/csv' }), fname('csv')));
  $('#rpt-series').addEventListener('click', () => download(new Blob([ui.report.series()], { type: 'text/csv' }), fname('series.csv')));
  $('#model').textContent = JSON.stringify(state.desc.model, null, 1);

  const tabs = [...document.querySelectorAll('[role=tab]')];
  for (const b of tabs) b.addEventListener('click', () => setTab(b.dataset.tab));
  document.querySelector('[role=tablist]').addEventListener('keydown', (e) => {
    const i = tabs.indexOf(document.activeElement);
    if (i < 0 || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    next.focus();
    setTab(next.dataset.tab);
  });
  let savedTab = null;
  try { savedTab = localStorage.getItem('power-sim:tab'); } catch { /* ignore */ }
  setTab(location.hash.slice(1) || savedTab || 'sim');
  window.addEventListener('hashchange', () => setTab(location.hash.slice(1)));

  $('#play').addEventListener('click', () => play(!state.playing));
  $('#speed').addEventListener('change', (e) => { state.speed = Number(e.target.value); });
  $('#scrub').addEventListener('input', (e) => { play(false); renderAt(Number(e.target.value)); });
  $('#price-scale').addEventListener('click', () => { state.logPrice = !state.logPrice; renderDay(); renderAt(state.i); });
  $('#reset').addEventListener('click', () => selectScenario(state.scenario.id));   // back to the preset the timeline started from
  $('#copy-model').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('#model').textContent); $('#copy-model').textContent = 'Copied'; }
    catch { getSelection().selectAllChildren($('#model')); $('#copy-model').textContent = 'Selected, press Ctrl+C'; }
    setTimeout(() => { $('#copy-model').textContent = 'Copy JSON'; }, 1800);
  });
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input,select,textarea,.ev,[role=tab]')) return;
    if (e.key === ' ') { e.preventDefault(); play(!state.playing); }
    if (e.key === 'ArrowRight') renderAt(Math.min(state.result.rows.length - 1, state.i + 1));
    if (e.key === 'ArrowLeft') renderAt(Math.max(0, state.i - 1));
  });

  $('#scenario-note').textContent = first.description;
  applyStartView(first);
  if (sel.value === 'custom') {
    ui.editor.load(savedCustom.spec, { preset: false });
    onEdit(savedCustom.spec);
    return;
  }
  rerun(0);
}

main().catch((e) => status(`Could not reach the simulation service: ${e.message}. Start it with ./serve.sh`, true));
