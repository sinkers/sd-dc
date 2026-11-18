// AU01 model review viewer.
//
// Loads the meshopt-compressed GLB written by ../export_glb.py and gives a
// reviewer the four things a static render cannot: orbit around the plant, turn
// a group off to see behind it, cut a section through the building, and click a
// part to get the name it has in FreeCAD.
//
// The GLB carries each part's FreeCAD tree path in node `extras`, so the group
// list on the left is rebuilt from the file rather than configured here. A new
// export with new groups needs no change to this file.

import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';
import { GLTFLoader } from './vendor/GLTFLoader.js';
import { MeshoptDecoder } from './vendor/meshopt_decoder.module.js';

const MODEL = './model/au01.packed.glb';
const MANIFEST = './model/au01.parts.json';

const $ = (id) => document.getElementById(id);

// ---------- scene ----------

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.localClippingEnabled = true;
$('scene').appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x101418);

const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.05, 4000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

// Lighting is deliberately flat and shadowless. This is a dimension-checking
// tool, not a render: a hemisphere fill keeps every face legible, and the two
// directional lights only stop parallel surfaces from merging into one another.
scene.add(new THREE.HemisphereLight(0xdfe8f2, 0x2a3038, 1.5));
const key = new THREE.DirectionalLight(0xffffff, 1.4);
key.position.set(1, 2, 1.5);
scene.add(key);
const fill = new THREE.DirectionalLight(0xbcd0e6, 0.5);
fill.position.set(-1.5, 0.8, -1);
scene.add(fill);

// A horizontal cut, so a reviewer can look inside the halls without hiding
// walls one at a time. Clipping is a render-time plane, so nothing is moved.
const clipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), Infinity);

// ---------- load ----------

const loader = new GLTFLoader();
loader.setMeshoptDecoder(MeshoptDecoder);

let picked = null;
let pickedColour = null;
const HIGHLIGHT = new THREE.Color(0xffb648);
const parts = [];       // { mesh, label, name, path }
const groups = new Map(); // top-level path label -> { parts, visible }

fetch(MANIFEST).then(r => r.ok ? r.json() : null).catch(() => null).then((manifest) => {
  loader.load(MODEL, (gltf) => onLoaded(gltf, manifest), onProgress, (err) => {
    $('loadingText').textContent = 'could not load ' + MODEL + ' — ' + err;
  });
});

function onProgress(event) {
  if (event.total) {
    const pct = Math.round(100 * event.loaded / event.total);
    $('loadingText').textContent = `loading model… ${pct}%`;
  } else {
    $('loadingText').textContent =
      `loading model… ${(event.loaded / 1e6).toFixed(1)} MB`;
  }
}

function onLoaded(gltf, manifest) {
  const root = gltf.scene;
  scene.add(root);

  let triangles = 0;
  const meshSet = new Set();
  root.traverse((node) => {
    if (!node.isMesh) return;
    node.material.clippingPlanes = [clipPlane];
    node.material.clipShadows = true;
    triangles += node.geometry.index
      ? node.geometry.index.count / 3
      : node.geometry.attributes.position.count / 3;
    meshSet.add(node.geometry.uuid);

    // Prefer the label from extras: three.js sanitises glTF node names on load,
    // so `node.name` has every space replaced by an underscore and reads wrong
    // next to the FreeCAD tree.
    const extras = node.userData || {};
    const path = extras.path || [];
    const entry = { mesh: node, label: extras.label || node.name,
                    name: extras.name || node.name, path };
    parts.push(entry);

    const top = path[0] || '(ungrouped)';
    if (!groups.has(top)) groups.set(top, { parts: [], visible: true });
    groups.get(top).parts.push(entry);
  });

  // Frame the model, and give the orbit target something sensible to spin about.
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  const centre = box.getCenter(new THREE.Vector3());
  controls.target.copy(centre);

  // Exposed on purpose, and set before the first setView because that reads it:
  // this is how the export gets checked against the source model from the
  // console, e.g. finding the part that pushes the bounding box wider than
  // FreeCAD says it should be.
  window.__viewer = { THREE, scene, camera, controls, parts, groups, box, size, centre };
  setView('iso');

  const grid = new THREE.GridHelper(Math.ceil(Math.max(size.x, size.z) * 1.4),
                                    40, 0x2a3239, 0x1b2127);
  grid.position.set(centre.x, box.min.y - 0.05, centre.z);
  scene.add(grid);

  $('statParts').textContent = parts.length.toLocaleString();
  $('statMeshes').textContent = meshSet.size.toLocaleString();
  $('statTris').textContent = (triangles / 1e6).toFixed(2) + 'M';
  $('statSize').textContent =
    `${size.x.toFixed(0)} × ${size.z.toFixed(0)} × ${size.y.toFixed(0)} m`;

  if (manifest) {
    $('source').textContent = manifest.source;
    // "drawn" above counts every instance; this is what the file actually holds.
    $('exportNote').textContent =
      `exported ${manifest.exported} · ${manifest.deflection_mm} mm / ` +
      `${manifest.angular_deg}° deflection · ${manifest.instanced_parts} of ` +
      `${manifest.parts} parts instanced · ` +
      `${(manifest.triangles / 1e6).toFixed(2)}M triangles stored`;
  }

  buildGroupList();
  setupClip(box);
  $('loading').style.display = 'none';
}

// ---------- group visibility ----------

function buildGroupList() {
  const host = $('groups');
  const ordered = [...groups.entries()].sort((a, b) => b[1].parts.length - a[1].parts.length);
  for (const [label, group] of ordered) {
    const row = document.createElement('label');
    row.className = 'toggle';
    row.innerHTML =
      `<input type="checkbox" checked><span class="t">${escapeHtml(label)}</span>` +
      `<small>${group.parts.length}</small>`;
    row.querySelector('input').addEventListener('change', (e) => {
      group.visible = e.target.checked;
      for (const part of group.parts) part.mesh.visible = group.visible;
    });
    host.appendChild(row);
  }

  $('allOn').addEventListener('click', () => {
    for (const [, group] of groups) {
      group.visible = true;
      for (const part of group.parts) part.mesh.visible = true;
    }
    for (const box of host.querySelectorAll('input')) box.checked = true;
  });
}

// ---------- search ----------

$('search').addEventListener('input', (e) => {
  const term = e.target.value.trim().toLowerCase();
  if (!term) {
    for (const part of parts) {
      const group = groups.get(part.path[0] || '(ungrouped)');
      part.mesh.visible = !group || group.visible;
    }
    $('hits').textContent = '';
    return;
  }
  let hits = 0;
  for (const part of parts) {
    const match = part.label.toLowerCase().includes(term) ||
                  part.path.join('/').toLowerCase().includes(term);
    part.mesh.visible = match;
    if (match) hits++;
  }
  $('hits').textContent = `${hits} of ${parts.length} parts shown`;
});

// ---------- views ----------

function setView(which) {
  const model = window.__viewer;
  if (!model) return;
  const { size, centre } = model;
  const span = Math.max(size.x, size.y, size.z);
  const distance = span * 1.15;
  const directions = {
    iso: [1, 0.75, 1], top: [0, 1, 0.001], front: [0, 0.15, 1],
    back: [0, 0.15, -1], left: [-1, 0.15, 0], right: [1, 0.15, 0],
  };
  const dir = new THREE.Vector3(...(directions[which] || directions.iso)).normalize();
  camera.position.copy(centre).addScaledVector(dir, distance);
  controls.target.copy(centre);
  controls.update();
}

for (const button of document.querySelectorAll('.views button')) {
  button.addEventListener('click', () => setView(button.dataset.view));
}
$('fit').addEventListener('click', () => setView('iso'));

// ---------- section ----------

function setupClip(box) {
  // The slider spans where the geometry actually is, not the full bounding box.
  // AU01's box runs from -14.7 m to +19 m because a survey formation sits well
  // below grade, so a cut at "30% of the model" landed 4.5 m underground and
  // emptied the screen. Percentiles put the whole travel across the buildings.
  const lows = [], highs = [];
  for (const part of parts) {
    part.mesh.geometry.computeBoundingBox();
    const b = part.mesh.geometry.boundingBox.clone().applyMatrix4(part.mesh.matrixWorld);
    lows.push(b.min.y);
    highs.push(b.max.y);
  }
  lows.sort((a, b) => a - b);
  highs.sort((a, b) => a - b);
  const pick = (sorted, q) => sorted[Math.floor(q * (sorted.length - 1))] ?? 0;
  const ground = pick(lows, 0.05);
  const top = Math.max(pick(highs, 0.98), ground + 1);

  const slider = $('clip');
  const apply = () => {
    const t = slider.value / 100;
    if (t >= 1) {
      clipPlane.constant = Infinity;   // Infinity disables the cut entirely.
      $('clipLabel').textContent = 'cut horizontally to see inside';
    } else {
      const height = ground + t * (top - ground);
      clipPlane.constant = height;
      $('clipLabel').textContent =
        `showing below ${(height - ground).toFixed(1)} m above ground`;
    }
  };
  slider.addEventListener('input', apply);
  $('clipOff').addEventListener('click', () => { slider.value = 100; apply(); });
  apply();
}

// ---------- picking ----------

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let downAt = null;

renderer.domElement.addEventListener('pointerdown', (e) => {
  downAt = { x: e.clientX, y: e.clientY };
});

renderer.domElement.addEventListener('pointerup', (e) => {
  // Only treat it as a pick if the pointer did not travel - otherwise every
  // orbit drag that happens to end on a part would select it.
  if (!downAt || Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 4) return;

  pointer.x = (e.clientX / innerWidth) * 2 - 1;
  pointer.y = -(e.clientY / innerHeight) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);

  const visible = parts.filter(p => p.mesh.visible).map(p => p.mesh);
  const hit = raycaster.intersectObjects(visible, false)[0];
  select(hit ? parts.find(p => p.mesh === hit.object) : null);
});

function select(part) {
  // Materials are shared between instances, so highlighting has to clone the
  // material for the one part rather than paint every copy of it.
  if (picked) {
    picked.mesh.material = pickedColour;
    picked = null;
  }
  if (!part) {
    $('pick').style.display = 'none';
    return;
  }
  pickedColour = part.mesh.material;
  const highlight = part.mesh.material.clone();
  highlight.color = HIGHLIGHT;
  highlight.clippingPlanes = [clipPlane];
  part.mesh.material = highlight;
  picked = part;

  const bbox = new THREE.Box3().setFromObject(part.mesh);
  const size = bbox.getSize(new THREE.Vector3());
  $('pickLabel').textContent = part.label;
  $('pickMeta').innerHTML =
    escapeHtml(part.path.join(' / ') || '(ungrouped)') +
    `<br>${part.name} · ${(size.x * 1000).toFixed(0)} × ` +
    `${(size.z * 1000).toFixed(0)} × ${(size.y * 1000).toFixed(0)} mm`;
  $('pick').style.display = 'block';
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
}

// ---------- loop ----------

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

let frames = 0;
let lastFps = performance.now();
function tick() {
  controls.update();
  renderer.render(scene, camera);
  frames++;
  const now = performance.now();
  if (now - lastFps > 500) {
    $('statFps').textContent = Math.round(frames * 1000 / (now - lastFps));
    frames = 0;
    lastFps = now;
  }
  requestAnimationFrame(tick);
}
tick();
