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
  if (part.group === 'pipe') return manifest.service_colour[part.tag];
  return manifest.kind_colour[part.group] || [0.5, 0.5, 0.5];
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

  fitCamera(min, max);

  buildUI();
  document.getElementById('loading').remove();
  document.getElementById('left').hidden = false;
  document.getElementById('right').hidden = false;
}

/* Frame the whole plant.
 *
 * Fits the eight bounding-box corners projected onto the camera's own right and
 * up axes, rather than fitting the bounding sphere. The sphere is the tidier
 * formula and it wastes the frame here: this plant is 30 x 27 x 4 m, so its
 * sphere is mostly empty air above and below, and fitting that sphere to the
 * narrower field of view left the model floating in a third of the window.
 * Projecting the corners costs a dozen lines and uses the whole viewport. */
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
  // left the model using 57 % of the window. The 1.12 margin already covers the
  // perspective growth; halfD belongs in the near plane, below, and nowhere else.
  const distance = Math.max(halfH / Math.tan(vFov / 2),
                            halfW / Math.tan(hFov / 2)) * 1.22;

  camera.position.copy(dir.clone().multiplyScalar(distance));
  camera.near = Math.max(0.1, distance - halfD * 3);
  camera.far = distance + halfD * 6 + 50;
  camera.updateProjectionMatrix();
  controls.target.set(0, 0, 0);
  controls.minDistance = Math.max(halfW, halfH) * 0.1;
  controls.maxDistance = distance * 3;
  controls.update();
}

/* ---------- UI ---------- */

function buildUI() {
  const order = ['pipe:facility_supply', 'pipe:facility_return',
                 'pipe:tcs_supply', 'pipe:tcs_return', 'valve',
                 'rack', 'cdu', 'chiller'];
  const labels = {
    valve: 'Control valves', rack: 'AI racks', cdu: 'CDUs', chiller: 'HT chillers',
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
    ['CDUs', `${n('cdu')} (3 pods × 3)`],
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
  if (p.group === 'pipe') {
    bits.push(`DN${p.dn} · ${p.length_m} m · ${p.elbows} elbow${p.elbows === 1 ? '' : 's'} · ` +
              `${manifest.services[p.tag].label}`);
    bits.push(`<span style="color:var(--dim)">${p.from} → ${p.to}` +
              (p.valve ? ` · valve ${p.valve}` : '') + `</span>`);
  } else if (p.group === 'valve') {
    bits.push(`Control valve on ${p.on_segment} · DN${p.dn}`);
  }
  if (p.pod !== null && p.pod !== undefined) bits.push(`<span style="color:var(--dim)">Pod ${p.pod + 1}</span>`);
  box.innerHTML = bits.join('<br>');
  box.style.display = 'block';
});

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
