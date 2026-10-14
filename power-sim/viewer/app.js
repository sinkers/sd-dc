// The viewer. Fetches a simulation's description (model, schemas, scenarios),
// builds the page from it, and re-runs the day on the service whenever a
// setting changes. Playback is local: the whole day is already here, so the
// clock only moves a cursor through it.

import { chart } from './ui/chart.js';
import { controls, resolve } from './ui/controls.js';
import { fix, minutes, money, price, symlog } from './ui/format.js';
import { oneline } from './ui/oneline.js';
import { card } from './views/card.js';

const $ = (sel) => document.querySelector(sel);
const API = 'api';

const state = { desc: null, scenario: null, params: {}, result: null, i: 0, playing: false, speed: 3, logPrice: true };
const ui = { cards: {}, charts: [], sld: null, dispatch: null, ctrlId: null, voltage: null, power: null };

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
      const result = await getJSON(`${API}/sims/${state.desc.id}/run`, { scenario: state.scenario.id, params: state.params });
      if (ticket !== pending) return;
      state.result = result;
      state.i = Math.min(state.i, result.rows.length - 1);
      $('#scrub').max = result.rows.length - 1;
      renderDay();
      renderAt(state.i);
      status(`Solved ${result.rows.length} steps of ${result.scenario.dt_min < 1 ? `${Math.round(result.scenario.dt_min * 60)} s` : `${result.scenario.dt_min} min`} in ${Math.round(performance.now() - t0)} ms. Price data: ${result.price.name}.`);
    } catch (e) {
      status(`Could not run the simulation: ${e.message}`, true);
    }
  }, delay);
}

function onParam(id, key, value) {
  state.params[id][key] = value;
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

function selectScenario(id) {
  state.scenario = state.desc.scenarios.find((s) => s.id === id) ?? state.desc.scenarios[0];
  state.params = paramsFor(state.scenario);
  for (const [aid, c] of Object.entries(ui.cards)) c.set(state.params[aid]);
  ui.dispatch?.set(state.params[ui.ctrlId]);
  renderDispatchNote();
  applyStartView(state.scenario);
  play(false);
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
  const logPrice = state.logPrice && c.priceMax - c.priceMin > 600;
  $('#price-scale').textContent = logPrice ? 'Price scale: log' : 'Price scale: linear';
  ui.charts[0].update(r.rows, { refs, bands, scale: logPrice ? symlog : null });
  for (const ch of ui.charts.slice(1)) ch.update(r.rows, { bands, refs: ch === ui.power ? powerRefs : [] });
}

function renderAt(i) {
  const r = state.result;
  if (!r) return;
  state.i = i;
  const row = r.rows[i];
  $('#clock').textContent = row.clock;
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
  for (const [id, cd] of Object.entries(ui.cards)) cd.update(row.assets[id], c);
  ui.sld.update(row);
  for (const ch of ui.charts) ch.cursor(i);
}

// ── playback ────────────────────────────────────────────────────────────

let last = 0, acc = 0;
function tick(ts) {
  if (!state.playing || !state.result) return;
  const rows = state.result.rows;
  const dtH = rows[1].t - rows[0].t;
  if (last) acc += ((ts - last) / 1000) * state.speed;  // sim-hours elapsed
  last = ts;
  const steps = Math.floor(acc / dtH);
  if (steps > 0) {
    acc -= steps * dtH;
    renderAt((state.i + steps) % rows.length);
  }
  requestAnimationFrame(tick);
}
function play(on) {
  state.playing = on;
  $('#play').textContent = on ? 'Pause' : 'Play';
  $('#play').setAttribute('aria-pressed', on);
  last = 0; acc = 0;
  if (on) requestAnimationFrame(tick);
}

// ── build ───────────────────────────────────────────────────────────────

function buildCharts() {
  const host = $('#charts');
  const cursor = (i) => { play(false); renderAt(i); };
  const A = (id) => (r) => r.assets[id];
  const bess = A('BESS-1'), ups = A('UPS-1'), gpu = A('GPU-1'), grid = A('UTIL');
  const kwf = (v) => fix(v, 0);
  ui.voltage = chart({ title: 'Grid voltage', unit: '%', height: 120, yMin: 0, yMax: 110, fmt: (v) => fix(v, 0),
    onCursor: cursor, series: [{ label: 'lowest in step', cls: 'c-alarm', kind: 'step', get: (r) => r.v_pct, width: 2 }] });
  ui.power = chart({ title: 'Power', unit: 'kW', height: 210, fmt: kwf, onCursor: cursor, series: [
      { label: 'BESS discharging', cls: 'c-discharge', kind: 'area', get: (r) => Math.max(0, bess(r).ac_kw) },
      { label: 'BESS charging', cls: 'c-charge', kind: 'area', get: (r) => Math.min(0, bess(r).ac_kw) },
      { label: 'GPU load', cls: 'c-load', get: (r) => gpu(r).kw },
      { label: 'UPS input', cls: 'c-ups', get: (r) => ups(r).input_kw, dash: '4 3' },
      { label: 'generator', cls: 'c-gen', get: (r) => r.assets['GEN-1']?.kw ?? 0, width: 2 },
      { label: 'grid import', cls: 'c-grid', get: (r) => grid(r).import_kw - grid(r).export_kw, width: 2.25 },
    ] });
  ui.charts = [
    chart({ title: 'Spot price', unit: '$/MWh', height: 170, fmt: (v) => price(v), onCursor: cursor,
            series: [{ label: 'price', cls: 'c-price', kind: 'step', get: (r) => r.price, width: 2 }] }),
    ui.voltage,
    ui.power,
    chart({ title: 'State of charge', unit: '%', height: 150, yMin: 0, yMax: 100, fmt: (v) => fix(v, 0), onCursor: cursor, series: [
      { label: 'BESS', cls: 'c-charge', get: (r) => bess(r).soc_pct, width: 2.25 },
      { label: 'UPS battery', cls: 'c-ups', get: (r) => ups(r).battery_soc_pct, dash: '4 3' },
    ] }),
    chart({ title: 'Saving so far', unit: '$', height: 150, fmt: (v) => money(v), onCursor: cursor, series: [
      { label: 'net saving against no BESS', cls: 'c-ok', get: (r) => r.saving, width: 2.25 },
    ] }),
  ];
  host.replaceChildren(...ui.charts.map((c) => c.el));
}

async function main() {
  const qs = new URLSearchParams(location.search);
  const sims = await getJSON(`${API}/sims`);
  const simId = qs.get('sim') ?? sims[0].id;
  state.desc = await getJSON(`${API}/sims/${simId}`);
  document.title = state.desc.title;
  $('#title').textContent = state.desc.title;
  $('#subtitle').textContent = state.desc.description;

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
  let saved = null;
  try { saved = localStorage.getItem('power-sim:scenario'); } catch { /* ignore */ }
  const first = state.desc.scenarios.find((s) => s.id === (qs.get('scenario') ?? saved)) ?? state.desc.scenarios[0];
  sel.value = first.id;
  sel.addEventListener('change', () => selectScenario(sel.value));

  state.scenario = first;
  state.params = paramsFor(first);

  ui.sld = oneline($('#sld'), state.desc, {
    onSelect: (id) => {
      const el = document.getElementById(`asset-${id}`);
      if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.querySelector('input,select')?.focus({ preventScroll: true }); }
    },
  });

  const host = $('#cards');
  for (const [id, meta] of Object.entries(state.desc.assets)) {
    if (meta.role === 'bus') continue;
    const c = card(id, meta, state.params[id], (key, value) => onParam(id, key, value));
    ui.cards[id] = c;
    host.append(c.el);
  }
  ui.ctrlId = Object.entries(state.desc.assets).find(([, m]) => m.role === 'controller')?.[0];
  if (ui.ctrlId) {
    ui.dispatch = controls(state.desc.assets[ui.ctrlId].schema, state.params[ui.ctrlId],
      (key, value) => onParam(ui.ctrlId, key, value), { prefix: 'dispatch', only: ['charge_below', 'discharge_above'], help: false });
    $('#dispatch-controls').append(ui.dispatch.el);
    renderDispatchNote();
  }
  buildCharts();
  $('#model').textContent = JSON.stringify(state.desc.model, null, 1);

  $('#play').addEventListener('click', () => play(!state.playing));
  $('#speed').addEventListener('change', (e) => { state.speed = Number(e.target.value); });
  $('#scrub').addEventListener('input', (e) => { play(false); renderAt(Number(e.target.value)); });
  $('#price-scale').addEventListener('click', () => { state.logPrice = !state.logPrice; renderDay(); renderAt(state.i); });
  $('#reset').addEventListener('click', () => selectScenario(state.scenario.id));
  $('#copy-model').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('#model').textContent); $('#copy-model').textContent = 'Copied'; }
    catch { getSelection().selectAllChildren($('#model')); $('#copy-model').textContent = 'Selected, press Ctrl+C'; }
    setTimeout(() => { $('#copy-model').textContent = 'Copy JSON'; }, 1800);
  });
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input,select,textarea')) return;
    if (e.key === ' ') { e.preventDefault(); play(!state.playing); }
    if (e.key === 'ArrowRight') renderAt(Math.min(state.result.rows.length - 1, state.i + 1));
    if (e.key === 'ArrowLeft') renderAt(Math.max(0, state.i - 1));
  });

  $('#scenario-note').textContent = first.description;
  applyStartView(first);
  rerun(0);
}

main().catch((e) => status(`Could not reach the simulation service: ${e.message}. Start it with ./serve.sh`, true));
