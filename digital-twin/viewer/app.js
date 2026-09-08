// AU01 digital twin — real-time 3D viewer.
//
// Geometry comes from viewer/geometry/{manifest.json,geometry.bin}, packed out of
// the FreeCAD CFD export by prepare_geometry.py with its solid names intact.
// State comes from the same WebSocket the Unreal scene will use, so this doubles
// as a working reference implementation of docs/TELEMETRY.md.
//
// ── About the airflow ─────────────────────────────────────────────────────────
// The streams are NOT a resolved flow field. They are path-following particles
// whose routes are built from the real geometry (each rack's actual intake and
// exhaust faces, each fan wall module's actual discharge face) and whose speed,
// colour and direction are driven by the model's zone-level mass flows. So the
// picture is honest about *how much* air goes *where* and at *what temperature* —
// which is what the model actually knows — without pretending to resolve eddies
// it never solved for. The recirculation streams over the containment are the
// exception worth watching: their direction is the physics the whole model turns
// on, and it is read straight from gap[zone].recirculating.

import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';

const QUERY = new URLSearchParams(location.search);
// Same origin, `/ws` path: works identically on http://localhost and behind TLS,
// and avoids the mixed-content block a hardcoded ws:// port would hit on HTTPS.
const WS_URL = QUERY.get('ws')
  || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;

const TEMP_LO = 18, TEMP_HI = 50;      // colour ramp range, °C
const PARTICLES_PER_RACK = 190;
const PARTICLES_PER_RECIRC = 150;

// ── temperature colour ramp ──────────────────────────────────────────────────
// Perceptually ordered cool→hot, dark enough at the cold end to read against the
// dark scene, and with a distinct step at the top so an over-limit rack is
// obvious rather than "slightly more orange".
const RAMP = [
  [0.00, 0x1b3fa0], [0.18, 0x1f8fd0], [0.36, 0x35d2c2],
  [0.54, 0xc8e05a], [0.72, 0xffa32e], [0.88, 0xff4d3d], [1.00, 0xb3122a],
];
const _c1 = new THREE.Color(), _c2 = new THREE.Color();
function tempColor(c, target = new THREE.Color()) {
  const t = Math.min(1, Math.max(0, (c - TEMP_LO) / (TEMP_HI - TEMP_LO)));
  for (let i = 1; i < RAMP.length; i++) {
    if (t <= RAMP[i][0]) {
      const [p0, h0] = RAMP[i - 1], [p1, h1] = RAMP[i];
      const f = (t - p0) / (p1 - p0 || 1);
      return target.copy(_c1.setHex(h0)).lerp(_c2.setHex(h1), f);
    }
  }
  return target.setHex(RAMP[RAMP.length - 1][1]);
}

// ── scene ────────────────────────────────────────────────────────────────────
const container = document.getElementById('scene');

// A machine without a usable GPU (a headless CI browser, a VM with software
// rendering) fails here, and three.js only logs to the console. Say so on the
// page instead — an unexplained black screen is the worst possible failure mode.
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true });
} catch (err) {
  document.getElementById('loading').innerHTML =
    '<b style="color:#ff4d5e">WebGL unavailable</b><br><br>'
    + 'This machine cannot create a WebGL context, so the 3D scene cannot render.'
    + '<br>Try a browser with hardware acceleration enabled.'
    + `<br><br><span style="font-size:11px">${err}</span>`;
  throw err;
}
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.setClearColor(0x0b0e13);
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.Fog(0x0b0e13, 34, 78);

// The model is Z-up (matching the CFD and cfd_export_params.json). Rather than
// rotating the geometry, tell the camera which way is up — so every coordinate
// in this file is directly comparable to the CFD's.
const camera = new THREE.PerspectiveCamera(48, innerWidth / innerHeight, 0.1, 400);
camera.up.set(0, 0, 1);
camera.position.set(30, -19, 13);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI * 0.52;

scene.add(new THREE.HemisphereLight(0x8fb4ff, 0x0a0d12, 0.65));
const key = new THREE.DirectionalLight(0xffffff, 1.15);
key.position.set(14, -22, 26);
scene.add(key);
const fill = new THREE.DirectionalLight(0x88aaff, 0.35);
fill.position.set(-18, 14, 8);
scene.add(fill);

const groups = {};   // render group -> THREE.Group
const rackMeshes = {};  // telemetry key -> mesh
let manifest = null;

// ── materials by group ───────────────────────────────────────────────────────
const MATERIALS = {
  shell: () => new THREE.MeshStandardMaterial({
    color: 0x2a3340, roughness: 0.92, metalness: 0.05,
    transparent: true, opacity: 0.20, side: THREE.DoubleSide, depthWrite: false,
  }),
  racks: () => new THREE.MeshStandardMaterial({
    color: 0x39424f, roughness: 0.55, metalness: 0.45,
  }),
  fanwalls: () => new THREE.MeshStandardMaterial({
    color: 0x4a5566, roughness: 0.4, metalness: 0.6,
  }),
  hac: () => new THREE.MeshStandardMaterial({
    color: 0x6d7a8c, roughness: 0.5, metalness: 0.2,
    transparent: true, opacity: 0.30, side: THREE.DoubleSide,
  }),
  bulkheads: () => new THREE.MeshStandardMaterial({
    color: 0x55606f, roughness: 0.7, transparent: true, opacity: 0.35,
    side: THREE.DoubleSide,
  }),
  gantry: () => new THREE.MeshStandardMaterial({
    color: 0x515b6b, roughness: 0.65, metalness: 0.5,
  }),
  supply_faces: () => new THREE.MeshBasicMaterial({
    color: 0x39b8ff, transparent: true, opacity: 0.5, side: THREE.DoubleSide,
  }),
  intake_faces: () => new THREE.MeshBasicMaterial({
    color: 0xff7a4d, transparent: true, opacity: 0.35, side: THREE.DoubleSide,
  }),
  rack_intake_faces: () => new THREE.MeshBasicMaterial({
    color: 0x39b8ff, transparent: true, opacity: 0.22, side: THREE.DoubleSide,
  }),
  rack_exhaust_faces: () => new THREE.MeshBasicMaterial({
    color: 0xff5a3c, transparent: true, opacity: 0.22, side: THREE.DoubleSide,
  }),
};

async function loadGeometry() {
  const [mf, bin] = await Promise.all([
    fetch('./geometry/manifest.json').then(r => r.json()),
    fetch('./geometry/geometry.bin').then(r => r.arrayBuffer()),
  ]);
  manifest = mf;
  const floats = new Float32Array(bin);

  for (const part of mf.parts) {
    const g = groups[part.group] || (groups[part.group] = new THREE.Group());
    if (!g.parent) scene.add(g);

    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(
      floats.subarray(part.offset, part.offset + part.floats), 3));
    geom.computeVertexNormals();

    const mat = (MATERIALS[part.group] || MATERIALS.racks)();
    const mesh = new THREE.Mesh(geom, mat);
    mesh.name = part.name;
    g.add(mesh);

    if (part.group === 'racks') {
      const k = part.name.replace(/^rack_/, '').split('-')[0];
      mesh.material = mesh.material.clone();
      mesh.material.vertexColors = true;
      // Shade each cabinet as a vertical gradient from its mean intake at the
      // floor to its worst face peak at the top. Hot spots in this hall are a
      // top-of-rack phenomenon (the CFD's inletTmax channels sit well above the
      // mean), so a single flat colour per rack hides exactly the thing that
      // decides the verdict. `height` is each vertex's normalised height, cached
      // once so the per-frame recolour is a straight lerp.
      const pos = geom.getAttribute('position');
      const zs = [];
      for (let v = 0; v < pos.count; v++) zs.push(pos.getZ(v));
      const zlo = Math.min(...zs), zhi = Math.max(...zs);
      const span = Math.max(zhi - zlo, 1e-6);
      mesh.userData.height = zs.map(z => (z - zlo) / span);
      geom.setAttribute('color', new THREE.BufferAttribute(
        new Float32Array(pos.count * 3), 3));
      rackMeshes[k] = mesh;
      // 600 mm cabinets on a 610 mm pitch merge into one slab without edges;
      // outlining each one is what makes it read as a row of 12 racks.
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geom, 1),
        new THREE.LineBasicMaterial({
          color: 0x0a0d12, transparent: true, opacity: 0.75,
        }));
      g.add(edges);
    }
  }

  // Centre the orbit on the pod, not the room origin.
  const ha = mf.hot_aisle;
  controls.target.set((ha.x[0] + ha.x[1]) / 2, (ha.y[0] + ha.y[1]) / 2, 1.4);
  // Frame the pod from a low three-quarter angle: close enough that the airflow
  // around individual cabinets is legible, which is the point of the view.
  camera.position.set(ha.x[1] + 5.5, ha.y[0] - 9.5, 5.2);
  controls.update();

  // A floor grid gives the eye a ground plane the translucent shell cannot.
  const grid = new THREE.GridHelper(56, 56, 0x1b2430, 0x141b25);
  grid.rotation.x = Math.PI / 2;
  grid.position.set(mf.room.x[1] / 2, mf.room.y[1] / 2, 0.004);
  scene.add(grid);
  groups.grid = grid;

  // Default visibility: the measurement faces are diagnostics, off to start.
  for (const k of ['supply_faces', 'intake_faces', 'rack_intake_faces',
                   'rack_exhaust_faces']) {
    if (groups[k]) groups[k].visible = false;
  }
}

// ── airflow streams ──────────────────────────────────────────────────────────
// Each particle follows a polyline route. Routes are built once from geometry;
// speed and colour are refreshed from every telemetry frame.
//
// A rack's route:  module supply face → cold aisle → rack intake → rack exhaust
//                  → up the open-top hot aisle → along to the return → module intake
// A recirculation route: hot aisle top → over the containment → down to a rack
//                  intake. Only active while that zone is actually recirculating.

const jitter = (a) => (Math.random() - 0.5) * a;

let _sprite = null;
function softSprite() {
  if (_sprite) return _sprite;
  const s = 64, cv = document.createElement('canvas');
  cv.width = cv.height = s;
  const cx = cv.getContext('2d');
  const g = cx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.35, 'rgba(255,255,255,0.55)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  cx.fillStyle = g;
  cx.fillRect(0, 0, s, s);
  _sprite = new THREE.CanvasTexture(cv);
  return _sprite;
}

function faceSample(face) {
  // random point on a planar face, using its extents
  const e = face.extent;
  return [
    face.centre[0] + jitter(e[0]),
    face.centre[1] + jitter(e[1]),
    face.centre[2] + jitter(e[2]),
  ];
}

// Fractions used to split the exhaust between the two ways out of an OPEN-TOP
// hot aisle. This is a VISUALISATION ASSUMPTION, not a result: no CFD of the
// AU01 open-top scheme has been run, and the ROM treats the hot aisle as one
// well-mixed node with no internal geometry, so it cannot tell you the split.
// The open top is 1.8 x 7.32 = 13.2 m2 against 2 x 3.5 m2 of baffle-channel end,
// so most of it going up is the physically plausible default.
const OVER_THE_TOP_FRACTION = 0.68;

class Streams {
  constructor(mf) {
    this.mf = mf;
    this.bulkheadTop = 3.0;   // as-drawn h3000; the viewer can drop it
    this.routes = [];
    this.build();

    const n = this.routes.length;
    this.pos = new Float32Array(n * 3);
    this.col = new Float32Array(n * 3);
    this.u = new Float32Array(n);
    this.speed = new Float32Array(n);
    this.alpha = new Float32Array(n);
    for (let i = 0; i < n; i++) this.u[i] = Math.random();

    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    geom.setAttribute('color', new THREE.BufferAttribute(this.col, 3));
    this.points = new THREE.Points(geom, new THREE.PointsMaterial({
      // A soft round sprite rather than square pixels: at hall scale the
      // particles are only a few pixels across, and hard squares read as noise
      // while soft blobs read as moving air.
      map: softSprite(),
      size: 0.30, vertexColors: true, transparent: true, opacity: 0.85,
      sizeAttenuation: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    }));
    // Inactive particles are parked far below the floor rather than deleted, so
    // the geometry's bounding sphere is meaningless and three.js would frustum-cull
    // the entire system. Particle positions change every frame anyway, so there is
    // nothing useful to cull against.
    this.points.frustumCulled = false;
    scene.add(this.points);
    groups.airflow = this.points;
  }

  // Which end of the hall a rack sits nearer. Used as a *preference* only: the
  // actual feeding module is chosen per frame from whatever is running.
  endFor(rackKey) {
    return parseInt(rackKey.slice(1), 10) <= 6 ? 'west' : 'east';
  }

  build() {
    const mf = this.mf;
    const ha = mf.hot_aisle;
    const aisleY = (ha.y[0] + ha.y[1]) / 2;
    const baffleTop = ha.baffle_z[1];
    const roomY = mf.room.y;

    for (const [key, rack] of Object.entries(mf.racks)) {
      if (!rack.intake || !rack.exhaust) continue;
      const end = this.endFor(key);
      const pos = parseInt(key.slice(1), 10);
      const zone = `cold_${rack.row}_${pos <= 6 ? 'west' : 'east'}`;
      const inN = rack.intake.normal, exN = rack.exhaust.normal;

      // Which end of the baffled channel this rack's exhaust heads for.
      const nearEndX = Math.abs(rack.exhaust.centre[0] - ha.x[0]) <
                       Math.abs(rack.exhaust.centre[0] - ha.x[1]) ? ha.x[0] : ha.x[1];

      for (let p = 0; p < PARTICLES_PER_RACK; p++) {
        const i = faceSample(rack.intake);
        const e = faceSample(rack.exhaust);

        // Cold side: the discharge fans out across the FULL width of the room to
        // reach both side aisles, not just the width of the unit's own face.
        const aisleEntry = [
          this.mf.modules[end === 'west' ? 'W1' : 'E1'].supply.centre[0]
            + (end === 'west' ? 1.6 : -1.6) + jitter(1.2),
          i[1] + inN[1] * (0.5 + Math.random() * 1.2),
          0.4 + Math.random() * 2.4,
        ];
        const approach = [i[0] + jitter(0.5), i[1] + inN[1] * 0.9, i[2]];

        // Hot side: rise inside the aisle, then leave either over the open top or
        // through the open end of the baffled channel.
        const overTop = Math.random() < OVER_THE_TOP_FRACTION;
        const rise = [
          e[0] + jitter(0.3),
          aisleY + jitter(1.2),
          overTop ? baffleTop + 0.10 + Math.random() * 0.25
                  : 2.3 + Math.random() * 1.5,
        ];
        const exit = overTop
          // straight up and out of the open top, then drifting toward the end
          ? [e[0] + (nearEndX - e[0]) * (0.25 + Math.random() * 0.35),
             aisleY + jitter(1.6),
             baffleTop + 0.35 + Math.random() * 0.35]
          // out through the channel end, above the 2 m end doors
          : [nearEndX + (nearEndX < e[0] ? -0.4 : 0.4),
             aisleY + jitter(1.4),
             2.3 + Math.random() * 1.5];

        // Crossing the room back toward the fan wall, spread over the full width.
        const traverse = [
          nearEndX + (end === 'west' ? -2.2 : 2.2) + jitter(1.4),
          roomY[0] + 0.4 + Math.random() * (roomY[1] - roomY[0] - 0.8),
          2.6 + Math.random() * 1.3,
        ];

        this.routes.push({
          rack: key, kind: 'through', zone, end,
          // where this particle sits on the fan wall face, kept stable so the
          // stream does not shimmer when the feeding module changes
          jit: [jitter(3.6), jitter(1.7)],
          slot: Math.random(),           // resolved against the open areas later
          mid: [aisleEntry, approach, i, e, rise, exit, traverse],
          _module: null, pts: null,
          coldUntil: 3, hotFrom: 4,
        });
      }
    }

    // Recirculation / spill over the open containment top, per zone.
    for (const [key, rack] of Object.entries(mf.racks)) {
      if (!rack.intake || !rack.exhaust) continue;
      const pos = parseInt(key.slice(1), 10);
      const zone = `cold_${rack.row}_${pos <= 6 ? 'west' : 'east'}`;
      const inN = rack.intake.normal;
      const n = Math.round(PARTICLES_PER_RECIRC / 12);
      for (let p = 0; p < n; p++) {
        const i = faceSample(rack.intake);
        const overTop = [i[0] + jitter(0.4), rack.exhaust.centre[1], baffleTop + 0.15];
        const descend = [i[0] + jitter(0.4), i[1] + inN[1] * 1.1, baffleTop - 1.0];
        this.routes.push({
          rack: key, kind: 'recirc', zone, end: this.endFor(key),
          jit: [0, 0], slot: 0,
          mid: [overTop, descend, [i[0], i[1] + inN[1] * 0.25, i[2] + 0.35]],
          _module: null, pts: null,
          coldUntil: -1, hotFrom: 0,
        });
      }
    }
  }

  // Build the full polyline for a route, given which module is feeding it.
  //
  // The return leg is the part worth reading carefully. The unit is a solid block
  // 4 m tall (x 2.0-3.6 west) with its intake on the REAR face, and bulkheads seal
  // the 2.1 m side passages up to `bulkheadTop`. So return air cannot go straight
  // to the intake - it has to get over something first, then down into the rear
  // corridor and forward into the unit. Three ways through, and a particle takes
  // the one its `slot` value lands in, weighted by the actual open areas:
  //
  //   * over a bulkhead side slot (south or north), above `bulkheadTop`
  //   * over the top of the unit itself, through the gable space above 4 m
  //
  // Those add up to the ~7.8 m2 the as-drawn h3000 design quotes. Dropping the
  // bulkheads enlarges the side slots, which is why the split is recomputed
  // whenever `bulkheadTop` changes.
  assemble(r, moduleName) {
    const mf = this.mf;
    const m = mf.modules[moduleName];
    const body = mf.fanwall_bodies[r.end];
    const west = r.end === 'west';
    const roomY = mf.room.y;
    const eave = mf.room.eave;

    const supplyPt = [
      m.supply.centre[0],
      m.supply.centre[1] + r.jit[0] / 2,
      Math.max(0.25, m.supply.centre[2] + r.jit[1] / 2),
    ];
    const intakePt = [
      m.intake.centre[0],
      m.intake.centre[1] + r.jit[0] / 2,
      Math.max(0.25, m.intake.centre[2] + r.jit[1] / 2),
    ];

    if (r.kind === 'recirc') {
      r.pts = r.mid;
      r._module = moduleName;
      return;
    }

    // Open areas of the three return routes, so the particle split matches the
    // geometry rather than being picked by eye.
    const sideW = 2.1;                                   // each side passage
    const sideH = Math.max(0.05, (eave + 0.35) - this.bulkheadTop);
    const overH = Math.max(0.05, (eave + 0.6) - body.max[2]);
    const aSide = sideW * sideH, aOver = (body.max[1] - body.min[1]) * overH;
    const total = 2 * aSide + aOver;
    const t = r.slot * total;

    let cross;
    if (t < aSide) {
      // south side slot, over the bulkhead
      cross = [
        body.max[0] + (west ? 0.1 : -0.1),
        roomY[0] + 0.25 + Math.random() * (body.min[1] - roomY[0] - 0.5),
        this.bulkheadTop + 0.15 + Math.random() * Math.max(0.1, sideH - 0.3),
      ];
    } else if (t < 2 * aSide) {
      // north side slot
      cross = [
        body.max[0] + (west ? 0.1 : -0.1),
        body.max[1] + 0.25 + Math.random() * (roomY[1] - body.max[1] - 0.5),
        this.bulkheadTop + 0.15 + Math.random() * Math.max(0.1, sideH - 0.3),
      ];
    } else {
      // over the top of the unit, through the gable space
      cross = [
        (body.min[0] + body.max[0]) / 2,
        body.min[1] + 0.3 + Math.random() * (body.max[1] - body.min[1] - 0.6),
        body.max[2] + 0.12 + Math.random() * Math.max(0.1, overH - 0.25),
      ];
    }

    // Down into the rear corridor behind the unit, then forward into the intake.
    const corridorX = west ? Math.max(0.35, body.min[0] - 1.0)
                           : Math.min(mf.room.x[1] - 0.35, body.max[0] + 1.0);
    const corridor = [corridorX, intakePt[1], intakePt[2] + 0.7 + Math.random() * 0.9];

    r.pts = [supplyPt, ...r.mid, cross, corridor, intakePt];
    r._module = moduleName;
    // colour stage boundaries shift because the supply leg gained a point
    r.coldUntil = 4;
    r.hotFrom = 5;
  }

  // Choose the module feeding a rack this frame. Prefer the near end, but ANY
  // running module keeps every rack breathing - which is the whole point of the
  // fan wall being a bank. Tying a rack to one module meant half the row went
  // visually dead when a single module tripped, which the model never said.
  pickModule(frame, r) {
    const running = Object.entries(frame.supply)
      .filter(([, u]) => u.on && u.flow_m3h > 1)
      .map(([name]) => name);
    if (!running.length) return null;
    const near = running.filter(n => this.mf.modules[n]?.end === r.end);
    const pool = near.length ? near : running;
    // keep the current choice if it is still valid, to avoid flicker
    if (r._module && pool.includes(r._module)) return r._module;
    return pool[Math.floor(Math.random() * pool.length)];
  }

  setBulkheadTop(z) {
    if (Math.abs(z - this.bulkheadTop) < 1e-6) return;
    this.bulkheadTop = z;
    for (const r of this.routes) r._module = null;   // force reassembly
  }

  update(frame) {
    const supplyT = avg(Object.values(frame.supply).map(u => u.t_supply));
    const hotT = frame.hot_aisle;

    for (let i = 0; i < this.routes.length; i++) {
      const r = this.routes[i];
      const rack = frame.racks[r.rack];
      if (!rack) { this.alpha[i] = 0; continue; }

      if (r.kind === 'through') {
        const mod = this.pickModule(frame, r);
        const live = mod !== null && rack.flow_m3h > 1;
        this.alpha[i] = live ? 1 : 0;
        if (live && (r._module !== mod || !r.pts)) this.assemble(r, mod);
        this.speed[i] = live ? 0.005 + 0.008 * Math.min(1.6, rack.flow_m3h / 7000) : 0;
      } else {
        const gap = frame.gap[r.zone];
        const on = gap && gap.recirculating;
        this.alpha[i] = on ? 1 : 0;
        if (on && !r.pts) this.assemble(r, 'W1');
        this.speed[i] = on
          ? 0.010 + 0.030 * Math.min(1, Math.abs(gap.net_m3h) / 25000)
          : 0;
      }
      r._supplyT = supplyT; r._exhaustT = rack.t_out; r._intakeT = rack.t_in;
      r._hotT = hotT;
    }
  }

  step(dt) {
    const n = this.routes.length;
    const c = new THREE.Color();
    for (let i = 0; i < n; i++) {
      const r = this.routes[i];
      if (this.alpha[i] === 0 || !r.pts) {
        this.pos[i * 3 + 2] = -999;
        continue;
      }
      this.u[i] += this.speed[i] * dt * 60;
      if (this.u[i] > 1) this.u[i] -= 1;

      const segs = r.pts.length - 1;
      const f = this.u[i] * segs;
      const s = Math.min(segs - 1, Math.floor(f));
      const lf = f - s;
      const a = r.pts[s], b = r.pts[s + 1];
      const j = i * 3;
      this.pos[j] = a[0] + (b[0] - a[0]) * lf;
      this.pos[j + 1] = a[1] + (b[1] - a[1]) * lf;
      this.pos[j + 2] = a[2] + (b[2] - a[2]) * lf;

      let temp;
      if (r.kind === 'recirc') {
        temp = r._exhaustT;
      } else if (s < r.coldUntil) {
        temp = r._supplyT;
      } else if (s < r.hotFrom) {
        temp = r._intakeT + (r._exhaustT - r._intakeT) * lf;
      } else {
        temp = r._exhaustT;
      }
      tempColor(temp ?? 28, c);
      this.col[j] = c.r; this.col[j + 1] = c.g; this.col[j + 2] = c.b;
    }
    this.points.geometry.attributes.position.needsUpdate = true;
    this.points.geometry.attributes.color.needsUpdate = true;
  }
}

const avg = (xs) => xs.reduce((a, b) => a + b, 0) / (xs.length || 1);

// ── telemetry ────────────────────────────────────────────────────────────────
let streams = null, hello = null, latest = null, ws = null;

function connect() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => { document.getElementById('disconnected').style.display = 'none'; };
  ws.onclose = () => {
    document.getElementById('disconnected').style.display = 'block';
    setTimeout(connect, 1200);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'hello') { hello = msg; buildControls(msg); }
    else if (msg.type === 'state') { latest = msg; applyFrame(msg); }
    else if (msg.type === 'err') console.warn('solver:', msg.reason);
  };
}
function send(cmd) {
  if (!ws || ws.readyState !== 1) return;
  if (cmd._fan !== undefined) {
    for (const m of hello?.modules || [])
      ws.send(JSON.stringify({
        type: 'cmd', cmd: 'set_unit_airflow', unit: m.name, fraction: cmd._fan,
      }));
    return;
  }
  ws.send(JSON.stringify({ type: 'cmd', ...cmd }));
}

const _cLo = new THREE.Color(), _cHi = new THREE.Color(), _cMix = new THREE.Color();

function applyFrame(f) {
  for (const [k, mesh] of Object.entries(rackMeshes)) {
    const r = f.racks[k];
    if (!r) continue;
    const attr = mesh.geometry.getAttribute('color');
    const h = mesh.userData.height;

    if (r.kw <= 0) {
      // An empty cabinet position has an air temperature but nothing to protect,
      // so render it as inert rather than colouring it like a hot rack.
      mesh.material.emissive.setHex(0x000000);
      for (let v = 0; v < attr.count; v++) attr.setXYZ(v, 0.14, 0.16, 0.20);
      attr.needsUpdate = true;
      continue;
    }

    tempColor(r.t_in, _cLo);         // floor: mean intake
    tempColor(r.t_in_peak, _cHi);    // top: worst face peak
    for (let v = 0; v < attr.count; v++) {
      _cMix.copy(_cLo).lerp(_cHi, h[v]);
      attr.setXYZ(v, _cMix.r * 0.85, _cMix.g * 0.85, _cMix.b * 0.85);
    }
    attr.needsUpdate = true;

    // A uniform emissive keyed to the peak makes an over-limit rack glow from
    // the top, which is where the problem actually is.
    mesh.material.emissive.copy(_cHi).multiplyScalar(
      r.status === 'over_allowable' ? 0.45 : r.status === 'over_recommended' ? 0.16 : 0.07);
  }
  if (streams) streams.update(f);
  updateHud(f);
  if (manifest) applyBulkheadTop(streams?.bulkheadTop ?? AS_DRAWN_BULKHEAD_TOP);
}

// ── HUD ──────────────────────────────────────────────────────────────────────
function buildControls(h) {
  const units = document.getElementById('units');
  units.innerHTML = '';
  for (const m of h.modules) {
    const b = document.createElement('button');
    b.textContent = m.name;
    b.dataset.unit = m.name;
    b.onclick = () => send({ cmd: 'set_unit', unit: m.name, on: b.classList.contains('off') });
    units.appendChild(b);
  }
  const tg = document.getElementById('toggles');
  tg.innerHTML = '';
  const items = [
    ['airflow', 'airflow'], ['racks', 'racks'], ['shell', 'shell'],
    ['gantry', 'gantry'], ['hac', 'containment'], ['bulkheads', 'bulkheads'],
    ['fanwalls', 'fan walls'], ['rack_intake_faces', 'intake faces'],
    ['rack_exhaust_faces', 'exhaust faces'], ['grid', 'grid'],
  ];
  for (const [k, label] of items) {
    const b = document.createElement('button');
    b.textContent = label;
    const obj = groups[k];
    if (obj && obj.visible) b.classList.add('on');
    b.onclick = () => {
      const o = groups[k];
      if (!o) return;
      o.visible = !o.visible;
      b.classList.toggle('on', o.visible);
    };
    tg.appendChild(b);
  }
  document.getElementById('ramp-lo').textContent = TEMP_LO;
  document.getElementById('ramp-hi').textContent = `${TEMP_HI} °C`;
}

function updateHud(f) {
  const v = document.getElementById('verdict');
  v.className = `panel v-${f.verdict}`;
  document.getElementById('v-text').textContent = f.verdict;
  document.getElementById('v-why').textContent = f.verdict_reason;

  for (const b of document.querySelectorAll('#mode button'))
    b.classList.toggle('on', b.dataset.mode === f.mode);

  // In auto mode the profile owns the B300 load, so show what those racks are
  // actually running at rather than a stale setpoint.
  const b300 = (hello?.racks || [])
    .filter(r => r.class === 'b300')
    .map(r => f.racks[r.name]?.kw)
    .filter(v => v !== undefined);
  sliders.load?.(f.mode === 'auto' && b300.length
    ? Math.round(avg(b300) * 4) / 4
    : f.b300_setpoint_kw);
  sliders.supply?.(f.supply_setpoint_c);
  sliders.speed?.(f.speed);
  const on = Object.values(f.supply).filter(u => u.on);
  if (on.length) sliders.fan?.(Math.round(avg(on.map(u => u.airflow_fraction)) * 100));
  document.getElementById('phase').textContent = f.profile
    ? `${f.profile.phase} · ${Math.round(f.profile.mean_utilisation * 100)}% util`
    + (f.profile.straggler ? ` · straggler ${f.profile.straggler}` : '')
    : 'manual';

  for (const b of document.querySelectorAll('#units button')) {
    const u = f.supply[b.dataset.unit];
    b.classList.toggle('off', !u.on);
    b.classList.toggle('sat', !!u.saturated);
    b.title = `${u.t_supply.toFixed(1)} °C · ${Math.round(u.flow_m3h).toLocaleString()} m³/h`
      + ` · ${u.duty_kw.toFixed(0)}/${u.capacity_kw} kW${u.saturated ? ' · SATURATED' : ''}`;
  }

  const t = f.totals;
  const recirc = Object.entries(f.gap).filter(([, g]) => g.recirculating).map(([z]) => z.replace('cold_', ''));
  document.getElementById('stats-body').innerHTML = `
    <tr><td>IT load</td><td>${t.it_kw.toFixed(1)} kW</td></tr>
    <tr><td>cooling duty</td><td>${t.cooling_kw.toFixed(1)} kW</td></tr>
    <tr><td>into thermal mass</td><td>${t.storage_kw >= 0 ? '+' : ''}${t.storage_kw.toFixed(1)} kW</td></tr>
    <tr><td>supply air</td><td>${avg(Object.values(f.supply).map(u => u.t_supply)).toFixed(1)} °C</td></tr>
    <tr><td>hot aisle</td><td>${f.hot_aisle.toFixed(1)} °C</td></tr>
    <tr><td>return air</td><td>${f.return_air.toFixed(1)} °C</td></tr>
    <tr><td>worst rack</td><td>${t.worst_rack} @ ${t.worst_t_in.toFixed(2)} °C</td></tr>
    <tr><td>worst face peak</td><td>${t.worst_t_in_peak.toFixed(2)} °C</td></tr>
    <tr><td>supply / demand</td><td style="color:${t.supply_m3h >= t.rack_m3h ? 'var(--pass)' : 'var(--fail)'}">${(t.supply_m3h / Math.max(t.rack_m3h, 1) * 100).toFixed(0)} %</td></tr>
    <tr><td>fan power (cube law)</td><td>${(Math.pow(avg(Object.values(f.supply).filter(u => u.on).map(u => u.airflow_fraction)) || 0, 3) * 100).toFixed(0)} % of full</td></tr>
    <tr><td>recirculating</td><td style="color:${recirc.length ? 'var(--fail)' : 'var(--pass)'}">${recirc.length ? recirc.join(' ') : 'none'}</td></tr>
    <tr><td>sim time</td><td>${Math.floor(f.t_sim / 60)}m ${Math.round(f.t_sim % 60)}s · ${f.speed}×</td></tr>`;

  const rows = [];
  for (const [k, r] of Object.entries(f.racks)) {
    const cls = r.kw <= 0 ? 'spare'
      : r.status === 'over_allowable' ? 'hot'
      : r.status === 'over_recommended' ? 'warm' : '';
    rows.push(`<tr class="${cls}"><td>${k}</td><td>${r.kw.toFixed(1)}</td>`
      + `<td>${r.t_in.toFixed(1)}</td><td>${r.t_in_peak.toFixed(1)}</td>`
      + `<td>${r.kw > 0 ? r.t_out.toFixed(1) : '—'}</td>`
      + `<td>${(r.recirc * 100).toFixed(0)}%</td></tr>`);
  }
  document.getElementById('racks-body').innerHTML = rows.join('');
}

// control wiring
document.querySelectorAll('#mode button').forEach(b => {
  b.onclick = () => send({ cmd: 'set_mode', mode: b.dataset.mode });
});

// ── bulkhead height ──────────────────────────────────────────────────────────
// The bulkheads seal the 2.1 m passages either side of each fan wall unit, so the
// only way return air reaches the rear intakes is over them, or over the top of
// the unit itself. That total open area is the design's return-path bottleneck:
// the as-drawn h3000 quotes ~7.8 m2 and ~2.6 m/s, doubling to ~5.2 m/s on a
// single slot in N-1.
//
// IMPORTANT: this control changes the geometry and the airflow routing only. The
// ROM has ONE lumped return node with no pressure drop, so lowering the
// bulkheads does not and cannot change any temperature the twin reports. It is a
// static-pressure question, and answering it needs the CFD (case-au01 already
// takes `bulkhead h3000|h4000` as a scenario knob). The area and velocity shown
// here are computed from the geometry, which is a real answer to a real question
// — just not one the thermal model contributes to.
const AS_DRAWN_BULKHEAD_TOP = 3.0;

function returnSlotArea(top) {
  const mf = manifest;
  if (!mf) return null;
  const body = mf.fanwall_bodies.west;
  const roomY = mf.room.y, eave = mf.room.eave;
  // Roof rises from the eave at the walls to the apex over the ridge; approximate
  // each opening by its mean height.
  const sideMeanRoof = eave + 0.5 * (mf.room.apex - eave) * 0.5;
  const sideW = body.min[1] - roomY[0];              // 2.1 m each side
  const sideH = Math.max(0, sideMeanRoof - top);
  const overW = body.max[1] - body.min[1];
  const overH = Math.max(0, mf.room.apex - 0.15 - body.max[2]);
  return { area: 2 * sideW * sideH + overW * overH, sideH, overH };
}

function applyBulkheadTop(top) {
  if (groups.bulkheads) {
    // The panels run from the floor to 3.0 m, so scaling z about the world origin
    // lowers the top edge without moving the base.
    groups.bulkheads.scale.z = top / AS_DRAWN_BULKHEAD_TOP;
  }
  streams?.setBulkheadTop(top);
  for (const b of document.querySelectorAll('#bulkhead button'))
    b.classList.toggle('on', parseFloat(b.dataset.top) === top);

  const s = returnSlotArea(top);
  const el = document.getElementById('slot-out');
  if (!s || !latest) { if (el) el.textContent = '—'; return; }
  // Velocity through the slot at whatever the fans are currently moving. Note
  // this is NOT the design sheet's ~2.6 m/s: that figure is at the racks' airflow
  // demand (~151,000 m3/h), while the fan wall is sized at 260,000 m3/h, so at
  // full fan speed the slot sees considerably more. Both are correct answers to
  // different questions; the label says which one this is.
  const runningEnds = new Set(
    Object.entries(latest.supply).filter(([, u]) => u.on)
      .map(([n]) => manifest.modules[n]?.end).filter(Boolean));
  const m3h = Object.values(latest.supply)
    .filter(u => u.on).reduce((a, u) => a + u.flow_m3h, 0);
  const ends = Math.max(runningEnds.size, 1);
  const v = (m3h / ends) / 3600 / Math.max(s.area, 1e-6);
  const base = returnSlotArea(AS_DRAWN_BULKHEAD_TOP);
  const delta = base && Math.abs(top - AS_DRAWN_BULKHEAD_TOP) > 1e-6
    ? ` (${((s.area / base.area - 1) * 100).toFixed(0)}% area)` : '';
  el.textContent = `${s.area.toFixed(1)} m² · ${v.toFixed(1)} m/s at fan flow${delta}`;
}

document.querySelectorAll('#bulkhead button').forEach(b => {
  b.onclick = () => applyBulkheadTop(parseFloat(b.dataset.top));
});
const sliders = {};
const bind = (id, out, fmt, cmd) => {
  const el = document.getElementById(id), o = document.getElementById(out);
  const show = () => { o.textContent = fmt(parseFloat(el.value)); };
  let dragging = false;
  el.addEventListener('pointerdown', () => { dragging = true; });
  addEventListener('pointerup', () => { dragging = false; });
  el.oninput = show;
  el.onchange = () => { show(); send(cmd(parseFloat(el.value))); };
  show();
  // Reflect the twin's actual value, so the HUD cannot drift away from what the
  // solver is doing (e.g. after another client issues a command, or in auto mode
  // where the profile owns the load). Never fight the user mid-drag.
  sliders[id] = (value) => {
    if (dragging || document.activeElement === el) return;
    if (Math.abs(parseFloat(el.value) - value) < 1e-6) return;
    el.value = value;
    show();
  };
};
bind('load', 'load-out', v => `${v.toFixed(2)} kW`, v => ({ cmd: 'set_load', target: 'global', kw: v }));
// Fan speed is a VFD turndown applied to every running module. This is the one
// control whose effect runs entirely through the gap closure: turning the fans
// down shrinks the supply until it no longer covers what the racks draw, and the
// shortfall arrives as hot recirculation. AU01 delivers ~142% of rack demand at
// full speed, so there is real turndown headroom before the gap flow reverses —
// and fan power follows roughly the cube of speed, so the headroom is worth money.
bind('fan', 'fan-out', v => `${v.toFixed(0)} %`, v => ({ _fan: v / 100 }));
bind('supply', 'supply-out', v => `${v.toFixed(1)} °C`, v => ({ cmd: 'set_supply_temp', celsius: v }));
bind('speed', 'speed-out', v => `${v}×`, v => ({ cmd: 'set_speed', x: v }));

// legend ramp
{
  const cv = document.getElementById('ramp'), cx = cv.getContext('2d');
  const c = new THREE.Color();
  for (let x = 0; x < cv.width; x++) {
    tempColor(TEMP_LO + (TEMP_HI - TEMP_LO) * (x / cv.width), c);
    cx.fillStyle = `#${c.getHexString()}`;
    cx.fillRect(x, 0, 1, cv.height);
  }
}

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

// ── boot ─────────────────────────────────────────────────────────────────────
let last = performance.now();
function animate() {
  requestAnimationFrame(animate);
  const now = performance.now();
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  if (streams) streams.step(dt);
  controls.update();
  renderer.render(scene, camera);
}

loadGeometry().then(() => {
  streams = new Streams(manifest);
  applyBulkheadTop(AS_DRAWN_BULKHEAD_TOP);
  document.getElementById('loading').style.display = 'none';
  connect();
  animate();
}).catch(err => {
  console.error(err);
  document.getElementById('loaderr').textContent =
    `${err}\n\nRun viewer/prepare_geometry.py first.`;
});

// Expose for console poking. `frame` and `hello` must be accessors: Object.assign
// would copy their value at load time (null) rather than tracking the live one.
Object.assign(window, { scene, camera, renderer, controls, groups, rackMeshes });
Object.defineProperties(window, {
  frame: { get: () => latest },
  hello: { get: () => hello },
  streams: { get: () => streams },
});
