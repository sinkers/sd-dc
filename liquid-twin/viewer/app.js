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
  drawChart();
  setAmbient(parseFloat(slider.value));
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
  const r = rowFor(t);
  document.getElementById('ambVal').textContent = `${t.toFixed(1)} °C`;
  const mode = document.getElementById('mode');
  mode.textContent = r.mode;
  mode.className = 'm-' + r.mode;
  const freePct = r.free_fraction * 100;
  document.getElementById('freePct').textContent = `${freePct.toFixed(0)} %`;
  document.getElementById('barFree').style.width = `${freePct}%`;
  document.getElementById('barMech').style.width = `${100 - freePct}%`;
  document.getElementById('fans').textContent = `${r.fans_kw.toFixed(0)} kW`;
  document.getElementById('comp').textContent = `${r.compressors_kw.toFixed(0)} kW`;
  document.getElementById('total').textContent = `${r.total_kw.toFixed(0)} kW`;
  document.getElementById('cop').textContent = r.cop_effective.toFixed(1);

  // Tint the chillers by mode, so the switch is visible in the model and not
  // only in the readout. Mixed a third of the way toward the base grey rather
  // than applied flat: these are the largest objects in the scene by a wide
  // margin, and at full saturation four of them swamp the pipework the model
  // exists to show.
  const g = groups.get('chiller');
  if (g) {
    const base = manifest.kind_colour.chiller;
    const c = MODE_TINT[r.mode] || base;
    const k = 0.34;
    g.mesh.material.color.setRGB(
      base[0] + (c[0] - base[0]) * k,
      base[1] + (c[1] - base[1]) * k,
      base[2] + (c[2] - base[2]) * k);
    g.mesh.material.emissive.setRGB(c[0] * 0.10, c[1] * 0.10, c[2] * 0.10);
  }
  drawChart(t);
}

function drawChart(marker) {
  const cv = document.getElementById('chart');
  const ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height, pad = 18;
  ctx.clearRect(0, 0, W, H);
  const s = manifest.chillers.sweep;
  const maxKw = Math.max(...s.map(r => r.total_kw)) * 1.08;
  const x = t => pad + (t - s[0].ambient_c) / (s[s.length - 1].ambient_c - s[0].ambient_c) * (W - pad * 2);
  const y = k => H - pad - k / maxKw * (H - pad * 2);

  // Free-cooling band, so the crossover reads as a region not just a number.
  const xc = x(manifest.chillers.crossover_c);
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

function scenario() { return manifest.scenarios[scenarioIndex]; }

function buildHydraulicsUI() {
  const sel = document.getElementById('scenario');
  manifest.scenarios.forEach((s, i) => {
    const o = document.createElement('option');
    o.value = i;
    o.textContent = s.label;
    sel.appendChild(o);
  });
  sel.onchange = () => { scenarioIndex = +sel.value; renderHydraulics(); };
  renderHydraulics();
}

function rows(pairs) {
  return pairs.map(([a, b, cls]) =>
    `<div class="row"><span>${a}</span><span class="${cls || ''}">${b}</span></div>`).join('');
}

function renderHydraulics() {
  const s = scenario();
  const v = document.getElementById('verdict');
  v.textContent = s.heat.verdict;
  v.className = 'verdict v-' + s.heat.verdict;
  document.getElementById('verdictWhy').textContent = s.heat.verdict_reason;
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

  // Electrical load to heat to liquid.
  const h = s.heat, e = h.electrical;
  const liqPct = e.to_liquid_kw / e.it_electrical_kw * 100;
  document.getElementById('heat').innerHTML =
    rows([['IT electrical', `${e.it_electrical_kw.toFixed(0)} kW`]]) +
    `<div class="sankey">
       <i style="width:${liqPct}%;background:#3ba3d0"></i>
       <i style="width:${100 - liqPct}%;background:#c98a4a"></i>
     </div>` +
    rows([
      ['→ liquid', `${e.to_liquid_kw.toFixed(0)} kW (${liqPct.toFixed(0)} %)`],
      ['→ air', `${e.to_air_kw.toFixed(0)} kW`],
      ['Carried by liquid', `${h.carried_by_liquid_kw.toFixed(0)} kW`],
      ['+ pump work in fluid', `${h.pump_hydraulic_kw.toFixed(0)} kW`],
      ['= rejected at chillers', `${h.rejected_at_chillers_kw.toFixed(0)} kW`],
      ['Pump shaft power', `${h.pump_shaft_kw.toFixed(0)} kW`],
      ['Worst rack', h.worst_rack],
      ['its rise', h.worst_delta_t_k === null
        ? `starved — no steady state`
        : `${h.worst_delta_t_k.toFixed(1)} K vs ${h.design_delta_t_k} design`,
        h.worst_delta_t_k === null ? 'bad' : h.worst_delta_t_k > 13 ? 'warn' : ''],
      ['its outlet', h.racks[h.worst_rack].outlet_c === null
        ? '—'
        : `${h.racks[h.worst_rack].outlet_c.toFixed(1)} °C`,
        h.racks[h.worst_rack].over_limit ? 'bad' : ''],
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
