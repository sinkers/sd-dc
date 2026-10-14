// What each IndustroML asset kind looks like in the viewer: its glyph on the
// one-line diagram, its state, its dials and its readouts. Keyed by kind, the
// same key dtpower.components.REGISTRY uses, so a model built by hand or by a
// drag-and-drop editor renders without per-simulation code.
//
// Every function takes the asset's snapshot from a simulated (or measured) row.

import { fix, kw, minutes, money, pct, price, symlog } from '../ui/format.js';

const stateOf = (text, cls = '') => ({ text, cls });

export const KINDS = {
  utility_supply: {
    glyph: 'grid',
    badge: (s) => ({ text: `${price(s.price)}/MWh`, cls: 'price' }),
    kw: (s) => s.import_kw - s.export_kw,
    state: (s) => (!s.up ? stateOf('Outage', 'alarm')
      : s.v_pct < 90 ? stateOf(`Sag to ${Math.round(s.v_pct)} %`, 'alarm')
      : s.over_capacity ? stateOf('Over capacity', 'alarm')
      : s.export_kw > 0 ? stateOf('Exporting', 'discharge') : stateOf('Importing')),
    dials: [
      { id: 'price', label: 'Spot price', unit: '$/MWh', scale: symlog, format: (v) => price(v).replace('$', ''),
        range: (s, ctx) => [Math.min(-100, ctx.priceMin), Math.max(300, ctx.priceMax)],
        value: (s) => s.price, cls: (s, ctx) => (s.price >= ctx.dischargeAbove ? 'discharge' : s.price <= ctx.chargeBelow ? 'charge' : '') },
      { id: 'import', label: 'Grid import', unit: 'kW', format: (v) => kw(v),
        range: (s) => [0, s.capacity_kw], bands: (s) => [{ from: 0.9 * s.capacity_kw, to: s.capacity_kw }],
        value: (s) => s.import_kw - s.export_kw, cls: (s) => (s.over_capacity ? 'alarm' : '') },
    ],
    stats: [
      ['Connection used', (s) => `${pct(s.utilisation_pct)} %`],
      ['Bill so far', (s) => money(s.cost)],
      ['Imported', (s) => `${fix(s.import_kwh / 1000, 2)} MWh`],
      ['Exported', (s) => `${fix(s.export_kwh, 0)} kWh`],
      ['Voltage', (s) => (s.up ? `${fix(s.v_pct, 0)} %${s.dip_ms > 0 ? ` for ${fix(s.dip_ms, 0)} ms` : ''}` : 'none')],
    ],
  },

  switchboard: {
    glyph: 'bus',
    kw: (s) => s.net_kw,
    state: () => stateOf(''),
    dials: [],
    stats: [['Feeder load', (s) => `${kw(s.load_kw)} kW`], ['Storage', (s) => `${kw(s.storage_kw)} kW`]],
  },

  bess: {
    glyph: 'battery',
    soc: (s) => ({ pct: s.soc_pct, cls: s.status === 'charging' ? 'charge' : s.status === 'discharging' ? 'discharge' : '' }),
    draw: (s) => -s.ac_kw,
    kw: (s) => s.ac_kw,
    state: (s) => ({
      charging: stateOf('Charging', 'charge'), discharging: stateOf('Discharging', 'discharge'),
      idle: stateOf('Idle'), full: stateOf('Full'), empty: stateOf('At reserve'),
      disabled: stateOf('Disabled'), tripped: stateOf(`Tripped${s.trip_cause ? `: ${s.trip_cause}` : ''}`, 'alarm'),
      reconnecting: stateOf(`Reconnect in ${Math.ceil(s.reconnect_remaining_s)} s`, 'alarm'),
    }[s.status] ?? stateOf(s.status)),
    dials: [
      { id: 'soc', label: 'State of charge', unit: '%', format: (v) => fix(v, 0),
        range: () => [0, 100], bands: (s) => [{ from: 0, to: s.soc_min_pct }, { from: s.soc_max_pct, to: 100 }],
        value: (s) => s.soc_pct, cls: (s) => (s.status === 'charging' ? 'charge' : s.status === 'discharging' ? 'discharge' : '') },
      { id: 'power', label: 'Power (+ out)', unit: 'kW', centerZero: true, format: (v) => kw(v),
        range: (s) => [-s.rated_kw, s.rated_kw], limLabels: (r) => [`−${kw(r.max)}`, `+${kw(r.max)}`],
        value: (s) => s.ac_kw, cls: (s) => (s.dc_kw > 0 ? 'discharge' : s.dc_kw < 0 ? 'charge' : '') },
    ],
    stats: [
      ['Rate', (s) => `${fix(s.c_rate, 2)} C`],
      ['Stored', (s) => `${fix(s.energy_kwh, 0)} kWh`],
      ['Size', (s) => `${fix(s.rated_kw, 0)} kW / ${fix(s.capacity_kwh, 0)} kWh`],
      ['Duration', (s) => `${fix(s.duration_h, 1)} h`],
      ['Cycles so far', (s) => fix(s.cycles, 2)],
      ['Wear so far', (s) => money(s.wear_cost)],
      ['Power limit', (s) => (s.power_limit_kw < s.rated_kw - 0.5 ? `${kw(s.power_limit_kw)} kW, ramping` : 'full')],
      ['Fault ride-through', (s) => `${s.lvrt ? 'on' : 'off'}${s.trips ? `, ${s.trips} trip${s.trips > 1 ? 's' : ''}` : ''}`],
    ],
  },

  ups: {
    glyph: 'converter',
    soc: (s) => ({ pct: s.battery_soc_pct,
                   cls: s.status === 'on battery' ? 'discharge' : s.status === 'load dropped' ? 'alarm' : s.battery_soc_pct < 99.9 ? 'charge' : '' }),
    draw: (s) => s.input_kw,
    kw: (s) => s.output_kw,
    state: (s) => ({
      online: stateOf('Online', 'ok'), eco: stateOf('Eco mode', 'ok'), bypass: stateOf('Static bypass', 'discharge'),
      'on battery': stateOf(`On battery${s.cause ? `: ${s.cause}` : ''}`, 'discharge'),
      resync: stateOf(`On battery, resync in ${Math.ceil(s.resync_remaining_s)} s`, 'discharge'),
      'walk-in': stateOf('Walk-in to grid', 'discharge'),
      recharging: stateOf(s.recharge_limited ? 'Recharging, held to max demand' : 'Recharging', 'charge'),
      'load dropped': stateOf('Load dropped', 'alarm'),
    }[s.status] ?? stateOf(s.status)),
    dials: [
      { id: 'load', label: 'UPS load', unit: '%', format: (v) => fix(v, 0),
        range: () => [0, 120], bands: () => [{ from: 100, to: 120 }],
        value: (s) => (s.status === 'load dropped' ? 0 : s.load_pct), cls: (s) => (s.load_pct > 100 ? 'alarm' : '') },
      { id: 'batt', label: 'UPS battery', unit: '%', format: (v) => fix(v, 0),
        range: () => [0, 100], value: (s) => s.battery_soc_pct,
        cls: (s) => (['on battery', 'resync', 'walk-in'].includes(s.status) ? 'discharge'
          : s.status === 'recharging' ? 'charge' : s.status === 'load dropped' ? 'alarm' : '') },
      { id: 'input', label: 'UPS input', unit: 'kW', format: (v) => kw(v),
        range: (s) => [0, Math.max(s.rated_kw * 0.9, (s.max_demand_kw ?? 0) * 1.25)],
        bands: (s) => (s.max_demand_kw ? [{ from: s.max_demand_kw, to: Math.max(s.rated_kw * 0.9, s.max_demand_kw * 1.25) }] : []),
        value: (s) => s.input_kw,
        cls: (s) => (s.max_demand_kw && s.input_kw > s.max_demand_kw + 0.01 ? 'alarm' : s.recharge_kw > 0.05 ? 'charge' : '') },
    ],
    stats: [
      ['Efficiency', (s) => (s.eff_pct ? `${fix(s.eff_pct, 1)} %` : '–')],
      ['Losses', (s) => `${fix(s.loss_kw, 1)} kW`],
      ['Autonomy', (s) => minutes(s.autonomy_min)],
      ['Input', (s) => `${kw(s.input_kw)} kW`],
      ['Unserved so far', (s) => `${fix(s.unserved_kwh, 1)} kWh`],
      ['Rating', (s) => `${fix(s.rated_kw, 0)} kW`],
      ['Recharge', (s) => `${fix(s.recharge_kw, 1)} kW${s.recharge_limited ? ', held' : ''}`],
      ['Max demand', (s) => (s.max_demand_kw ? `${fix(s.max_demand_kw, 0)} kW` : 'not limited')],
      ['Ride-through', (s) => (s.ride_through ? 'on' : 'off')],
      ['On battery so far', (s) => `${fix(s.on_battery_s, 0)} s, ${s.transfers} transfer${s.transfers === 1 ? '' : 's'}`],
    ],
  },

  server: {
    glyph: 'rack',
    draw: (s) => s.kw,
    kw: (s) => s.kw,
    state: (s) => (s.capped ? stateOf('Power capped', 'discharge') : stateOf('Running')),
    dials: [
      { id: 'kw', label: 'Fleet power', unit: 'kW', format: (v) => kw(v),
        range: (s) => [0, s.max_kw], bands: (s) => [{ from: 0, to: s.idle_kw }],
        value: (s) => s.kw, cls: (s) => (s.capped ? 'discharge' : '') },
      { id: 'tp', label: 'Throughput', unit: '%', format: (v) => fix(v, 0),
        range: () => [0, 100], value: (s) => s.throughput_pct, cls: (s) => (s.capped ? 'discharge' : 'ok') },
    ],
    stats: [
      ['Uncapped demand', (s) => `${kw(s.uncapped_kw)} kW`],
      ['Curtailed so far', (s) => `${fix(s.curtailed_kwh, 0)} kWh`],
      ['Compute lost', (s) => `${fix(s.work_lost_server_h, 1)} server-h`],
      ['Server', (s) => s.server_label],
    ],
  },

  generator: {
    glyph: 'gen',
    kw: (s) => s.kw,
    draw: (s) => s.kw,
    state: (s) => ({
      disabled: stateOf('Disabled'), off: stateOf('Stopped'),
      starting: stateOf(`Starting, ${Math.ceil(s.countdown_s)} s`, 'discharge'),
      running: s.islanded
        ? stateOf(s.countdown_s > 0 ? `To grid in ${Math.ceil(s.countdown_s)} s` : 'Islanded', 'ok')
        : stateOf('In parallel', 'ok'),
      cooldown: stateOf('Cooling down'), tripped: stateOf('Tripped on overload', 'alarm'),
    }[s.state] ?? stateOf(s.state)),
    dials: [
      { id: 'kw', label: 'Output', unit: 'kW', format: (v) => kw(v),
        range: (s) => [0, s.rated_kw * 1.2], bands: (s) => [{ from: s.rated_kw, to: s.rated_kw * 1.2 }],
        value: (s) => s.kw, cls: (s) => (s.state === 'tripped' ? 'alarm' : s.kw > s.rated_kw ? 'alarm' : s.kw > 0 ? 'ok' : '') },
      { id: 'load', label: 'Load', unit: '% of prime', format: (v) => fix(v, 0),
        range: () => [0, 120], bands: () => [{ from: 100, to: 120 }],
        value: (s) => s.load_pct, cls: (s) => (s.load_pct > 100 ? 'alarm' : s.kw > 0 ? 'ok' : '') },
    ],
    stats: [
      ['Rating', (s) => `${fix(s.prime_kva, 0)} kVA × ${fix(s.pf, 2)} = ${fix(s.rated_kw, 0)} kW`],
      ['Starts on', (s) => `outage${s.price_start ? `, price ≥ ${price(s.price_threshold)}` : ''}`],
      ['Energy so far', (s) => `${fix(s.kwh, 0)} kWh`],
      ['Run time', (s) => minutes(s.run_h * 60)],
      ['Fuel so far', (s) => `${fix(s.fuel_l, 0)} L, ${money(s.fuel_cost)}`],
      ['Running cost', (s) => `${price(s.cost_per_mwh)}/MWh`],
      ['Starts, trips', (s) => `${s.starts}, ${s.trips}`],
    ],
  },

  plc: {
    glyph: 'controller',
    kw: () => null,
    state: (s) => ({ charge: stateOf('Charge', 'charge'), discharge: stateOf('Discharge', 'discharge'),
                     'peak shave': stateOf('Peak shave', 'discharge') }[s.decision]
      ?? stateOf('Hold')),
    dials: [],
    stats: [['Decision', (s) => s.decision], ['Strategy', (s) => (s.strategy === 'optimal' ? 'Optimal (foresight)' : 'Thresholds')]],
  },
};

export const kindOf = (k) => KINDS[k] ?? {
  glyph: 'box', kw: () => null, state: () => stateOf(''), dials: [], stats: [],
};
