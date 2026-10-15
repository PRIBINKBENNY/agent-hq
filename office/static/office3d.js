/* Agent HQ ring campus. One circular building (think Apple Park) cut open from above: each department is a
   segment of the ring, the brain stands in the courtyard at the centre, and a radial walkway joins every
   department to it. Agents sit at desks facing the courtyard, type while they work, walk along their
   walkway to the brain when they recall or remember, and cross the courtyard to another department's
   walkway when they delegate. Daylight, white walls, wood desks, soft screens, one accent per department,
   dark-on-light labels. API on window.HQ3D: init, setRoster, setState, say, goBrain, goHome, goTo, pulse,
   reward, setBrain, resize, focus, floorView. */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const OFFICE_ORDER = ["front-desk", "job-hunt", "pm", "studio", "brand-sales", "trading", "ops"];
const ACCENT = { "front-desk": 0xc2558f, "job-hunt": 0x3b6fd6, "pm": 0xd98433, "studio": 0x7a5fcf, "brand-sales": 0xd4a52a, "trading": 0xc94a5c, "ops": 0x2e9c86, "research": 0x3a9bc9, "creative": 0xd06a9c };
const TITLE = { "front-desk": "Front Desk", "job-hunt": "Job Hunt", "pm": "Project Office", "studio": "Studio", "brand-sales": "Brand & Sales", "trading": "Trading Desk", "ops": "Operations" };
const STATE_COLOR = { idle: 0x9aa3b5, think: 0x3b6fd6, tool: 0xd98433, delegate: 0x7a5fcf, done: 0x2e9c86, error: 0xc94a5c };
const SKIN = [0xf3cfae, 0xe0b08a, 0xc48e63, 0x9c6a45, 0x6f4a30, 0xf7dcc0];
const TOPS = [0x2d3f6b, 0xf2f2f2, 0x6b7a99, 0x8fb0d9, 0xd9c7b0, 0x3f3f4a, 0xb9d3c2, 0xe6b3b3, 0x4a6b8a, 0xf0d9a8];
const HAIR = [0x1d140e, 0x3b2616, 0x6b3f22, 0xb8842d, 0x2a2a2a, 0x8a8a8a, 0xc24b2f];
const RI = 34, RO = 54, RP = 13, H = 6;          // ring inner/outer radius, courtyard plaza radius, wall height

let renderer, scene, camera, controls, container, clock, raycaster, mouse;
let ring, figures = {}, depts = {}, brain, brainRings = [], brainLight, particles = [], labels = [], opts = {}, lastFrame = 0, hovered = null;
const polar = (r, th, y = 0) => new THREE.Vector3(r * Math.cos(th), y, -r * Math.sin(th));
const facing = (from, to) => { const d = to.clone().sub(from); return Math.atan2(d.x, d.z) + Math.PI; };   // figures and desks face -z locally

/* ----------------------------------------------------------------------------- textures and labels */
function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
function textSprite(text, { size = 26, color = "#1b2130", bg = "rgba(255,255,255,.94)", pad = 12, bold = true, accent, border = "rgba(0,0,0,.12)" } = {}) {
  const c = document.createElement("canvas"); const g = c.getContext("2d");
  g.font = `${bold ? "700" : "500"} ${size}px -apple-system, Inter, system-ui, sans-serif`;
  const w = Math.ceil(g.measureText(text).width + pad * 2 + (accent ? 18 : 0)), h = size + pad * 2;
  c.width = w * 2; c.height = h * 2; g.scale(2, 2);
  g.fillStyle = bg; roundRect(g, 0.5, 0.5, w - 1, h - 1, h / 2); g.fill(); g.strokeStyle = border; g.lineWidth = 1; g.stroke();
  if (accent) { g.fillStyle = accent; g.beginPath(); g.arc(pad + 2, h / 2, 5, 0, Math.PI * 2); g.fill(); }
  g.font = `${bold ? "700" : "500"} ${size}px -apple-system, Inter, system-ui, sans-serif`; g.fillStyle = color; g.textBaseline = "middle"; g.textAlign = "left";
  g.fillText(text, pad + (accent ? 18 : 0), h / 2 + 1);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.minFilter = THREE.LinearFilter;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false })); sp.scale.set(w / 24, h / 24, 1); sp.renderOrder = 10; return sp;
}
function screenTexture(kind, accentHex) {
  const c = document.createElement("canvas"); c.width = 512; c.height = 256; const g = c.getContext("2d");
  const acc = "#" + accentHex.toString(16).padStart(6, "0");
  g.fillStyle = "#f4f6fa"; g.fillRect(0, 0, 512, 256); g.fillStyle = "#ffffff"; g.fillRect(0, 0, 512, 34); g.fillStyle = "#e3e7ee"; g.fillRect(0, 34, 512, 1);
  g.font = "700 15px system-ui"; g.fillStyle = "#1b2130"; g.fillText((TITLE[kind] || kind).toUpperCase(), 14, 22); g.fillStyle = acc; g.fillRect(14, 28, 60, 3);
  if (kind === "trading") {
    let p = 140; for (let i = 0; i < 40; i++) { const o = p, cl = Math.max(60, Math.min(230, o + (Math.random() - 0.48) * 24)); const hi = Math.max(o, cl) - Math.random() * 9, lo = Math.min(o, cl) + Math.random() * 9; const x = 16 + i * 12;
      g.strokeStyle = g.fillStyle = cl < o ? "#2e9c86" : "#c94a5c"; g.beginPath(); g.moveTo(x + 3, hi); g.lineTo(x + 3, lo); g.stroke(); g.fillRect(x, Math.min(o, cl), 6, Math.max(2, Math.abs(cl - o))); p = cl; }
    g.fillStyle = "#1b2130"; g.fillRect(0, 234, 512, 22); g.font = "600 13px ui-monospace"; g.fillStyle = "#f4f6fa"; g.fillText("GOLD 4143.9 ▲0.6%   US500 7695 ▲0.2%   UK100 ▼0.1%   EURUSD 1.164   VODL 1.179", 8, 249);
  } else if (kind === "studio") {
    const cols = ["#7a5fcf", "#3a9bc9", "#2e9c86", "#d98433", "#4a5568"]; for (let i = 0; i < 13; i++) { const y = 48 + i * 15; let x = 16 + (i % 3) * 20; for (let k = 0; k < 2 + (i * 7) % 4; k++) { const w = 18 + ((i * 13 + k * 29) % 70); g.fillStyle = cols[(i + k) % cols.length]; g.fillRect(x, y, w, 7); x += w + 10; } }
  } else if (kind === "pm") {
    ["TO DO", "DOING", "REVIEW", "DONE"].forEach((t, i) => { const x = 14 + i * 124; g.fillStyle = "#e9edf3"; roundRect(g, x, 44, 112, 200, 8); g.fill(); g.font = "700 12px system-ui"; g.fillStyle = "#4a5568"; g.fillText(t, x + 8, 62); for (let k = 0; k < 2 + (i * 2) % 4; k++) { g.fillStyle = "#ffffff"; roundRect(g, x + 8, 74 + k * 36, 96, 26, 5); g.fill(); g.fillStyle = i === 3 ? "#2e9c86" : i === 2 ? "#d4a52a" : "#d98433"; g.fillRect(x + 8, 74 + k * 36, 4, 26); } });
  } else if (kind === "job-hunt") {
    for (let i = 0; i < 6; i++) { const x = 14 + (i % 3) * 164, y = 46 + Math.floor(i / 3) * 100; g.fillStyle = "#ffffff"; roundRect(g, x, y, 150, 86, 8); g.fill(); g.strokeStyle = "#e3e7ee"; g.stroke(); g.fillStyle = acc; g.fillRect(x + 10, y + 12, 60, 8); g.fillStyle = "#c7cedb"; g.fillRect(x + 10, y + 30, 120, 6); g.fillRect(x + 10, y + 44, 90, 6); g.fillStyle = "#2e9c86"; g.font = "700 12px system-ui"; g.fillText("fit " + (3 + i % 3) + "/5", x + 10, y + 74); }
  } else if (kind === "brand-sales") {
    for (let i = 0; i < 3; i++) { const y = 46 + i * 64; g.fillStyle = "#ffffff"; roundRect(g, 14, y, 484, 54, 8); g.fill(); g.strokeStyle = "#e3e7ee"; g.stroke(); g.fillStyle = acc; g.beginPath(); g.arc(40, y + 27, 14, 0, Math.PI * 2); g.fill(); g.fillStyle = "#c7cedb"; g.fillRect(66, y + 14, 200 + i * 40, 7); g.fillRect(66, y + 30, 320, 6); g.fillStyle = "#c2558f"; g.font = "700 12px system-ui"; g.fillText("♥ " + (120 + i * 87), 430, y + 34); }
  } else if (kind === "ops") {
    for (let i = 0; i < 7; i++) { const y = 52 + i * 27; g.strokeStyle = i < 4 ? "#2e9c86" : "#9aa3b5"; g.lineWidth = 2; g.strokeRect(16, y, 14, 14); if (i < 4) { g.beginPath(); g.moveTo(18, y + 7); g.lineTo(23, y + 12); g.lineTo(29, y + 2); g.stroke(); } g.fillStyle = i < 4 ? "#4a5568" : "#c7cedb"; g.fillRect(40, y + 4, 180 + (i * 53) % 200, 6); }
  } else {
    g.font = "800 42px system-ui"; g.fillStyle = "#1b2130"; g.fillText("Welcome", 24, 120); g.font = "500 18px system-ui"; g.fillStyle = "#4a5568"; g.fillText("Agent HQ reception · one shared brain", 24, 156);
  }
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; return tex;
}

/* ----------------------------------------------------------------------------- materials */
const M = {
  ground: new THREE.MeshStandardMaterial({ color: 0xd6d8d3, roughness: 0.92 }),
  path: new THREE.MeshStandardMaterial({ color: 0xc3c6c0, roughness: 0.95 }),
  grass: new THREE.MeshStandardMaterial({ color: 0x8fb57a, roughness: 1 }),
  wall: new THREE.MeshStandardMaterial({ color: 0xf2f1ec, roughness: 0.85, side: THREE.DoubleSide }),
  wallDark: new THREE.MeshStandardMaterial({ color: 0x4a5160, roughness: 0.7, metalness: 0.2 }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0xcfe3f2, transmission: 0.9, opacity: 0.3, transparent: true, roughness: 0.08, metalness: 0, thickness: 0.4, side: THREE.DoubleSide, depthWrite: false }),
  frame: new THREE.MeshStandardMaterial({ color: 0x3a4150, roughness: 0.5, metalness: 0.6 }),
  carpet: new THREE.MeshStandardMaterial({ color: 0xb9c3cf, roughness: 1, side: THREE.DoubleSide }),
  wood: new THREE.MeshStandardMaterial({ color: 0xd4b48c, roughness: 0.6 }),
  deskLeg: new THREE.MeshStandardMaterial({ color: 0xf4f4f2, roughness: 0.6, metalness: 0.1 }),
  chair: new THREE.MeshStandardMaterial({ color: 0x4a5160, roughness: 0.9 }),
  monitor: new THREE.MeshStandardMaterial({ color: 0x2a2f3a, roughness: 0.4, metalness: 0.5 }),
  screen: new THREE.MeshStandardMaterial({ color: 0xeaf1fb, emissive: 0xdde8f7, emissiveIntensity: 0.55, roughness: 0.3 }),
  plant: new THREE.MeshStandardMaterial({ color: 0x4f9a5c, roughness: 0.9 }), pot: new THREE.MeshStandardMaterial({ color: 0xcbbca6, roughness: 0.9 }),
  trunk: new THREE.MeshStandardMaterial({ color: 0x7a5a3a, roughness: 1 }), canopy: new THREE.MeshStandardMaterial({ color: 0x5f9e5a, roughness: 1 }),
  shadow: new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.18, depthWrite: false }),
  accentBand: (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.7 }),
  light: (c, i = 0.9) => new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: i, roughness: 0.4 }),
};
function box(w, h, d, mat) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.castShadow = true; m.receiveShadow = true; return m; }
function disc(r, mat) { const m = new THREE.Mesh(new THREE.CircleGeometry(r, 24), mat); m.rotation.x = -Math.PI / 2; m.renderOrder = 1; return m; }
/* a curved wall built from short boxes along an arc (no geometry-convention headaches) */
function arcWall(group, r, th0, th1, y, h, thick, mat, step = 0.05) {
  const n = Math.max(2, Math.ceil((th1 - th0) / step)); const dth = (th1 - th0) / n;
  for (let i = 0; i < n; i++) { const a = th0 + (i + 0.5) * dth; const seg = box(thick, h, r * dth + 0.05, mat); seg.position.copy(polar(r, a, y)); seg.rotation.y = a; group.add(seg); }
}

/* ----------------------------------------------------------------------------- init */
export function init(el, options = {}) {
  container = el; opts = options; clock = new THREE.Clock();
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1)); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0; renderer.outputColorSpace = THREE.SRGBColorSpace;
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene(); scene.background = new THREE.Color(0xdbe6f3); scene.fog = new THREE.Fog(0xdbe6f3, 240, 520);
  camera = new THREE.PerspectiveCamera(36, 1, 0.5, 900); camera.position.set(0, 96, 128);
  controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.dampingFactor = 0.07;
  controls.maxPolarAngle = Math.PI / 2.4; controls.minPolarAngle = 0.2; controls.minDistance = 16; controls.maxDistance = 300; controls.target.set(0, 2, -6);
  raycaster = new THREE.Raycaster(); mouse = new THREE.Vector2();
  scene.add(new THREE.HemisphereLight(0xeaf2ff, 0x8a8f86, 0.95));
  const sun = new THREE.DirectionalLight(0xfff2e0, 2.2); sun.position.set(80, 130, 60); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); Object.assign(sun.shadow.camera, { left: -120, right: 120, top: 120, bottom: -120, far: 360 }); sun.shadow.bias = -0.0005; sun.shadow.radius = 3; scene.add(sun);
  const fill = new THREE.DirectionalLight(0xcfe0ff, 0.5); fill.position.set(-60, 40, -50); scene.add(fill);
  const ground = new THREE.Mesh(new THREE.CircleGeometry(190, 96), M.grass); ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
  const apron = new THREE.Mesh(new THREE.RingGeometry(RO + 1, RO + 7, 96), M.path); apron.rotation.x = -Math.PI / 2; apron.position.y = 0.03; apron.receiveShadow = true; scene.add(apron);
  const court = new THREE.Mesh(new THREE.CircleGeometry(RI - 0.5, 96), M.grass); court.rotation.x = -Math.PI / 2; court.position.y = 0.03; court.receiveShadow = true; scene.add(court);
  const plaza = new THREE.Mesh(new THREE.CircleGeometry(RP, 64), M.path); plaza.rotation.x = -Math.PI / 2; plaza.position.y = 0.05; plaza.receiveShadow = true; scene.add(plaza);
  const plazaRing = new THREE.Mesh(new THREE.RingGeometry(RP - 0.5, RP, 64), M.wallDark); plazaRing.rotation.x = -Math.PI / 2; plazaRing.position.y = 0.06; scene.add(plazaRing);
  for (let i = 0; i < 34; i++) { const a = (i / 34) * Math.PI * 2 + 0.1, r = RO + 14 + (i % 3) * 12; const tree = new THREE.Group(); const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.7, 5, 8), M.trunk); trunk.position.y = 2.5; trunk.castShadow = true; tree.add(trunk);
    const c1 = new THREE.Mesh(new THREE.SphereGeometry(3.4 + (i % 2), 12, 10), M.canopy); c1.position.y = 7; c1.castShadow = true; tree.add(c1); tree.position.copy(polar(r, a)); scene.add(tree); }
  for (let i = 0; i < 10; i++) { const a = (i / 10) * Math.PI * 2 + 0.3, r = RP + 7 + (i % 2) * 6; if (Math.abs(Math.sin(a * 3.5)) < 0.25) continue; const tree = new THREE.Group(); const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.5, 3.5, 8), M.trunk); trunk.position.y = 1.75; tree.add(trunk); const c1 = new THREE.Mesh(new THREE.SphereGeometry(2.2, 12, 10), M.canopy); c1.position.y = 4.6; c1.castShadow = true; tree.add(c1); tree.position.copy(polar(r, a)); scene.add(tree); }
  buildCenter();
  renderer.domElement.addEventListener("pointerdown", e => { mouse.userData = { x: e.clientX, y: e.clientY }; });
  renderer.domElement.addEventListener("pointerup", e => { const d = mouse.userData; if (d && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5) { const f = pick(e); if (f && opts.onAgentClick) opts.onAgentClick(f.name); } });
  renderer.domElement.addEventListener("pointermove", e => { const f = pick(e); if (hovered && hovered !== f) hovered.hover = false; hovered = f; if (f) f.hover = true; renderer.domElement.style.cursor = f ? "pointer" : "grab"; });
  new ResizeObserver(() => resize()).observe(el); resize();
  requestAnimationFrame(frame);
}
export function resize() {
  if (!renderer) return;
  const w = container.clientWidth || 1, h = container.clientHeight || 1;
  renderer.setSize(w, h, false); renderer.domElement.style.width = w + "px"; renderer.domElement.style.height = h + "px";
  camera.aspect = w / h; camera.updateProjectionMatrix();
}
export function floorView(on) { setTimeout(resize, 30); if (on) { camera.position.set(0, 90, 120); controls.target.set(0, 2, -6); } }
function pick(e) {
  const r = renderer.domElement.getBoundingClientRect();
  mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(Object.values(figures).map(f => f.group), true);
  if (!hits.length) return null; let o = hits[0].object; while (o && !o.userData.agent) o = o.parent; return o ? figures[o.userData.agent] : null;
}

/* ----------------------------------------------------------------------------- the brain in the courtyard */
function buildCenter() {
  const hq = new THREE.Group();
  const plinth = new THREE.Mesh(new THREE.CylinderGeometry(3.2, 4.2, 2.2, 48), M.wallDark); plinth.position.y = 1.1; plinth.castShadow = true; plinth.receiveShadow = true; hq.add(plinth);
  for (let i = 0; i < 8; i++) { const a = (i / 8) * Math.PI * 2; const col = box(0.5, 13, 0.5, M.wall); col.position.copy(polar(RP - 2, a, 6.5)); hq.add(col); }
  const canopy = new THREE.Mesh(new THREE.RingGeometry(RP - 5, RP - 0.5, 64), M.wall); canopy.rotation.x = -Math.PI / 2; canopy.position.y = 13.2; canopy.castShadow = true; hq.add(canopy);
  const canopyGlass = new THREE.Mesh(new THREE.CircleGeometry(RP - 5, 64), M.glass); canopyGlass.rotation.x = -Math.PI / 2; canopyGlass.position.y = 13.1; hq.add(canopyGlass);
  brain = new THREE.Group(); brain.position.set(0, 7, 0);
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(3.2, 4), new THREE.MeshStandardMaterial({ color: 0x8fc2ff, emissive: 0x5a9cf0, emissiveIntensity: 1.1, roughness: 0.25, metalness: 0.1 })); brain.add(core); brain.userData.core = core;
  const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(4.3, 1), new THREE.MeshBasicMaterial({ color: 0x8fc2ff, wireframe: true, transparent: true, opacity: 0.18 })); brain.add(shell); brain.userData.shell = shell;
  for (let i = 0; i < 2; i++) { const t = new THREE.Mesh(new THREE.TorusGeometry(5.6 + i * 1.3, 0.12, 8, 96), M.frame); t.rotation.set(Math.PI / 2 + i * 0.6, i * 0.9, 0); brain.add(t); brainRings.push(t); }
  brainLight = new THREE.PointLight(0x7fb3ff, 25, 40, 1.8); brainLight.position.set(0, 1, 0); brain.add(brainLight);
  const lbl = textSprite("HEADQUARTERS · the brain", { size: 24 }); lbl.position.set(0, 10.5, 0); brain.add(lbl); brain.userData.label = lbl;
  hq.add(brain); scene.add(hq);
}
export function setBrain(count) {
  if (!brain) return; const old = brain.userData.label; brain.remove(old); old.material.map.dispose();
  const lbl = textSprite(`HEADQUARTERS · ${count} notes in the brain`, { size: 24 }); lbl.position.set(0, 10.5, 0); brain.add(lbl); brain.userData.label = lbl;
}

/* ----------------------------------------------------------------------------- the ring building */
export function setRoster(list) {
  if (ring) scene.remove(ring); Object.values(figures).forEach(f => { scene.remove(f.group); scene.remove(f.label); if (f.bubbleSprite) scene.remove(f.bubbleSprite); });
  figures = {}; depts = {}; labels = []; ring = new THREE.Group(); scene.add(ring);
  const byOffice = {}; list.forEach(a => (byOffice[a.office] = byOffice[a.office] || []).push(a));
  const names = Object.keys(byOffice).sort((a, b) => (OFFICE_ORDER.indexOf(a) + 99) % 100 - (OFFICE_ORDER.indexOf(b) + 99) % 100);
  const n = names.length; const span = Math.PI * 2 / n; const gap = 0.012;
  // shared parts: floor slab, outer wall, roof overhang ring
  const slab = new THREE.Mesh(new THREE.RingGeometry(RI - 0.6, RO + 0.6, 96), M.wallDark); slab.rotation.x = -Math.PI / 2; slab.position.y = 0.4; slab.receiveShadow = true; ring.add(slab);
  const carpet = new THREE.Mesh(new THREE.RingGeometry(RI, RO, 96), M.carpet); carpet.rotation.x = -Math.PI / 2; carpet.position.y = 0.82; carpet.receiveShadow = true; ring.add(carpet);
  arcWall(ring, RO, 0, Math.PI * 2, 0.8 + H / 2, H, 0.5, M.wall, 0.04);
  const eave = new THREE.Mesh(new THREE.RingGeometry(RO - 0.2, RO + 2.2, 96), M.wall); eave.rotation.x = -Math.PI / 2; eave.position.y = 0.8 + H + 0.2; eave.castShadow = true; ring.add(eave);
  names.forEach((name, i) => {
    const members = byOffice[name]; const accent = ACCENT[name] || 0x3b6fd6;
    const th0 = Math.PI / 2 + i * span + gap, th1 = Math.PI / 2 + (i + 1) * span - gap, mid = (th0 + th1) / 2;
    depts[name] = { name, mid, accent, gate: polar(RI - 1.2, mid), plaza: polar(RP + 1.2, mid), centre: polar((RI + RO) / 2, mid) };
    // partitions, inner glass wall with a doorway on the walkway, parapet in the department colour
    for (const th of [th0, th1]) { const part = box(RO - RI, H, 0.4, M.wall); part.position.copy(polar((RI + RO) / 2, th, 0.8 + H / 2)); part.rotation.y = th + Math.PI / 2; ring.add(part); }
    const door = 2.6 / RI;
    arcWall(ring, RI, th0, mid - door, 0.8 + H / 2, H, 0.3, M.glass); arcWall(ring, RI, mid + door, th1, 0.8 + H / 2, H, 0.3, M.glass);
    arcWall(ring, RI, th0, th1, 0.8 + H + 0.17, 0.35, 0.7, M.accentBand(accent)); arcWall(ring, RO, th0, th1, 0.8 + H + 0.17, 0.35, 0.7, M.accentBand(accent));
    for (const th of [mid - door, mid + door]) { const post = box(0.3, H, 0.3, M.frame); post.position.copy(polar(RI, th, 0.8 + H / 2)); ring.add(post); }
    const lintel = box(0.4, 0.4, RI * door * 2 + 0.6, M.frame); lintel.position.copy(polar(RI, mid, 0.8 + H - 0.2)); lintel.rotation.y = mid; ring.add(lintel);
    // walkway from the doorway to the plaza
    const L = RI - RP - 2.4; const walk = box(3.6, 0.12, L, M.path); walk.position.copy(polar(RP + 1.2 + L / 2, mid, 0.06)); walk.rotation.y = mid; walk.receiveShadow = true; ring.add(walk);
    for (const sx of [-1, 1]) { const kerb = box(0.22, 0.25, L, M.wallDark); kerb.position.copy(polar(RP + 1.2 + L / 2, mid, 0.12)); kerb.rotation.y = mid; kerb.translateX(sx * 1.95); ring.add(kerb); }
    const lamp = new THREE.Group(); const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 4.2, 8), M.frame); pole.position.y = 2.1; lamp.add(pole); const head = new THREE.Mesh(new THREE.SphereGeometry(0.3, 8, 8), M.light(0xfff4dc, 0.6)); head.position.y = 4.3; lamp.add(head); lamp.position.copy(polar(RP + L / 2, mid)); lamp.rotation.y = mid; lamp.translateX(2.6); ring.add(lamp);
    // department sign over the doorway and the wall display on the outer wall
    const sign = textSprite(TITLE[name] || name, { size: 34, accent: "#" + accent.toString(16).padStart(6, "0") }); sign.position.copy(polar(RI - 0.5, mid, 0.8 + H + 4.0)); ring.add(sign);
    const count = textSprite(`${members.length} agent${members.length > 1 ? "s" : ""}`, { size: 19, bold: false, bg: "rgba(255,255,255,.85)" }); count.position.copy(polar(RI - 0.5, mid, 0.8 + H + 2.3)); ring.add(count);
    const arcLen = RO * (th1 - th0); const sw = Math.min(arcLen - 6, 11), sh = sw / 2; const tex = screenTexture(name, accent);
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(sw, sh), new THREE.MeshStandardMaterial({ map: tex, emissive: 0xffffff, emissiveMap: tex, emissiveIntensity: 0.35, roughness: 0.4 }));
    screen.position.copy(polar(RO - 0.6, mid, 0.8 + 2.3 + sh / 2)); screen.rotation.y = mid - Math.PI / 2; ring.add(screen);   // face the courtyard
    const bezel = box(sw + 0.5, sh + 0.5, 0.2, M.monitor); bezel.position.copy(polar(RO - 0.36, mid, 0.8 + 2.3 + sh / 2)); bezel.rotation.y = mid + Math.PI / 2; ring.add(bezel);
    for (const th of [th0 + 0.05, th1 - 0.05]) { const plant = new THREE.Group(); const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.6, 1.3, 14), M.pot); pot.position.y = 1.45; plant.add(pot); for (let k = 0; k < 5; k++) { const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.75, 10, 8), M.plant); leaf.position.set(Math.cos(k * 1.26) * 0.55, 2.7 + (k % 2) * 0.4, Math.sin(k * 1.26) * 0.55); leaf.castShadow = true; plant.add(leaf); } plant.position.copy(polar(RO - 2.2, th, 0.8)); ring.add(plant); }
    if (name === "front-desk") { const counter = box(6.5, 2.6, 1.6, M.wall); counter.position.copy(polar(RI + 3.2, mid, 2.1)); counter.rotation.y = mid + Math.PI / 2; ring.add(counter); const ctop = box(6.9, 0.2, 2.0, M.wood); ctop.position.copy(polar(RI + 3.2, mid, 3.5)); ctop.rotation.y = mid + Math.PI / 2; ring.add(ctop); }
    // desks: rows along the radius, columns along the arc, everyone facing the courtyard
    const cols = Math.min(4, Math.ceil(members.length / 2)), rows = Math.ceil(members.length / cols);
    members.forEach((a, k) => {
      const row = Math.floor(k / cols), col = k % cols; const inRow = Math.min(cols, members.length - row * cols);
      const r = RI + 7 + row * 7.5 + (name === "front-desk" ? 3 : 0); const dth = 7.2 / r; const th = mid + (col - (inRow - 1) / 2) * dth;
      const deskPos = polar(r, th, 0.8); const rot = facing(deskPos, new THREE.Vector3(0, 0.8, 0));
      const desk = addDesk(); desk.position.copy(deskPos); desk.rotation.y = rot; ring.add(desk);
      const seat = deskPos.clone().add(new THREE.Vector3(Math.sin(rot) * 2.0, 0, Math.cos(rot) * 2.0));   // the chair is at local +z, behind the desk from the courtyard
      const fig = makeFigure(a, k, accent); fig.group.position.copy(seat); fig.group.rotation.y = rot;
      fig.home = seat.clone(); fig.homeRot = rot; fig.dept = name; scene.add(fig.group);
      fig.label = textSprite(a.name, { size: 21, accent: "#" + accent.toString(16).padStart(6, "0") }); fig.label.position.copy(seat).add(new THREE.Vector3(0, 7.6, 0)); scene.add(fig.label);
      figures[a.name] = fig;
    });
  });
}

function addDesk() {
  const g = new THREE.Group();
  const top = box(5.4, 0.22, 2.6, M.wood); top.position.set(0, 1.85, 0); g.add(top);
  for (const sx of [-1, 1]) { const leg = box(0.25, 1.75, 2.2, M.deskLeg); leg.position.set(sx * 2.5, 0.9, 0); g.add(leg); }
  const mon = box(2.9, 1.75, 0.14, M.monitor); mon.position.set(0, 3.05, -0.85); g.add(mon);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(2.65, 1.5), M.screen); scr.position.set(0, 3.05, -0.77); g.add(scr);
  const stand = box(0.35, 0.9, 0.35, M.monitor); stand.position.set(0, 2.3, -0.85); g.add(stand);
  const kb = box(1.8, 0.1, 0.6, M.deskLeg); kb.position.set(0, 2.02, 0.35); g.add(kb);
  const mouse = box(0.35, 0.12, 0.5, M.deskLeg); mouse.position.set(1.4, 2.02, 0.4); g.add(mouse);
  const seat = box(1.7, 0.3, 1.7, M.chair); seat.position.set(0, 1.05, 2.0); g.add(seat);
  const back = box(1.7, 2.1, 0.3, M.chair); back.position.set(0, 2.25, 2.85); g.add(back);
  const post = box(0.22, 1.0, 0.22, M.frame); post.position.set(0, 0.5, 2.0); g.add(post);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 0.1, 16), M.frame); base.position.set(0, 0.08, 2.0); g.add(base);
  const sh = disc(2.3, M.shadow); sh.position.set(0, 0.03, 0.6); sh.scale.set(1.4, 0.9, 1); g.add(sh);
  return g;
}

/* ----------------------------------------------------------------------------- characters */
function capsule(r, len, mat) { const m = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 6, 12), mat); m.castShadow = true; return m; }
function makeFigure(a, k, accent) {
  const group = new THREE.Group(); group.userData.agent = a.name;
  const seed = [...a.name].reduce((s, ch) => s + ch.charCodeAt(0), 0) + k;
  const skin = new THREE.MeshStandardMaterial({ color: SKIN[seed % SKIN.length], roughness: 0.6 });
  const top = new THREE.MeshStandardMaterial({ color: TOPS[(seed * 7) % TOPS.length], roughness: 0.75 });
  const trousers = new THREE.MeshStandardMaterial({ color: [0x2a3042, 0x3f3f4a, 0x4a5a7a, 0x6b5a4a][seed % 4], roughness: 0.85 });
  const hairMat = new THREE.MeshStandardMaterial({ color: HAIR[(seed * 3) % HAIR.length], roughness: 0.9 });
  const body = new THREE.Group(); group.add(body);
  const hips = capsule(0.72, 0.3, trousers); hips.rotation.z = Math.PI / 2; hips.position.y = 2.0; body.add(hips);
  const torso = capsule(0.78, 1.2, top); torso.position.y = 3.05; torso.scale.set(1, 1, 0.78); body.add(torso);
  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.26, 0.35, 10), skin); neck.position.y = 3.95; body.add(neck);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.62, 20, 16), skin); head.position.y = 4.6; head.scale.set(1, 1.08, 1); head.castShadow = true; body.add(head);
  const style = seed % 5;
  if (style !== 4) { const hair = new THREE.Mesh(new THREE.SphereGeometry(0.66, 20, 12, 0, Math.PI * 2, 0, style === 1 ? Math.PI / 1.7 : Math.PI / 2.1), hairMat); hair.position.set(0, 0.06, -0.02); hair.scale.set(1, style === 2 ? 1.25 : 1, 1); head.add(hair); }
  if (style === 3) { const bun = new THREE.Mesh(new THREE.SphereGeometry(0.3, 12, 10), hairMat); bun.position.set(0, 0.62, -0.35); head.add(bun); }
  const eyeMat = new THREE.MeshStandardMaterial({ color: 0x1a1a22, roughness: 0.3 });
  for (const sx of [-1, 1]) { const eye = new THREE.Mesh(new THREE.SphereGeometry(0.07, 8, 8), eyeMat); eye.position.set(sx * 0.22, 0.05, -0.56); head.add(eye); }
  if (seed % 3 === 0) { const glasses = new THREE.Mesh(new THREE.TorusGeometry(0.14, 0.025, 6, 16), M.frame); glasses.position.set(-0.22, 0.05, -0.6); head.add(glasses); const g2 = glasses.clone(); g2.position.x = 0.22; head.add(g2); }
  const armL = capsule(0.22, 0.9, top); armL.position.set(-0.95, 3.15, 0); body.add(armL); const armR = capsule(0.22, 0.9, top); armR.position.set(0.95, 3.15, 0); body.add(armR);
  const foreL = capsule(0.18, 0.75, skin); foreL.position.set(-0.95, 2.55, -0.6); body.add(foreL); const foreR = capsule(0.18, 0.75, skin); foreR.position.set(0.95, 2.55, -0.6); body.add(foreR);
  const legs = new THREE.Group(); group.add(legs);
  const thL = capsule(0.3, 1.0, trousers), thR = capsule(0.3, 1.0, trousers), shL = capsule(0.26, 1.0, trousers), shR = capsule(0.26, 1.0, trousers); legs.add(thL, thR, shL, shR);
  const shoeMat = new THREE.MeshStandardMaterial({ color: 0x2a2a30, roughness: 0.6 }); const shoeL = box(0.5, 0.25, 0.85, shoeMat), shoeR = box(0.5, 0.25, 0.85, shoeMat); legs.add(shoeL, shoeR);
  const light = new THREE.Mesh(new THREE.SphereGeometry(0.2, 10, 8), M.light(STATE_COLOR.idle, 0.4)); light.position.y = 5.65; group.add(light);
  const halo = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.2, 32), new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false })); halo.rotation.x = -Math.PI / 2; halo.position.y = 0.06; group.add(halo);
  const fig = { name: a.name, group, body, legs, parts: { armL, armR, foreL, foreR, thL, thR, shL, shR, shoeL, shoeR, head, light, halo }, state: "idle", seated: true, target: null, path: [], bubbleSprite: null, bubbleUntil: 0, phase: Math.random() * 6, hover: false };
  pose(fig, true); return fig;
}
function pose(fig, seated) {
  const p = fig.parts; fig.seated = seated;
  if (seated) {
    p.thL.position.set(-0.4, 1.75, -0.55); p.thL.rotation.x = Math.PI / 2; p.thR.position.set(0.4, 1.75, -0.55); p.thR.rotation.x = Math.PI / 2;
    p.shL.position.set(-0.4, 0.95, -1.1); p.shL.rotation.x = 0; p.shR.position.set(0.4, 0.95, -1.1); p.shR.rotation.x = 0;
    p.shoeL.position.set(-0.4, 0.15, -1.3); p.shoeR.position.set(0.4, 0.15, -1.3);
    fig.body.position.y = 0; p.armL.rotation.x = -0.85; p.armR.rotation.x = -0.85; p.foreL.rotation.x = -Math.PI / 2.3; p.foreR.rotation.x = -Math.PI / 2.3;
  } else {
    p.thL.position.set(-0.4, 1.1, 0); p.thL.rotation.x = 0; p.thR.position.set(0.4, 1.1, 0); p.thR.rotation.x = 0;
    p.shL.position.set(-0.4, 0.5, 0); p.shR.position.set(0.4, 0.5, 0); p.shoeL.position.set(-0.4, 0.12, 0.15); p.shoeR.position.set(0.4, 0.12, 0.15);
    fig.body.position.y = 0.75; p.armL.rotation.x = 0; p.armR.rotation.x = 0; p.foreL.rotation.x = -0.4; p.foreR.rotation.x = -0.4;
  }
}

/* ----------------------------------------------------------------------------- routes: desk -> doorway -> walkway -> plaza */
function walk(f, points, lookAt = null) { f.path = points.map(p => p.clone()); f.lookAt = lookAt; f.target = f.path.shift(); }
export function setState(name, state) { const f = figures[name]; if (!f) return; f.state = state; f.parts.light.material = M.light(STATE_COLOR[state] || STATE_COLOR.idle, state === "idle" ? 0.4 : 1.0); }
export function say(name, text, ms = 6000) {
  const f = figures[name]; if (!f) return;
  if (f.bubbleSprite) { scene.remove(f.bubbleSprite); f.bubbleSprite.material.map.dispose(); }
  f.bubbleSprite = textSprite(text.length > 46 ? text.slice(0, 44) + "…" : text, { size: 19, bold: false }); f.bubbleUntil = Date.now() + ms; scene.add(f.bubbleSprite);
}
export function goBrain(name) {
  const f = figures[name]; const d = f && depts[f.dept]; if (!d) return;
  const spot = d.plaza.clone().lerp(new THREE.Vector3(0, 0, 0), 0.35).add(new THREE.Vector3((Math.random() - 0.5) * 3, 0, (Math.random() - 0.5) * 3));
  walk(f, f.seated || f.group.position.distanceTo(f.home) < 1 ? [d.gate, d.plaza, spot] : [spot], new THREE.Vector3(0, 0, 0));
}
export function goHome(name) {
  const f = figures[name]; const d = f && depts[f.dept]; if (!f) return;
  if (f.group.position.distanceTo(f.home) < 0.5 && !f.target) return;
  const outside = f.group.position.length() < RI - 0.5;          // in the courtyard: come back through the doorway
  walk(f, outside && d ? [d.plaza, d.gate, f.home] : [f.home], null);
}
export function goTo(name, other) {
  const f = figures[name], o = figures[other]; const d = f && depts[f.dept], od = o && depts[o.dept]; if (!f || !o || !d || !od) return;
  const near = o.home.clone().add(polar(3.2, od.mid)).sub(o.home.clone().normalize().multiplyScalar(0)); const stop = o.home.clone().add(o.home.clone().normalize().multiplyScalar(-3.2));
  if (f.dept === o.dept) { walk(f, [stop], o.home); return; }
  walk(f, [d.gate, d.plaza, od.plaza, od.gate, stop], o.home);
}
export function pulse(fromName, toBrain, color = 0x5a9cf0) {
  const f = figures[fromName]; if (!f) return;
  const from = toBrain ? f.group.position.clone().add(new THREE.Vector3(0, 4, 0)) : new THREE.Vector3(0, 7, 0);
  const to = toBrain ? new THREE.Vector3(0, 7, 0) : f.home.clone().add(new THREE.Vector3(0, 4, 0));
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.32, 8, 8), M.light(color, 1.2)); mesh.position.copy(from);
  particles.push({ from, to, u: 0, speed: 0.012 + Math.random() * 0.006, mesh, lift: 14 + Math.random() * 6 }); scene.add(mesh);
}
export function focus(name) { const f = figures[name]; if (!f) return; controls.target.copy(f.group.position).add(new THREE.Vector3(0, 2, 0)); }
export function reward(detail = {}) {
  const origin = depts.trading ? depts.trading.centre.clone().add(new THREE.Vector3(0, 10, 0)) : new THREE.Vector3(0, 12, 0);
  for (let i = 0; i < 48; i++) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.35, 0.08), M.light(i % 3 ? 0xd4a52a : 0xfff0b3, 0.9)); m.position.copy(origin); m.rotation.set(Math.random() * 3, Math.random() * 3, 0);
    const vel = new THREE.Vector3(Math.random() - 0.5, 0.7 + Math.random() * 0.8, Math.random() - 0.5).normalize().multiplyScalar(0.22 + Math.random() * 0.3);
    particles.push({ from: origin.clone(), to: new THREE.Vector3(0, 7, 0), u: 0, speed: 0.01, mesh: m, lift: 12, gold: true, vel }); scene.add(m);
  }
  if (brain) brain.userData.flash = 1.0;
  const txt = textSprite(`+${detail.pnl != null ? Number(detail.pnl).toFixed(2) : ""} ${detail.currency || ""} · ${detail.strategy || "trade"} · treasury ${detail.treasury ?? ""}`, { size: 24, color: "#5a3e00", bg: "rgba(255,236,170,.96)", border: "rgba(120,90,0,.3)" });
  txt.position.copy(origin).add(new THREE.Vector3(0, 4, 0)); scene.add(txt); labels.push({ sprite: txt, born: performance.now(), ttl: 5500, rise: 0.03 });
  if (figures["trader"]) say("trader", "💰 profitable trade", 6000);
}

/* ----------------------------------------------------------------------------- animation */
function frame(now) {
  requestAnimationFrame(frame);
  if (document.hidden) return;
  const busy = Object.values(figures).some(f => f.state !== "idle" || f.target || f.hover) || particles.length;
  if (!busy && now - lastFrame < 1000 / 24) return;
  lastFrame = now; const dt = Math.min(0.05, clock.getDelta()); const t = now / 1000;
  if (brain) {
    brain.rotation.y += dt * 0.18; brain.userData.shell.rotation.x -= dt * 0.12; brainRings.forEach((r, i) => { r.rotation.z += dt * (0.2 + i * 0.08); });
    const flash = brain.userData.flash || 0; brain.userData.flash = Math.max(0, flash - dt * 0.5);
    brain.userData.core.position.y = Math.sin(t * 1.2) * 0.25; const k = 1 + 0.03 * Math.sin(t * 2) + flash * 0.25; brain.userData.core.scale.setScalar(k);
    brain.userData.core.material.emissive.setHex(flash > 0.05 ? 0xe0a830 : 0x5a9cf0); brainLight.intensity = 25 + flash * 90; brainLight.color.setHex(flash > 0.05 ? 0xe0a830 : 0x7fb3ff);
  }
  for (const f of Object.values(figures)) {
    const p = f.parts, g = f.group;
    if (f.target) {
      const d = f.target.clone().sub(g.position); d.y = 0; const dist = d.length();
      if (dist < 0.35) {
        g.position.copy(f.target); g.position.y = f.home.y;
        if (f.path.length) { f.target = f.path.shift(); }
        else { f.target = null; const atHome = g.position.distanceTo(f.home) < 0.6; if (atHome) { g.rotation.y = f.homeRot; pose(f, true); } else if (f.lookAt) { g.rotation.y = facing(g.position, f.lookAt); } }
      } else {
        if (f.seated) pose(f, false); const step = Math.min(dist, dt * 14); g.position.add(d.normalize().multiplyScalar(step)); g.rotation.y = Math.atan2(d.x, d.z) + Math.PI;
        const sw = Math.sin(t * 10 + f.phase) * 0.7; p.thL.rotation.x = sw; p.thR.rotation.x = -sw; p.shL.rotation.x = Math.max(0, -sw) * 0.8; p.shR.rotation.x = Math.max(0, sw) * 0.8; p.armL.rotation.x = -sw * 0.6; p.armR.rotation.x = sw * 0.6; g.position.y = f.home.y - 0.75 + Math.abs(Math.sin(t * 10 + f.phase)) * 0.14;
      }
    } else if (f.seated) {
      const working = f.state === "think" || f.state === "tool" || f.state === "delegate";
      if (working) { p.foreL.position.y = 2.55 + Math.sin(t * 17 + f.phase) * 0.09; p.foreR.position.y = 2.55 + Math.cos(t * 16 + f.phase) * 0.09; p.head.position.y = 4.6 + Math.sin(t * 2.3 + f.phase) * 0.03; p.head.rotation.x = -0.14; p.head.rotation.y = Math.sin(t * 1.1 + f.phase) * 0.08; }
      else { p.foreL.position.y = 2.55; p.foreR.position.y = 2.55; p.head.position.y = 4.6 + Math.sin(t * 1.2 + f.phase) * 0.04; p.head.rotation.x = Math.sin(t * 0.45 + f.phase) * 0.06; p.head.rotation.y = Math.sin(t * 0.3 + f.phase) * 0.3; }
      f.body.position.y = Math.sin(t * 1.4 + f.phase) * 0.025;
    } else if (f.lookAt) { p.foreR.rotation.x = -0.6 + Math.sin(t * 5 + f.phase) * 0.25; }
    p.light.scale.setScalar(f.state === "idle" ? 0.75 : 1 + 0.3 * Math.sin(t * 6 + f.phase));
    p.halo.material.opacity = f.hover ? 0.9 : f.state !== "idle" ? 0.35 + 0.2 * Math.sin(t * 4 + f.phase) : 0;
    f.label.position.copy(g.position).add(new THREE.Vector3(0, f.seated ? 7.3 : 8.4, 0));
    if (f.bubbleSprite) { if (Date.now() > f.bubbleUntil) { scene.remove(f.bubbleSprite); f.bubbleSprite.material.map.dispose(); f.bubbleSprite = null; } else f.bubbleSprite.position.copy(g.position).add(new THREE.Vector3(0, (f.seated ? 9.1 : 10.2) + Math.sin(t * 2) * 0.1, 0)); }
  }
  for (let i = particles.length - 1; i >= 0; i--) {
    const q = particles[i];
    if (q.gold) { q.mesh.position.add(q.vel); q.vel.y -= 0.012; q.vel.multiplyScalar(0.985); q.mesh.rotation.x += 0.2; q.u += dt * 0.5; if (q.u > 1.2 || q.mesh.position.y < 0.3) { scene.remove(q.mesh); particles.splice(i, 1); } continue; }
    q.u += q.speed; q.mesh.position.lerpVectors(q.from, q.to, q.u); q.mesh.position.y += Math.sin(q.u * Math.PI) * q.lift;
    if (q.u >= 1) { scene.remove(q.mesh); particles.splice(i, 1); if (q.to.y === 7 && brain) brain.userData.flash = Math.max(brain.userData.flash || 0, 0.3); }
  }
  for (let i = labels.length - 1; i >= 0; i--) { const l = labels[i]; const age = now - l.born; l.sprite.position.y += l.rise; l.sprite.material.opacity = Math.max(0, 1 - age / l.ttl); if (age > l.ttl) { scene.remove(l.sprite); l.sprite.material.map.dispose(); labels.splice(i, 1); } }
  controls.update(); renderer.render(scene, camera);
}
