// The run report: what was done to the site, what happened and when, and what
// it cost. Shown at the foot of the page, printable (the browser's print to
// PDF), and exportable as a self-contained HTML file or the event log as CSV.

import { fix, minutes, money, price } from '../ui/format.js';

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

function table(head, rows, { cls = '', onRow = null } = {}) {
  const t = el('table', { class: `rpt ${cls}` });
  t.append(el('thead', {}, el('tr', {}, ...head.map((h) => el('th', { text: h })))));
  const tb = el('tbody');
  for (const r of rows) {
    const tr = el('tr', r.cls ? { class: r.cls } : {}, ...r.cells.map((c) => el('td', { text: c ?? '' })));
    if (onRow && r.i != null) {
      tr.tabIndex = 0;
      tr.title = 'Jump the playback to this moment';
      tr.addEventListener('click', () => onRow(r.i));
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') onRow(r.i); });
    }
    tb.append(tr);
  }
  t.append(tb);
  return t;
}

/** Settings that differ from each component's default, in words. */
function changedSettings(desc, params) {
  const out = [];
  for (const [aid, meta] of Object.entries(desc.assets)) {
    for (const f0 of meta.schema) {
      // the simulation's own default where it sets one (the generator is fitted but off)
      const f = { ...f0, default: desc.defaults?.[aid]?.[f0.key] ?? f0.default };
      const v = params[aid]?.[f.key];
      if (v == null || v === f.default) continue;
      const show = (x) => (f.kind === 'toggle' ? (x ? 'on' : 'off')
        : f.kind === 'select' ? (f.options.find((o) => o.value === x)?.label ?? x)
        : `${Number(x).toLocaleString('en-AU')}${f.unit ? ` ${f.unit}` : ''}`);
      out.push({ cells: [meta.name, f.label, show(v), show(f.default)] });
    }
  }
  return out;
}

function results(s) {
  const rows = [
    ['Net saving', money(s.saving, { sign: true })],
    ['  from the BESS', money(s.saving_bess, { sign: true })],
    ['  from the GPU power cap', money(s.saving_cap, { sign: true })],
    ['  from the generator', money(s.saving_gen, { sign: true })],
    ['Bill without BESS / with', `${money(s.baseline_cost)} / ${money(s.cost)}`],
    ['BESS energy out', `${fix(s.bess_discharged_kwh, 0)} kWh, ${fix(s.bess_cycles, 2)} cycles`],
    ['Peak grid import', `${fix(s.peak_import_kw, 0)} kW`],
    ['Unserved load', `${fix(s.unserved_kwh, 2)} kWh`],
  ];
  if (s.disturbances) {
    rows.push(['UPS time on battery', `${fix(s.ups_on_battery_s, 0)} s over ${s.ups_transfers} transfer${s.ups_transfers === 1 ? '' : 's'}`]);
    rows.push(['UPS battery low point', `${fix(s.ups_min_soc_pct, 0)} %`]);
    rows.push(['UPS input peak', `${fix(s.ups_peak_input_kw, 0)} kW${s.ups_max_demand_kw ? ` (max demand ${fix(s.ups_max_demand_kw, 0)})` : ''}`]);
    rows.push(['BESS trips', String(s.bess_trips)]);
  }
  if (s.gen_enabled) {
    rows.push(['Generator', `${fix(s.gen_kwh, 0)} kWh over ${minutes(s.gen_run_h * 60)}, fuel ${money(s.gen_fuel_cost)}, ${s.gen_starts} start${s.gen_starts === 1 ? '' : 's'}, ${s.gen_trips} trip${s.gen_trips === 1 ? '' : 's'}`]);
  }
  return rows.map(([a, b]) => ({ cells: [a, b] }));
}

const kwFmt = (v) => `${fix(v, Math.abs(v) >= 100 ? 0 : 1)}`;
const kwhFmt = (v) => (Math.abs(v) >= 1000 ? `${fix(v / 1000, 2)} MWh` : `${fix(v, 1)} kWh`);
const dur = (s) => (s >= 3600 ? `${fix(s / 3600, 1)} h` : s >= 120 ? `${fix(s / 60, 0)} min` : `${fix(s, s < 10 ? 2 : 0)} s`);

/** Voltage, power, state of charge and power capping: the plant's side of the run. */
function plantSections(p, rowsIndex, onJump) {
  if (!p) return [];
  const out = [];
  const v = p.voltage;
  if (v) {
    out.push(el('section', {}, el('h4', { text: 'Grid voltage' }), table(['', ''], [
      { cells: ['Lowest', `${fix(v.lowest_pct, 0)} % at ${v.lowest_at}`] },
      { cells: ['Mean while connected', `${fix(v.mean_pct, 1)} %`] },
      { cells: ['Sags below 90 %', v.sags ? `${v.sags}, ${dur(v.below_90_s)} in total` : 'none'] },
      { cells: ['Outages', v.outages.length ? `${v.outages.length}, ${dur(v.outage_s)} in total` : 'none'] },
      ...v.outages.map((o) => ({ cells: [`  outage`, `${o.clock_start} to ${o.clock_end}`], i: rowsIndex(o.start) })),
    ], { cls: 'kv', onRow: onJump })));
  }
  if (p.soc?.length) {
    out.push(el('section', {}, el('h4', { text: 'State of charge' }), table(['Battery', 'Start', 'End', 'Lowest', 'Highest'],
      p.soc.map((x) => ({ cells: [x.label, `${fix(x.start_pct, 0)} %`, `${fix(x.end_pct, 0)} %`,
                                   `${fix(x.lowest_pct, 0)} % at ${x.lowest_at}`, `${fix(x.highest_pct, 0)} %`] })))));
  }
  const cols = el('div', { class: 'rpt-cols' }, ...out);
  const blocks = [cols];

  if (p.power?.length) {
    blocks.push(el('h4', { text: `Power flows · ${p.steps.toLocaleString('en-AU')} steps of ${dur(p.step_s)}` }),
      table(['Flow', 'Peak kW', 'Peak at', 'Mean kW', 'Lowest kW', 'Energy'],
        p.power.map((f) => ({ cells: [f.label, kwFmt(f.peak_kw), f.peak_at ?? '', kwFmt(f.mean_kw), kwFmt(f.min_kw), kwhFmt(f.energy_kwh)] })),
        { cls: 'num' }));
  }

  for (const c of p.capping ?? []) {
    blocks.push(el('h4', { text: `Power capping · ${c.name}` }));
    if (!c.applied) {
      blocks.push(el('p', { class: 'n', text: 'No power cap was applied to the load in this run.' }));
      continue;
    }
    blocks.push(el('p', { class: 'n', text:
      `Capped for ${dur(c.capped_h * 3600)} over ${c.periods.length} period${c.periods.length === 1 ? '' : 's'}: ` +
      `${kwhFmt(c.curtailed_kwh)} curtailed, ${fix(c.work_lost_server_h, 1)} server-hours of compute lost, ` +
      `throughput down to ${fix(c.lowest_throughput_pct, 0)} % at worst.` }));
    blocks.push(table(['From', 'To', 'Load held to', 'Most cut', 'Lowest throughput', 'Mean price'],
      c.periods.map((x) => ({ cells: [x.clock_start, x.clock_end, `${kwFmt(x.capped_kw)} kW`, `${kwFmt(x.cut_peak_kw)} kW`,
                                      `${fix(x.lowest_throughput_pct, 0)} %`, `${price(x.mean_price)}/MWh`], i: rowsIndex(x.start) })),
      { cls: 'num', onRow: onJump }));
  }
  return blocks;
}

export function report(host, { onJump }) {
  const head = el('div', { class: 'rpt-head' });
  const body = el('div', { class: 'rpt-body' });
  const filter = el('div', { class: 'rpt-filter', role: 'group', 'aria-label': 'Show events' });
  const show = { alarm: true, warn: true, info: true };
  for (const [k, label] of [['alarm', 'Alarms'], ['warn', 'Warnings'], ['info', 'Information']]) {
    const id = `rpt-f-${k}`;
    const cb = el('input', { type: 'checkbox', id });
    cb.checked = true;
    cb.addEventListener('change', () => { show[k] = cb.checked; paint(); });
    filter.append(el('label', { for: id, class: `sev-${k}` }, cb, ` ${label}`));
  }
  host.append(head, body);
  let last = null;

  function paint() {
    if (!last) return;
    const { r, desc, params, rowsIndex } = last;
    const s = r.summary;
    const sc = r.scenario;
    head.replaceChildren(
      el('h3', { text: sc.label }),
      el('p', { class: 'n', text: `${r.price.name} · ${toWindow(sc)} · ${sc.dt_min < 1 ? `${Math.round(sc.dt_min * 60)} s` : `${sc.dt_min} min`} steps · generated ${new Date().toLocaleString('en-AU')}` }),
      el('p', { class: 'rpt-desc', text: sc.description }));

    const ev = r.log.events.filter((e) => show[e.severity]);
    body.replaceChildren(
      el('div', { class: 'rpt-cols' },
        el('section', {}, el('h4', { text: 'Results' }), table(['', ''], results(s), { cls: 'kv' })),
        el('section', {}, el('h4', { text: 'Injected events' }),
          r.injected.length
            ? table(['Time', 'Event'], r.injected.map((x) => ({ cells: [x.clock, x.event], i: rowsIndex(x.t) })), { onRow: onJump })
            : el('p', { class: 'n', text: 'None. This run is the price day as recorded.' }),
          el('h4', { text: 'Settings changed from default' }),
          (() => { const c = changedSettings(desc, params); return c.length
            ? table(['Equipment', 'Setting', 'Value', 'Default'], c) : el('p', { class: 'n', text: 'None.' }); })())),
      el('h3', { class: 'rpt-sub', text: 'Plant' }),
      ...plantSections(r.plant, rowsIndex, onJump),
      el('h4', {}, `Sequence of events `, el('span', { class: 'n', text: `${r.log.counts.alarm} alarms, ${r.log.counts.warn} warnings, ${r.log.counts.info} information${r.log.truncated ? ', first 400 shown' : ''}` })),
      filter,
      ev.length
        ? table(['Time', 'Equipment', 'Event', 'Detail'],
            ev.map((e) => ({ cls: `sev-${e.severity}`, cells: [e.clock, e.name, e.event, e.detail], i: rowsIndex(e.t) })),
            { cls: 'soe', onRow: onJump })
        : el('p', { class: 'n', text: 'No state changes in this run.' }));
  }

  function toWindow(sc) {
    const c = (h) => `${String(Math.floor(h)).padStart(2, '0')}:${String(Math.round((h % 1) * 60)).padStart(2, '0')}`;
    return sc.hours >= 24 ? 'whole day' : `${c(sc.start_h)} to ${c(sc.start_h + sc.hours)}`;
  }

  function csv() {
    const q = (v) => `"${String(v ?? '').replaceAll('"', '""')}"`;
    const lines = [['time', 'equipment', 'asset', 'severity', 'event', 'detail'].join(',')];
    for (const x of last.r.injected) lines.push([x.clock, 'Scenario', '', 'injected', x.event, ''].map(q).join(','));
    for (const e of last.r.log.events) lines.push([e.clock, e.name, e.asset, e.severity, e.event, e.detail].map(q).join(','));
    return lines.join('\n');
  }

  // Every step of the run, the plant side and the price, one row per step.
  function series() {
    const r = last.r;
    const cols = [
      ['time', (x) => x.clock], ['hours', (x) => x.t.toFixed(6)],
      ['grid_up', (x) => (x.grid_up ? 1 : 0)], ['grid_voltage_pct', (x) => x.v_pct],
      ['grid_import_kw', (x) => x.assets.UTIL.import_kw - x.assets.UTIL.export_kw],
      ['ups_input_kw', (x) => x.assets['UPS-1'].input_kw], ['ups_output_kw', (x) => x.assets['UPS-1'].output_kw],
      ['ups_loss_kw', (x) => x.assets['UPS-1'].loss_kw], ['ups_recharge_kw', (x) => x.assets['UPS-1'].recharge_kw],
      ['ups_status', (x) => x.assets['UPS-1'].status], ['ups_battery_soc_pct', (x) => x.assets['UPS-1'].battery_soc_pct],
      ['gpu_load_kw', (x) => x.assets['GPU-1'].kw], ['gpu_demand_before_cap_kw', (x) => x.assets['GPU-1'].uncapped_kw],
      ['gpu_power_capped', (x) => (x.assets['GPU-1'].capped ? 1 : 0)], ['gpu_throughput_pct', (x) => x.assets['GPU-1'].throughput_pct],
      ['bess_ac_kw', (x) => x.assets['BESS-1'].ac_kw], ['bess_status', (x) => x.assets['BESS-1'].status],
      ['bess_soc_pct', (x) => x.assets['BESS-1'].soc_pct],
      ['generator_kw', (x) => x.assets['GEN-1']?.kw ?? 0], ['generator_state', (x) => x.assets['GEN-1']?.state ?? ''],
      ['price_per_mwh', (x) => x.price], ['saving_so_far', (x) => x.saving],
    ];
    const q = (v) => (typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : `"${String(v ?? '').replaceAll('"', '""')}"`);
    const lines = [cols.map((c) => c[0]).join(',')];
    for (const x of r.rows) lines.push(cols.map((c) => q(c[1](x))).join(','));
    return lines.join('\n');
  }

  return {
    series,
    update(r, desc, params) {
      const t0 = r.rows[0].t, dt = r.rows.length > 1 ? r.rows[1].t - r.rows[0].t : 1;
      last = { r, desc, params, rowsIndex: (t) => Math.max(0, Math.min(r.rows.length - 1, Math.round((t - t0) / dt))) };
      paint();
    },
    csv,
    get title() { return last?.r.scenario.label ?? 'Power sim report'; },
  };
}

/** A standalone copy of the page's results: summary, diagram, trends, report. */
export async function exportHtml({ title, nodes }) {
  let css = '';
  try { css = await (await fetch('ui/theme.css')).text(); } catch { /* exported page falls back to browser styles */ }
  const parts = nodes.map((n) => {
    const c = n.cloneNode(true);
    c.querySelectorAll('button, .rpt-filter, input, select, details.more').forEach((x) => x.remove());
    return c.outerHTML;
  });
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title.replace(/</g, '&lt;')}</title>
<style>${css}
body { padding: 24px 32px; } .wrap { max-width: 1200px; } header.bar { position: static; }
</style></head><body class="exported"><main class="wrap">
<h1 class="export-title">${title.replace(/</g, '&lt;')}</h1>
${parts.join('\n')}
</main></body></html>`;
  return new Blob([html], { type: 'text/html' });
}

export function download(blob, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
