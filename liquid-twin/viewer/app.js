/* RD110 liquid loop — review viewer.
 *
 * Loads the bundle written by prepare_geometry.py: one binary of float32
 * triangle positions plus a manifest saying which slice of it each part owns.
 * Positions only — normals are recomputed here, which halves the payload and
 * gives correct flat shading on non-indexed geometry anyway.
 *
 * Parts are merged into one mesh per (group, service) pair rather than one mesh
 * each. 261 separate meshes is 261 draw calls for a scene that should take
 * eight, and the picking needs a per-part lookup either way — so the merge
 * keeps a triangle-range table and maps a raycast hit back to its part through
 * that. Per-segment temperature colouring in Phase 2 uses the same table, as a
 * vertex-colour range update rather than a material swap.
 *
 * The chiller mode readout is a lookup into the table the manifest carries.
 * The physics lives in dtloop/chiller.py; nothing here recomputes it.
 */

import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';

const MM = 0.001; // the bundle is in mm; the scene works in metres

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x101418);

const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.1, 2000);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
document.getElementById('scene').appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

scene.add(new THREE.HemisphereLight(0xdfe8f0, 0x1a2029, 0.85));
const key = new THREE.DirectionalLight(0xffffff, 1.15);
key.position.set(1, -0.9, 1.6);
scene.add(key);
const fill = new THREE.DirectionalLight(0x9fb4c8, 0.45);
fill.position.set(-1.2, 0.7, 0.5);
scene.add(fill);

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

let manifest = null;
const groups = new Map();   // key -> { mesh, ranges: [{part, first, count}] }
const meshOfKey = new Map();

function colourOf(part) {
  if (part.group === 'valve') return manifest.valve_colour;
  if (part.group === 'meter') return manifest.meter_colour;
  if (part.group === 'pipe') return manifest.service_colour[part.tag];
  return manifest.kind_colour[part.group] || [0.5, 0.5, 0.5];
}

/* Pipes are drawn as one merged mesh per service, so recolouring them by flow
 * or velocity cannot be a material swap. It is a per-vertex colour update over
 * the triangle range each segment owns, which the merge already records. */
function ensureVertexColours(g) {
  const geom = g.mesh.geometry;
  if (geom.getAttribute('color')) return geom.getAttribute('color');
  const n = geom.getAttribute('position').count;
  const attr = new THREE.BufferAttribute(new Float32Array(n * 3), 3);
  geom.setAttribute('color', attr);
  return attr;
}

function paintRange(attr, range, rgb) {
  const from = range.first * 3;
  const to = from + range.count * 3;
  for (let v = from; v < to; v++) attr.setXYZ(v, rgb[0], rgb[1], rgb[2]);
}

/* Blue -> green -> amber -> red, for a normalised 0..1 value. Deliberately not
 * a rainbow: the ends have to read as "low" and "high" at a glance, and a
 * rainbow's yellow is brighter than its red, which inverts the reading. */
function ramp(x) {
  const stops = [
    [0.00, [0.18, 0.40, 0.72]],
    [0.35, [0.24, 0.72, 0.62]],
    [0.70, [0.88, 0.72, 0.28]],
    [1.00, [0.85, 0.28, 0.26]],
  ];
  x = Math.max(0, Math.min(1, x));
  for (let i = 1; i < stops.length; i++) {
    if (x <= stops[i][0]) {
      const [a, ca] = stops[i - 1], [b, cb] = stops[i];
      const f = (x - a) / (b - a);
      return ca.map((c, j) => c + (cb[j] - c) * f);
    }
  }
  return stops[stops.length - 1][1];
}

function groupKey(part) {
  return part.group === 'pipe' ? `pipe:${part.tag}` : part.group;
}

async function load() {
  manifest = await (await fetch('geometry/manifest.json')).json();
  const buf = await (await fetch('geometry/' + manifest.binary)).arrayBuffer();
  const all = new Float32Array(buf);

  // Bucket parts by render group, then build one merged BufferGeometry each.
  const buckets = new Map();
  for (const part of manifest.parts) {
    const k = groupKey(part);
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k).push(part);
  }

  const { min, max } = manifest.bounds;
  const centre = new THREE.Vector3(
    (min[0] + max[0]) / 2 * MM, (min[1] + max[1]) / 2 * MM, (min[2] + max[2]) / 2 * MM);

  for (const [k, parts] of buckets) {
    const nTri = parts.reduce((a, p) => a + p.triangles, 0);
    const pos = new Float32Array(nTri * 9);
    const ranges = [];
    let write = 0, first = 0;
    for (const part of parts) {
      const start = part.byteOffset / 4;
      const count = part.triangles * 9;
      pos.set(all.subarray(start, start + count), write);
      write += count;
      ranges.push({ part, first, count: part.triangles });
      first += part.triangles;
    }
    // Scale to metres and recentre on the plant, in place.
    for (let i = 0; i < pos.length; i += 3) {
      pos[i] = pos[i] * MM - centre.x;
      pos[i + 1] = pos[i + 1] * MM - centre.y;
      pos[i + 2] = pos[i + 2] * MM - centre.z;
    }

    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geom.computeVertexNormals();
    geom.computeBoundingSphere();

    const c = colourOf(parts[0]);
    const mat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(c[0], c[1], c[2]),
      roughness: k.startsWith('pipe') ? 0.42 : 0.78,
      metalness: k.startsWith('pipe') ? 0.5 : 0.15,
      flatShading: true,
    });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.name = k;
    scene.add(mesh);
    groups.set(k, { mesh, ranges });
    meshOfKey.set(mesh, k);
  }

  // Z is up in the bundle. Telling the camera so beats rotating the scene: the
  // orbit then behaves the way a plan view should - dragging sideways spins
  // about the vertical - and part coordinates stay in the frame the manifest
  // and the layout module use, which matters as soon as anything is picked.
  camera.up.set(0, 0, 1);

  buildUI();
  buildInputsUI();
  buildHydraulicsUI();
  document.getElementById('loading').remove();
  document.getElementById('left').hidden = false;
  document.getElementById('right').hidden = false;
  document.getElementById('hydraulics').hidden = false;

  // Fit last, once the panels are laid out. freeBand() measures them, and
  // measuring an element that is still `hidden` returns a zero rect - so
  // fitting before this point silently fell back to the whole viewport.
  fitCamera(min, max);
}

/* Frame the whole plant.
 *
 * Fits the eight bounding-box corners projected onto the camera's own right and
 * up axes, rather than fitting the bounding sphere. The sphere is the tidier
 * formula and it wastes the frame here: this plant is 30 x 27 x 4 m, so its
 * sphere is mostly empty air above and below, and fitting that sphere to the
 * narrower field of view left the model floating in a third of the window.
 * Projecting the corners costs a dozen lines and uses the whole viewport. */
/* The horizontal band left free by the side panels, as {centre, width} in CSS
 * pixels. The panels overlay the canvas rather than shrinking it, so a fit that
 * uses the full viewport hides a third of the plant behind them - which it did. */
function freeBand() {
  let left = 0, right = innerWidth;
  for (const id of ['left']) {
    const el = document.getElementById(id);
    if (el && !el.hidden) left = Math.max(left, el.getBoundingClientRect().right + 12);
  }
  for (const id of ['right', 'hydraulics']) {
    const el = document.getElementById(id);
    if (el && !el.hidden) right = Math.min(right, el.getBoundingClientRect().left - 12);
  }
  const width = Math.max(240, right - left);
  return { centre: (left + right) / 2, width };
}

function fitCamera(min, max) {
  const dir = new THREE.Vector3(0.62, -0.72, 0.31).normalize();
  const up = new THREE.Vector3(0, 0, 1);
  const right = new THREE.Vector3().crossVectors(dir, up).normalize();
  const camUp = new THREE.Vector3().crossVectors(right, dir).normalize();

  const c = [0, 1, 2].map(i => (min[i] + max[i]) / 2 * MM);
  let halfW = 0, halfH = 0, halfD = 0;
  for (const sx of [0, 1]) for (const sy of [0, 1]) for (const sz of [0, 1]) {
    const v = new THREE.Vector3(
      (sx ? max[0] : min[0]) * MM - c[0],
      (sy ? max[1] : min[1]) * MM - c[1],
      (sz ? max[2] : min[2]) * MM - c[2]);
    halfW = Math.max(halfW, Math.abs(v.dot(right)));
    halfH = Math.max(halfH, Math.abs(v.dot(camUp)));
    halfD = Math.max(halfD, Math.abs(v.dot(dir)));
  }

  const vFov = THREE.MathUtils.degToRad(camera.fov);
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
  // Fit at the box centre, not its near face. Adding halfD here - which looked
  // like the safe thing, since the near corner is closer than the centre and so
  // projects larger - pushed the camera back by the plant's own 19 m depth and
  // left the model using 57 % of the window. The margin already covers the
  // perspective growth; halfD belongs in the near plane, below, and nowhere else.
  //
  // The panels overlay the canvas rather than shrinking it, so fitting to the
  // full viewport hides the plant behind them. Fit to the band they leave free
  // instead, then pan the view into that band's centre.
  const band = freeBand();
  const shrink = innerWidth / band.width;
  const distance = Math.max(halfH / Math.tan(vFov / 2),
                            halfW * shrink / Math.tan(hFov / 2)) * 1.08;

  // `right` is cross(dir, up), and the camera looks from `dir` back toward the
  // origin - so its forward is -dir and cross(forward, up) is -right. That makes
  // this vector screen-LEFT, not screen-right, which is why panning by -shift
  // pushed the plant the wrong way and part of it behind the panel it was meant
  // to clear. Panning by +shift along a screen-left axis moves the view left.
  const visibleWidth = 2 * distance * Math.tan(hFov / 2);
  const shift = (band.centre - innerWidth / 2) / innerWidth * visibleWidth;
  const pan = right.clone().multiplyScalar(shift);

  camera.position.copy(dir.clone().multiplyScalar(distance)).add(pan);
  camera.near = Math.max(0.1, distance - halfD * 3);
  camera.far = distance + halfD * 6 + 50;
  camera.updateProjectionMatrix();
  controls.target.copy(pan);
  controls.minDistance = Math.max(halfW, halfH) * 0.1;
  controls.maxDistance = distance * 3;
  controls.update();
}

/* ---------- UI ---------- */

function buildUI() {
  const order = ['pipe:facility_supply', 'pipe:facility_return',
                 'pipe:tcs_supply', 'pipe:tcs_return', 'valve', 'meter',
                 'rack', 'cdu', 'pump', 'chiller'];
  const labels = {
    valve: 'Control valves', meter: 'CDU flow meters', rack: 'AI racks',
    cdu: 'CDUs', pump: 'Chilled water pumps', chiller: 'HT chillers',
  };
  const host = document.getElementById('toggles');
  for (const k of order) {
    const g = groups.get(k);
    if (!g) continue;
    const parts = g.ranges.length;
    let name = labels[k], note = `${parts}`;
    if (k.startsWith('pipe:')) {
      const svc = k.slice(5);
      name = manifest.services[svc].label;
      const m = g.ranges.reduce((a, r) => a + (r.part.length_m || 0), 0);
      note = `${parts} runs · ${m.toFixed(0)} m · ${manifest.services[svc].design_c}°C`;
    }
    const c = colourOf(g.ranges[0].part);
    const el = document.createElement('label');
    el.className = 'toggle';
    el.innerHTML = `<input type="checkbox" checked>
      <i class="swatch" style="background:rgb(${c.map(v => Math.round(v * 255)).join(',')})"></i>
      <span class="t">${name}<br><small>${note}</small></span>`;
    el.querySelector('input').onchange = e => { g.mesh.visible = e.target.checked; };
    host.appendChild(el);
  }

  const totalPipe = manifest.parts
    .filter(p => p.group === 'pipe')
    .reduce((a, p) => a + p.length_m, 0);
  const n = g => manifest.parts.filter(p => p.group === g).length;
  document.getElementById('counts').innerHTML = [
    ['Chillers', `${n('chiller')} (N+1)`],
    ['Chilled water pumps', n('pump')],
    ['CDUs', `${n('cdu')} (3 pods × 3)`],
    ['Flow meters', n('meter')],
    ['Liquid-cooled racks', n('rack')],
    ['Control valves', n('valve')],
    ['Pipe runs', `${n('pipe')} · ${totalPipe.toFixed(0)} m`],
    ['Extent', `${((manifest.bounds.max[0] - manifest.bounds.min[0]) / 1000).toFixed(1)} × ` +
               `${((manifest.bounds.max[1] - manifest.bounds.min[1]) / 1000).toFixed(1)} m`],
    ['Triangles', manifest.total_triangles.toLocaleString()],
  ].map(([a, b]) => `<div class="row"><span>${a}</span><span>${b}</span></div>`).join('');

  const ch = manifest.chillers;
  document.getElementById('chillerModel').textContent =
    `${ch.units}× ${ch.model} · ${ch.running} running · ` +
    `${ch.capacity_kw.toFixed(0)} kW against ${ch.liquid_load_kw.toFixed(0)} kW`;
  document.getElementById('crossover').textContent = `${ch.crossover_c.toFixed(1)} °C`;
  document.getElementById('ambMax').textContent = `${ch.rd110_ambient_max_c} °C`;
  document.getElementById('chillerNote').textContent = ch.note;

  const modes = [
    ['service', 'Service', 'the four loops, at their design temperatures'],
    ['flow', 'Flow', 'mass flow, scaled per service'],
    ['velocity', 'Velocity', 'against a 3 m/s ceiling'],
    ['dp', 'Pressure drop', 'per run, scaled per service'],
  ];
  const cb = document.getElementById('colourBy');
  for (const [key, name, note] of modes) {
    const el = document.createElement('label');
    el.className = 'toggle';
    el.innerHTML = `<input type="radio" name="cb" value="${key}"${key === 'service' ? ' checked' : ''}>
      <span class="t">${name}<br><small>${note}</small></span>`;
    el.querySelector('input').onchange = () => setColourMode(key);
    cb.appendChild(el);
  }

  const slider = document.getElementById('amb');
  slider.oninput = () => setAmbient(parseFloat(slider.value));
}

function rowFor(ambient) {
  const s = manifest.chillers.sweep;
  let best = s[0];
  for (const r of s) if (Math.abs(r.ambient_c - ambient) < Math.abs(best.ambient_c - ambient)) best = r;
  return best;
}

const MODE_TINT = {
  free: [0.31, 0.79, 0.63],
  mixed: [0.88, 0.70, 0.29],
  mechanical: [0.88, 0.42, 0.35],
};

function setAmbient(t) {
  document.getElementById('ambVal').textContent = `${t.toFixed(1)} °C`;
  renderAll();
}

function renderChiller(th) {
  const t = +document.getElementById('amb').value;
  const c = th.chiller;
  document.getElementById('ambVal').textContent = `${t.toFixed(1)} °C`;
  const mode = document.getElementById('mode');
  mode.textContent = c.mode;
  mode.className = 'm-' + c.mode;
  const freePct = c.freeFraction * 100;
  document.getElementById('freePct').textContent = `${freePct.toFixed(0)} %`;
  document.getElementById('barFree').style.width = `${freePct}%`;
  document.getElementById('barMech').style.width = `${100 - freePct}%`;
  document.getElementById('fans').textContent = `${c.fans_kw.toFixed(0)} kW`;
  document.getElementById('comp').textContent = `${c.compressorsKw.toFixed(0)} kW`;
  document.getElementById('total').textContent = `${c.totalKw.toFixed(0)} kW`;
  document.getElementById('cop').textContent =
    c.totalKw > 0 ? (th.rejectedKw / c.totalKw).toFixed(1) : '—';
  // The crossover moves with load: T = T_return - load/UA_free.
  const crossover = manifest.chillers.return_water_c
    - th.rejectedKw / manifest.chillers.ua_free_kw_per_k;
  document.getElementById('crossover').textContent = `${crossover.toFixed(1)} °C`;

  // Tint the chillers by mode, so the switch is visible in the model and not
  // only in the readout. Mixed a third of the way toward the base grey rather
  // than applied flat: these are the largest objects in the scene by a wide
  // margin, and at full saturation four of them swamp the pipework the model
  // exists to show.
  const g = groups.get('chiller');
  if (g) {
    const base = manifest.kind_colour.chiller;
    const tint = MODE_TINT[c.mode] || base;
    const k = 0.34;
    g.mesh.material.color.setRGB(
      base[0] + (tint[0] - base[0]) * k,
      base[1] + (tint[1] - base[1]) * k,
      base[2] + (tint[2] - base[2]) * k);
    g.mesh.material.emissive.setRGB(tint[0] * 0.10, tint[1] * 0.10, tint[2] * 0.10);
  }
  drawChart(t, crossover);
}

function drawChart(marker, crossover) {
  const cv = document.getElementById('chart');
  const ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height, pad = 18;
  ctx.clearRect(0, 0, W, H);
  const s = manifest.chillers.sweep;
  const maxKw = Math.max(...s.map(r => r.total_kw)) * 1.08;
  const x = t => pad + (t - s[0].ambient_c) / (s[s.length - 1].ambient_c - s[0].ambient_c) * (W - pad * 2);
  const y = k => H - pad - k / maxKw * (H - pad * 2);

  // Free-cooling band, so the crossover reads as a region not just a number.
  const xc = x(crossover !== undefined ? crossover : manifest.chillers.crossover_c);
  ctx.fillStyle = 'rgba(78,201,160,.10)';
  ctx.fillRect(pad, pad, xc - pad, H - pad * 2);
  ctx.strokeStyle = 'rgba(78,201,160,.5)';
  ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(xc, pad); ctx.lineTo(xc, H - pad); ctx.stroke();
  ctx.setLineDash([]);

  ctx.strokeStyle = '#2a3239';
  ctx.beginPath(); ctx.moveTo(pad, H - pad); ctx.lineTo(W - pad, H - pad); ctx.stroke();

  // Fans-only floor, then total.
  for (const [key, colour, width] of [['fans_kw', '#4a5a68', 2], ['total_kw', '#7fb2e8', 3]]) {
    ctx.strokeStyle = colour; ctx.lineWidth = width;
    ctx.beginPath();
    s.forEach((r, i) => i ? ctx.lineTo(x(r.ambient_c), y(r[key])) : ctx.moveTo(x(r.ambient_c), y(r[key])));
    ctx.stroke();
  }

  if (marker !== undefined) {
    const r = rowFor(marker);
    ctx.fillStyle = '#e6ebf0';
    ctx.beginPath(); ctx.arc(x(r.ambient_c), y(r.total_kw), 4, 0, 7); ctx.fill();
  }

  ctx.fillStyle = '#8b98a5';
  ctx.font = '11px -apple-system, sans-serif';
  ctx.fillText(`${s[0].ambient_c}°C`, pad, H - 5);
  ctx.textAlign = 'right';
  ctx.fillText(`${s[s.length - 1].ambient_c}°C`, W - pad, H - 5);
  ctx.fillText(`${maxKw.toFixed(0)} kW`, W - pad, pad - 5);
  ctx.textAlign = 'left';
  ctx.fillStyle = 'rgba(78,201,160,.85)';
  ctx.fillText('free cooling', pad + 4, pad + 11);
}

/* ---------- hydraulics ---------- */

let scenarioIndex = 0;
let colourMode = 'service';

/* Live inputs. None of these re-solve the hydraulics, because the hydraulics do
 * not depend on them: flow is set by the pumps and the valve positions, so load
 * and plate area move temperatures and leave every flow where it was. That is
 * what lets them be sliders rather than another precomputed axis.
 *
 * The two lines that do the work are an energy balance and the eps-NTU duty
 * relation, both stated in dtloop/hx.py. The model itself - UA sizing, the COP
 * curve, the mode boundaries - stays in Python. */
const inputs = { rackKw: null, liquidFrac: null, uaIdx: null };

function scenario() { return manifest.scenarios[scenarioIndex]; }

function buildInputsUI() {
  const hc = manifest.heat_constants;
  const hx = manifest.hx_model;
  inputs.rackKw = hc.design_rack_kw;
  inputs.liquidFrac = hc.design_liquid_fraction;
  inputs.uaIdx = hx.ua_scales.indexOf(1.0);

  const rack = document.getElementById('rackKw');
  const liq = document.getElementById('liqFrac');
  const ua = document.getElementById('uaScale');
  rack.value = inputs.rackKw;
  liq.value = Math.round(inputs.liquidFrac * 100);
  ua.max = hx.ua_scales.length - 1;
  ua.value = inputs.uaIdx;

  rack.oninput = () => { inputs.rackKw = +rack.value; renderAll(); };
  liq.oninput = () => { inputs.liquidFrac = +liq.value / 100; renderAll(); };
  ua.oninput = () => { inputs.uaIdx = +ua.value; renderAll(); };
  document.getElementById('resetIT').onclick = () => {
    inputs.rackKw = hc.design_rack_kw;
    inputs.liquidFrac = hc.design_liquid_fraction;
    inputs.uaIdx = hx.ua_scales.indexOf(1.0);
    rack.value = inputs.rackKw;
    liq.value = Math.round(inputs.liquidFrac * 100);
    ua.value = inputs.uaIdx;
    renderAll();
  };

  document.getElementById('hxMethod').textContent = hx.method + ' — ' + hx.calibrated_from;
  document.getElementById('hxRelations').innerHTML = hx.relations.join('<br>');
  document.getElementById('hxCaveats').innerHTML = hx.caveats.join('<br><br>');

  const f = manifest.fluid;
  document.getElementById('fluidName').textContent =
    `${f.name} · grade ${f.confidence} · ${f.source}`;
  const loops = new Set(Object.values(f.loop_temperatures));
  document.getElementById('fluidTable').innerHTML =
    `<tr><th>°C</th><th>ρ kg/m³</th><th>cp J/kgK</th><th>k W/mK</th><th>μ mPa·s</th><th>Pr</th></tr>` +
    f.rows.map(r => `<tr class="${loops.has(r.t_c) ? 'loop' : ''}">
      <td>${r.t_c}</td><td>${r.rho}</td><td>${r.cp}</td>
      <td>${r.k}</td><td>${r.mu_mpas}</td><td>${r.prandtl}</td></tr>`).join('');
  document.getElementById('fluidCaveat').textContent = f.caveat;
}

/* The whole temperature chain, from the IT load outward. Everything here is
 * arithmetic on the solved flows and the exported plate state. */
function thermalState() {
  const s = scenario();
  const hc = manifest.heat_constants;
  const hxm = manifest.hx_model;
  const scale = hxm.ua_scales[inputs.uaIdx];

  const rackLiquidKw = inputs.rackKw * inputs.liquidFrac;
  const rackAirKw = inputs.rackKw * (1 - inputs.liquidFrac);
  const plantLiquidKw = rackLiquidKw * hc.ai_rack_count;
  const itKw = inputs.rackKw * hc.ai_rack_count
             + hc.network_rack_kw * hc.network_rack_count;
  const airKw = rackAirKw * hc.ai_rack_count + hc.network_rack_kw * hc.network_rack_count;

  // Racks: dT = Q/(m cp) at the already-solved flow.
  const racks = {};
  let worst = null, starved = [], over = [];
  for (const [name, r] of Object.entries(s.heat.racks)) {
    const st = r.flow_fraction < hc.starved_flow_fraction;
    const dt = st || r.m_dot_kgs <= 1e-4
      ? null : rackLiquidKw * 1000 / (r.m_dot_kgs * hc.cp_tcs);
    const row = { ...r, duty_kw: rackLiquidKw, starved: st, delta_t_k: dt };
    racks[name] = row;
    if (st) starved.push(name);
    if (!worst || (dt || 0) > (racks[worst].delta_t_k || 0)) worst = name;
  }

  // CDU plates. Duty splits over the CDUs that are actually passing flow.
  const plates = [];
  const live = Object.entries(s.plates).filter(([, p]) => p.hot_flow_kgs > 0.5);
  const dutyPerCdu = live.length ? plantLiquidKw / live.length : 0;
  for (const [name, p] of live) {
    const row = p.by_ua_scale[inputs.uaIdx];  // aligned to hx_model.ua_scales
    const inletDelta = row.effectiveness * row.c_min_kw_per_k > 0
      ? dutyPerCdu / (row.effectiveness * row.c_min_kw_per_k) : null;
    const hotDrop = row.c_hot_kw_per_k > 0 ? dutyPerCdu / row.c_hot_kw_per_k : null;
    plates.push({
      name, ...row, duty_kw: dutyPerCdu,
      inlet_delta_k: inletDelta,
      terminal_approach_k: inletDelta !== null && hotDrop !== null
        ? inletDelta - hotDrop : null,
    });
  }
  const approach = plates.length
    ? Math.max(...plates.map(p => p.terminal_approach_k ?? 0)) : null;

  // Facility side, including the pump work that lands in the fluid.
  const pumpKw = s.heat.pump_hydraulic_kw;
  const rejectedKw = plantLiquidKw + pumpKw;
  const mFac = s.heat.facility.m_dot_kgs;
  const facDt = mFac > 1e-3 ? rejectedKw * 1000 / (mFac * hc.cp_facility) : null;

  // Chillers: capability is load-independent, so look it up and do the balance.
  const amb = +document.getElementById('amb').value;
  const cap = manifest.chillers.capability.reduce((b, r) =>
    Math.abs(r.ambient_c - amb) < Math.abs(b.ambient_c - amb) ? r : b);
  const mechKw = Math.max(0, rejectedKw - cap.q_free_kw);
  const mode = rejectedKw <= 0 ? 'off'
    : cap.q_free_kw >= rejectedKw ? 'free'
    : cap.q_free_kw <= 0 ? 'mechanical' : 'mixed';
  const capacityKw = manifest.chillers.capacity_kw;
  const heldSetpoint = rejectedKw <= capacityKw;

  // The chain. Facility supply is the chiller's setpoint while it has the
  // capacity to hold it; past that the shortfall shows up as a rise, which is
  // the honest way to say "the plant has run out of chiller".
  const facSupply = hc.facility_supply_c
    + (heldSetpoint ? 0 : (rejectedKw - capacityKw) / (mFac * hc.cp_facility / 1000));
  const facReturn = facDt === null ? null : facSupply + facDt;
  const tcsSupply = approach === null ? null : facSupply + approach;
  const rackDt = racks[worst] ? racks[worst].delta_t_k : null;
  const tcsReturn = tcsSupply === null || rackDt === null ? null : tcsSupply + rackDt;

  for (const [name, r] of Object.entries(racks)) {
    r.outlet_c = r.delta_t_k === null || tcsSupply === null
      ? null : tcsSupply + r.delta_t_k;
    r.over_limit = r.outlet_c !== null && r.outlet_c > hc.return_limit_c;
    if (r.over_limit) over.push(name);
  }

  let verdict = 'PASS', reason = '';
  if (starved.length) {
    verdict = 'FAIL'; reason = `${starved.length} rack(s) starved: ${starved.slice(0, 4).join(', ')}`;
  } else if (!heldSetpoint) {
    verdict = 'FAIL';
    reason = `chillers short by ${(rejectedKw - capacityKw).toFixed(0)} kW — ` +
             `${rejectedKw.toFixed(0)} kW against ${capacityKw.toFixed(0)} kW of N+1 capacity`;
  } else if (over.length) {
    verdict = 'FAIL';
    reason = `${over.length} rack(s) over the ${hc.return_limit_c} °C return limit: ` +
             over.slice(0, 4).join(', ');
  } else if (facReturn !== null && facReturn > hc.facility_return_c + 0.5) {
    verdict = 'WARN';
    reason = `racks are fine, but facility return is ${facReturn.toFixed(1)} °C ` +
             `against ${hc.facility_return_c} °C design`;
  } else {
    reason = `worst rise ${rackDt === null ? '—' : rackDt.toFixed(1)} K at ` +
             `${racks[worst].outlet_c === null ? '—' : racks[worst].outlet_c.toFixed(1)} °C`;
  }

  return {
    scale, itKw, plantLiquidKw, airKw, rackLiquidKw, rejectedKw, pumpKw,
    racks, worst, starved, over, plates, approach, verdict, reason,
    facSupply, facReturn, facDt, tcsSupply, tcsReturn, rackDt, mFac,
    chiller: { ...cap, mode, mechKw, compressorsKw: mechKw / cap.cop,
               totalKw: cap.fans_kw + mechKw / cap.cop, capacityKw, heldSetpoint,
               freeFraction: rejectedKw > 0 ? Math.min(1, cap.q_free_kw / rejectedKw) : 0 },
  };
}

function buildHydraulicsUI() {
  const sel = document.getElementById('scenario');
  manifest.scenarios.forEach((s, i) => {
    const o = document.createElement('option');
    o.value = i;
    o.textContent = s.label;
    sel.appendChild(o);
  });
  sel.onchange = () => { scenarioIndex = +sel.value; renderAll(); };
  renderAll();
}

function renderAll() {
  const th = thermalState();
  renderInputs(th);
  renderTemperatures(th);
  renderHydraulics(th);
  renderChiller(th);
}

function renderInputs(th) {
  const hc = manifest.heat_constants;
  document.getElementById('rackKwVal').textContent = `${inputs.rackKw} kW`;
  document.getElementById('liqFracVal').textContent =
    `${(inputs.liquidFrac * 100).toFixed(0)} %` +
    (Math.abs(inputs.liquidFrac - hc.design_liquid_fraction) < 1e-9 ? ' (RD110)' : '');
  document.getElementById('itSummary').innerHTML = rows([
    ['To liquid, per rack', `${th.rackLiquidKw.toFixed(1)} kW`],
    ['To air, per rack', `${(inputs.rackKw - th.rackLiquidKw).toFixed(1)} kW`],
    [`× ${hc.ai_rack_count} AI racks`, `${th.plantLiquidKw.toFixed(0)} kW liquid`],
    [`+ ${hc.network_rack_count} × ${hc.network_rack_kw} kW networking`, 'air only'],
    ['Total IT electrical', `${th.itKw.toFixed(0)} kW`],
  ]);
  document.getElementById('itNote').textContent = hc.note;

  const hxm = manifest.hx_model;
  document.getElementById('uaScaleVal').textContent =
    `${th.scale.toFixed(2)}×` + (th.scale === 1 ? ' (RD110)' : '');
  const p0 = th.plates[0];
  document.getElementById('hxState').innerHTML = p0 ? rows([
    ['UA per plate', `${p0.ua_kw_per_k.toFixed(0)} kW/K`],
    ['NTU', p0.ntu.toFixed(2)],
    ['Cr', p0.cr.toFixed(3)],
    ['Effectiveness ε', p0.effectiveness.toFixed(3)],
    ['Duty per CDU', `${p0.duty_kw.toFixed(0)} kW`],
    ['Inlet-to-inlet ΔT', p0.inlet_delta_k === null ? '—' : `${p0.inlet_delta_k.toFixed(2)} K`],
    ['Terminal approach', p0.terminal_approach_k === null ? '—'
      : `${p0.terminal_approach_k.toFixed(2)} K`,
      p0.terminal_approach_k > 6 ? 'warn' : ''],
  ]) : '<div class="row"><span>no plate passing flow</span><span>—</span></div>';
}

const SERVICE_DOT = {
  facility_supply: '#3399d9', facility_return: '#d9741f',
  tcs_supply: '#4dbfa6', tcs_return: '#cc4048',
};

function renderTemperatures(th) {
  const hc = manifest.heat_constants;
  const amb = +document.getElementById('amb').value;
  const fmt = v => v === null ? '—' : `${v.toFixed(1)} °C`;
  const dev = (v, design) => v === null ? ''
    : Math.abs(v - design) < 0.35 ? 'on design'
    : `${v > design ? '+' : ''}${(v - design).toFixed(1)} K`;

  const chain = [
    ['#6b7a88', 'Ambient air', amb, null, ''],
    [SERVICE_DOT.facility_supply, 'Facility supply — chiller out, CDU in',
      th.facSupply, hc.facility_supply_c,
      th.chiller.heldSetpoint ? '' : 'bad'],
    [SERVICE_DOT.tcs_supply, 'TCS supply — cold plate in',
      th.tcsSupply, hc.tcs_supply_c, ''],
    [SERVICE_DOT.tcs_return, 'TCS return — cold plate out',
      th.tcsReturn, hc.tcs_return_c,
      th.tcsReturn !== null && th.tcsReturn > hc.return_limit_c ? 'bad' : ''],
    [SERVICE_DOT.facility_return, 'Facility return — chiller in',
      th.facReturn, hc.facility_return_c,
      th.facReturn !== null && th.facReturn > hc.facility_return_c + 0.5 ? 'warn' : ''],
  ];
  document.getElementById('temps').innerHTML = '<div class="chain">' + chain.map(
    ([dot, label, v, design, cls]) => `<div>
      <i class="dot" style="background:${dot}"></i>
      <b>${label}</b>
      <span class="t ${cls}">${fmt(v)}</span>
      <span class="d">${design === null ? '' : dev(v, design)}</span>
    </div>`).join('') + '</div>' + rows([
      ['CDU plate approach', th.approach === null ? '—' : `${th.approach.toFixed(2)} K`],
      ['Cold plate rise', th.rackDt === null ? '—' : `${th.rackDt.toFixed(2)} K`],
      ['Facility rise', th.facDt === null ? '—' : `${th.facDt.toFixed(2)} K`],
    ]);
  document.getElementById('tempNote').textContent = th.chiller.heldSetpoint
    ? 'Facility supply is the chillers\u2019 setpoint; the rest follows from the plate and the solved flows.'
    : `Facility supply has drifted above setpoint: the chillers are short by ${
        (th.rejectedKw - th.chiller.capacityKw).toFixed(0)} kW.`;
}

function rows(pairs) {
  return pairs.map(([a, b, cls]) =>
    `<div class="row"><span>${a}</span><span class="${cls || ''}">${b}</span></div>`).join('');
}

function renderHydraulics(th) {
  const s = scenario();
  const v = document.getElementById('verdict');
  v.textContent = th.verdict;
  v.className = 'verdict v-' + th.verdict;
  document.getElementById('verdictWhy').textContent = th.reason;
  document.getElementById('scenarioNote').textContent = s.note;

  // Circuits: solved flow against design, and the pressure band.
  document.getElementById('circuits').innerHTML = Object.values(s.circuits).map(c => {
    const pct = c.total_flow_kgs / c.design_flow_kgs * 100;
    const cls = pct < 90 ? 'bad' : pct < 98 ? 'warn' : '';
    const spread = c.pump_flow_spread > 0.5
      ? `<em>pump spread ${c.pump_flow_spread.toFixed(1)} kg/s — the pumps are not sharing</em>` : '';
    const rev = c.reverse_flow_branches.length
      ? `<em class="bad">reverse flow: ${c.reverse_flow_branches.slice(0, 3).join(', ')}</em>` : '';
    const fast = c.over_velocity.length
      ? `<em class="bad">over ${c.velocity_limit_ms} m/s: ${
          c.over_velocity.slice(0, 2).map(o => `${o.branch} ${o.velocity_ms}`).join(', ')}</em>`
      : `<em>peak velocity ${c.max_velocity_ms} m/s of ${c.velocity_limit_ms} allowed</em>`;
    return `<div class="seg">
      <b>${c.circuit}</b><span class="${cls}">${c.total_flow_kgs.toFixed(1)} kg/s</span>
      <em>${pct.toFixed(0)} % of ${c.design_flow_kgs.toFixed(1)} design ·
          ${c.pressure_min_kpa.toFixed(0)}–${c.pressure_max_kpa.toFixed(0)} kPa ·
          ${c.temperature_c} °C</em>${fast}${spread}${rev}</div>`;
  }).join('');

  // Flow meters, one row per CDU rather than one per meter: 18 rows pushed the
  // pumps below the fold, and the pair on a CDU is what a reader compares
  // anyway - the two sides of one plate should carry the same duty.
  const meters = {};
  for (const c of Object.values(s.circuits)) {
    for (const [tag, m] of Object.entries(c.meters)) meters[tag] = m;
  }
  const n = manifest.parts.filter(p => p.group === 'cdu').length;
  document.getElementById('meters').innerHTML = Array.from({ length: n }, (_, i) => {
    const id = String(i + 1).padStart(2, '0');
    const f = meters[`FM-F${id}`], tcs = meters[`FM-T${id}`];
    const dead = q => Math.abs(q ?? 0) < 5;
    const fmt = (m, cls) => m
      ? `<span class="${cls}">${m.q_m3h.toFixed(0)}</span>`
      : `<span class="dim">—</span>`;
    return `<div class="row"><span>CDU-${i + 1}</span><span>
      ${fmt(f, dead(f?.q_m3h) ? 'bad' : '')} <small style="color:var(--dim)">fac</small>
      &nbsp;·&nbsp;
      ${fmt(tcs, dead(tcs?.q_m3h) ? 'bad' : '')} <small style="color:var(--dim)">tcs m³/h</small>
      </span></div>`;
  }).join('');

  // Pumps: chiller-side CWPs first, then the CDU integral pumps.
  const pumps = [];
  for (const c of Object.values(s.circuits)) {
    for (const [name, p] of Object.entries(c.pumps)) pumps.push([name, p]);
  }
  pumps.sort((a, b) => (a[0].startsWith('CWP') ? 0 : 1) - (b[0].startsWith('CWP') ? 0 : 1)
                       || a[0].localeCompare(b[0]));
  document.getElementById('pumps').innerHTML = pumps.map(([name, p]) => {
    const off = p.speed === 0;
    const label = name.replace('_UNIT', '').replace('_PLATE_TCS', ' pump');
    // CWP-4 is the N+1 standby and is not in the solved network at all, which is
    // why it has no row here. Saying so beats leaving a reader to wonder.
    return `<div class="seg">
      <b>${label}${off ? ' — off' : ''}</b>
      <span class="${off ? 'bad' : ''}">${p.q_m3h.toFixed(0)} m³/h</span>
      <em>${p.suction_kpa.toFixed(0)} → ${p.discharge_kpa.toFixed(0)} kPa ·
          ${p.head_m.toFixed(1)} m · ${p.shaft_kw ?? 0} kW shaft${
            p.speed !== 1 ? ` · ${(p.speed * 100).toFixed(0)} % speed` : ''}</em></div>`;
  }).join('') +
    `<div class="row"><span>CWP-4</span><span style="color:var(--dim)">standby, N+1</span></div>`;

  // Electrical load to heat to liquid, all of it live off the sliders.
  const liqPct = th.plantLiquidKw / th.itKw * 100;
  const w = th.racks[th.worst];
  document.getElementById('heat').innerHTML =
    rows([['IT electrical', `${th.itKw.toFixed(0)} kW`]]) +
    `<div class="sankey">
       <i style="width:${liqPct}%;background:#3ba3d0"></i>
       <i style="width:${100 - liqPct}%;background:#c98a4a"></i>
     </div>` +
    rows([
      ['→ liquid', `${th.plantLiquidKw.toFixed(0)} kW (${liqPct.toFixed(0)} %)`],
      ['→ air', `${th.airKw.toFixed(0)} kW`],
      ['+ pump work in fluid', `${th.pumpKw.toFixed(0)} kW`],
      ['= rejected at chillers', `${th.rejectedKw.toFixed(0)} kW`,
        th.chiller.heldSetpoint ? '' : 'bad'],
      ['Chiller capacity, N+1', `${th.chiller.capacityKw.toFixed(0)} kW`],
      ['Worst rack', th.worst],
      ['its rise', th.rackDt === null
        ? 'starved — no steady state'
        : `${th.rackDt.toFixed(1)} K vs ${manifest.heat_constants.design_delta_t_k} design`,
        th.rackDt === null ? 'bad' : th.rackDt > 13 ? 'warn' : ''],
      ['its outlet', w.outlet_c === null ? '—' : `${w.outlet_c.toFixed(1)} °C`,
        w.over_limit ? 'bad' : ''],
    ]);

  applyColourMode();
}

function setColourMode(mode) {
  colourMode = mode;
  applyColourMode();
}

function applyColourMode() {
  const flows = scenario().segment_flow;
  for (const [key, g] of groups) {
    if (!key.startsWith('pipe:')) continue;
    const mat = g.mesh.material;
    if (colourMode === 'service') {
      mat.vertexColors = false;
      const c = manifest.service_colour[key.slice(5)];
      mat.color.setRGB(c[0], c[1], c[2]);
      mat.needsUpdate = true;
      continue;
    }
    // Scale per service, not across the whole plant: a DN50 rack drop and a
    // DN150 main differ by an order of magnitude in flow, and one global scale
    // paints every drop the same colour and tells the reader nothing.
    const vals = g.ranges.map(r => metric(flows[r.part.name]));
    const hi = Math.max(...vals.filter(v => v !== null), 1e-9);
    const attr = ensureVertexColours(g);
    g.ranges.forEach((r, i) => {
      const val = vals[i];
      paintRange(attr, r, val === null ? [0.22, 0.24, 0.26] : ramp(val / hi));
    });
    attr.needsUpdate = true;
    mat.vertexColors = true;
    mat.color.setRGB(1, 1, 1);
    mat.needsUpdate = true;
  }
}

function metric(row) {
  if (!row) return null;
  if (colourMode === 'flow') return Math.abs(row.m_dot_kgs);
  if (colourMode === 'velocity') return Math.abs(row.velocity_ms ?? 0);
  if (colourMode === 'dp') return Math.abs(row.dp_kpa);
  return null;
}

/* ---------- picking ---------- */

renderer.domElement.addEventListener('click', ev => {
  pointer.x = (ev.clientX / innerWidth) * 2 - 1;
  pointer.y = -(ev.clientY / innerHeight) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects([...groups.values()].map(g => g.mesh).filter(m => m.visible));
  const box = document.getElementById('pick');
  if (!hits.length) { box.style.display = 'none'; return; }

  // Map the hit triangle back to its part through the merged range table.
  const hit = hits[0];
  const g = groups.get(meshOfKey.get(hit.object));
  const tri = Math.floor(hit.faceIndex);
  const range = g.ranges.find(r => tri >= r.first && tri < r.first + r.count);
  const p = range ? range.part : null;
  if (!p) { box.style.display = 'none'; return; }

  const bits = [`<strong>${p.name}</strong>`];
  if (p.label) bits.push(p.label);
  const flows = scenario().segment_flow;
  if (p.group === 'pipe') {
    bits.push(`DN${p.dn} · ${p.length_m} m · ${p.elbows} elbow${p.elbows === 1 ? '' : 's'} · ` +
              `${manifest.services[p.tag].label}`);
    const f = flows[p.name];
    if (f) {
      bits.push(`<strong>${f.m_dot_kgs.toFixed(2)} kg/s</strong> · ${f.q_m3h.toFixed(1)} m³/h` +
                (f.velocity_ms !== null ? ` · ${f.velocity_ms.toFixed(2)} m/s` : '') +
                ` · Δp ${f.dp_kpa.toFixed(1)} kPa`);
    }
    bits.push(`<span style="color:var(--dim)">${p.from} → ${p.to}` +
              (p.valve ? ` · valve ${p.valve}` : '') +
              (p.meter ? ` · meter ${p.meter}` : '') + `</span>`);
  } else if (p.group === 'valve') {
    bits.push(`Control valve on ${p.on_segment} · DN${p.dn}`);
    const vb = findBranchByValve(p.name);
    if (vb) {
      bits.push(`lift ${(vb.valve_position * 100).toFixed(0)} % · ` +
                `Δp ${vb.dp_kpa.toFixed(1)} kPa · authority ${vb.valve_authority}`);
    }
  } else if (p.group === 'meter') {
    const m = findMeter(p.name);
    bits.push(`Flow meter on ${p.on_segment} · DN${p.dn}`);
    if (m) bits.push(`<strong>${m.l_per_s.toFixed(1)} L/s</strong> · ${m.q_m3h.toFixed(1)} m³/h`);
  } else if (p.group === 'pump') {
    const pm = findPump(p.name);
    if (pm) {
      bits.push(`<strong>${pm.q_m3h.toFixed(0)} m³/h</strong> · ${pm.head_m.toFixed(1)} m head`);
      bits.push(`${pm.suction_kpa.toFixed(0)} → ${pm.discharge_kpa.toFixed(0)} kPa · ` +
                `${pm.shaft_kw ?? 0} kW shaft · ${(pm.speed * 100).toFixed(0)} % speed`);
    }
  } else if (p.group === 'rack') {
    const r = scenario().heat.racks[p.name];
    if (r) {
      bits.push(`<strong>${r.duty_kw} kW to liquid</strong> · ${r.m_dot_kgs.toFixed(2)} kg/s ` +
                `(${(r.flow_fraction * 100).toFixed(0)} % of design)`);
      bits.push(r.starved
        ? `<span style="color:var(--mech)">starved — no steady state</span>`
        : `rise ${r.delta_t_k.toFixed(1)} K → outlet ${r.outlet_c.toFixed(1)} °C` +
          (r.over_limit ? ` <span style="color:var(--mech)">over limit</span>` : ''));
    }
  }
  if (p.pod !== null && p.pod !== undefined) bits.push(`<span style="color:var(--dim)">Pod ${p.pod + 1}</span>`);
  box.innerHTML = bits.join('<br>');
  box.style.display = 'block';
});

function findMeter(tag) {
  for (const c of Object.values(scenario().circuits)) if (c.meters[tag]) return c.meters[tag];
  return null;
}

function findPump(name) {
  for (const c of Object.values(scenario().circuits)) {
    for (const [k, v] of Object.entries(c.pumps)) if (k.startsWith(name)) return v;
  }
  return null;
}

function findBranchByValve(tag) {
  for (const c of Object.values(scenario().circuits)) {
    for (const b of Object.values(c.branches)) if (b.valve === tag) return b;
  }
  return null;
}

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

addEventListener('keydown', e => {
  if (e.key === 'f' && manifest) fitCamera(manifest.bounds.min, manifest.bounds.max);
});

(function tick() {
  requestAnimationFrame(tick);
  controls.update();
  renderer.render(scene, camera);
})();

load().catch(e => {
  document.getElementById('loading').textContent =
    'could not load geometry — run ./viewer/prepare_geometry.py, then serve this directory. ' + e;
});
