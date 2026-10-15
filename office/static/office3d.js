/* Agent HQ campus. A daylight corporate campus: the headquarters building in the centre with the brain in
   its glass atrium, one department wing per office around it, walkways between them. White walls, wood
   desks, soft screens, one muted accent per department, dark-on-light labels. Agents sit at desks, type
   while they work, walk to headquarters to recall or remember, and cross to a colleague to delegate.
   API on window.HQ3D: init, setRoster, setState, say, goBrain, goHome, goTo, pulse, reward, setBrain,
   resize, focus, floorView. */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const OFFICE_ORDER = ["front-desk", "job-hunt", "pm", "studio", "brand-sales", "trading", "ops"];
const ACCENT = { "front-desk": 0xc2558f, "job-hunt": 0x3b6fd6, "pm": 0xd98433, "studio": 0x7a5fcf, "brand-sales": 0xd4a52a, "trading": 0xc94a5c, "ops": 0x2e9c86, "research": 0x3a9bc9, "creative": 0xd06a9c };
const TITLE = { "front-desk": "Front Desk", "job-hunt": "Job Hunt", "pm": "Project Office", "studio": "Studio", "brand-sales": "Brand & Sales", "trading": "Trading Desk", "ops": "Operations" };
const STATE_COLOR = { idle: 0x9aa3b5, think: 0x3b6fd6, tool: 0xd98433, delegate: 0x7a5fcf, done: 0x2e9c86, error: 0xc94a5c };
const SKIN = [0xf3cfae, 0xe0b08a, 0xc48e63, 0x9c6a45, 0x6f4a30, 0xf7dcc0];
const TOPS = [0x2d3f6b, 0xf2f2f2, 0x6b7a99, 0x8fb0d9, 0xd9c7b0, 0x3f3f4a, 0xb9d3c2, 0xe6b3b3, 0x4a6b8a, 0xf0d9a8];
const HAIR = [0x1d140e, 0x3b2616, 0x6b3f22, 0xb8842d, 0x2a2a2a, 0x8a8a8a, 0xc24b2f];

let renderer, scene, camera, controls, container, clock, raycaster, mouse;
let roomGroups = {}, figures = {}, brain, brainRings = [], brainLight, particles = [], labels = [], tradingRoom = null, opts = {}, lastFrame = 0, hovered = null;

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
function signTexture(text, accentHex) {
  const c = document.createElement("canvas"); c.width = 1024; c.height = 192; const g = c.getContext("2d");
  g.fillStyle = "#f7f7f5"; g.fillRect(0, 0, 1024, 192); g.fillStyle = "#" + accentHex.toString(16).padStart(6, "0"); g.fillRect(0, 172, 1024, 20);
  g.font = "700 76px -apple-system, Inter, system-ui, sans-serif"; g.fillStyle = "#1b2130"; g.textBaseline = "middle"; g.textAlign = "center"; g.fillText(text, 512, 88);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
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
  ground: new THREE.MeshStandardMaterial({ color: 0xd6d8d3, roughness: 0.92, metalness: 0 }),
  path: new THREE.MeshStandardMaterial({ color: 0xc3c6c0, roughness: 0.95 }),
  grass: new THREE.MeshStandardMaterial({ color: 0x8fb57a, roughness: 1 }),
  wall: new THREE.MeshStandardMaterial({ color: 0xf2f1ec, roughness: 0.85 }),
  wallDark: new THREE.MeshStandardMaterial({ color: 0x4a5160, roughness: 0.7, metalness: 0.2 }),
  roof: new THREE.MeshStandardMaterial({ color: 0xe6e6e2, roughness: 0.9 }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0xcfe3f2, transmission: 0.9, opacity: 0.3, transparent: true, roughness: 0.08, metalness: 0, thickness: 0.4, side: THREE.DoubleSide, depthWrite: false }),
  frame: new THREE.MeshStandardMaterial({ color: 0x3a4150, roughness: 0.5, metalness: 0.6 }),
  carpet: new THREE.MeshStandardMaterial({ color: 0xb9c3cf, roughness: 1 }),
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

/* ----------------------------------------------------------------------------- init */
export function init(el, options = {}) {
  container = el; opts = options; clock = new THREE.Clock();
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1)); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0; renderer.outputColorSpace = THREE.SRGBColorSpace;
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene(); scene.background = new THREE.Color(0xdbe6f3); scene.fog = new THREE.Fog(0xdbe6f3, 220, 460);
  camera = new THREE.PerspectiveCamera(36, 1, 0.5, 900); camera.position.set(0, 92, 118);
  controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.dampingFactor = 0.07;
  controls.maxPolarAngle = Math.PI / 2.4; controls.minPolarAngle = 0.25; controls.minDistance = 20; controls.maxDistance = 260; controls.target.set(0, 2, -4);
  raycaster = new THREE.Raycaster(); mouse = new THREE.Vector2();
  scene.add(new THREE.HemisphereLight(0xeaf2ff, 0x8a8f86, 0.95));
  const sun = new THREE.DirectionalLight(0xfff2e0, 2.2); sun.position.set(70, 120, 50); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); Object.assign(sun.shadow.camera, { left: -110, right: 110, top: 110, bottom: -110, far: 320 }); sun.shadow.bias = -0.0005; sun.shadow.radius = 3; scene.add(sun);
  const fill = new THREE.DirectionalLight(0xcfe0ff, 0.5); fill.position.set(-60, 40, -50); scene.add(fill);
  const ground = new THREE.Mesh(new THREE.CircleGeometry(160, 96), M.ground); ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
  const lawn = new THREE.Mesh(new THREE.RingGeometry(70, 160, 96), M.grass); lawn.rotation.x = -Math.PI / 2; lawn.position.y = 0.02; lawn.receiveShadow = true; scene.add(lawn);
  const plaza = new THREE.Mesh(new THREE.CircleGeometry(24, 64), M.path); plaza.rotation.x = -Math.PI / 2; plaza.position.y = 0.03; plaza.receiveShadow = true; scene.add(plaza);
  const grid = new THREE.GridHelper(140, 28, 0xc4c7c1, 0xcfd2cc); grid.position.y = 0.04; grid.material.transparent = true; grid.material.opacity = 0.35; scene.add(grid);
  for (let i = 0; i < 26; i++) { const a = (i / 26) * Math.PI * 2 + 0.1, r = 82 + (i % 3) * 14; const tree = new THREE.Group(); const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.7, 5, 8), M.trunk); trunk.position.y = 2.5; trunk.castShadow = true; tree.add(trunk);
    const c1 = new THREE.Mesh(new THREE.SphereGeometry(3.4 + (i % 2), 12, 10), M.canopy); c1.position.y = 7; c1.castShadow = true; tree.add(c1); tree.position.set(r * Math.cos(a), 0, r * Math.sin(a)); scene.add(tree); }
  buildHQ();
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
export function floorView(on) { setTimeout(resize, 30); if (on) { camera.position.set(0, 84, 110); controls.target.set(0, 2, -4); } }
function pick(e) {
  const r = renderer.domElement.getBoundingClientRect();
  mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(Object.values(figures).map(f => f.group), true);
  if (!hits.length) return null; let o = hits[0].object; while (o && !o.userData.agent) o = o.parent; return o ? figures[o.userData.agent] : null;
}

/* ----------------------------------------------------------------------------- headquarters */
function buildHQ() {
  const hq = new THREE.Group();
  const podium = new THREE.Mesh(new THREE.CylinderGeometry(15, 16, 1.2, 48), M.wallDark); podium.position.y = 0.6; podium.receiveShadow = true; podium.castShadow = true; hq.add(podium);
  const steps = new THREE.Mesh(new THREE.CylinderGeometry(17.5, 18.5, 0.5, 48), M.path); steps.position.y = 0.25; steps.receiveShadow = true; hq.add(steps);
  const atrium = new THREE.Mesh(new THREE.CylinderGeometry(12.5, 12.5, 15, 48, 1, true), M.glass); atrium.position.y = 8.7; hq.add(atrium);
  for (let i = 0; i < 16; i++) { const a = (i / 16) * Math.PI * 2; const rib = box(0.45, 15, 0.45, M.wall); rib.position.set(12.5 * Math.cos(a), 8.7, 12.5 * Math.sin(a)); hq.add(rib); }
  const ringA = new THREE.Mesh(new THREE.TorusGeometry(12.6, 0.35, 8, 64), M.wall); ringA.rotation.x = Math.PI / 2; ringA.position.y = 8.7; hq.add(ringA);
  const roof = new THREE.Mesh(new THREE.CylinderGeometry(14.5, 13.5, 1.4, 48), M.roof); roof.position.y = 16.9; roof.castShadow = true; roof.receiveShadow = true; hq.add(roof);
  const crown = new THREE.Mesh(new THREE.CylinderGeometry(7, 7.5, 6, 48), M.wall); crown.position.y = 20.5; crown.castShadow = true; hq.add(crown);
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.25, 9, 8), M.frame); mast.position.y = 28; hq.add(mast);
  const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.45, 10, 8), M.light(0xc94a5c, 1.2)); beacon.position.y = 32.6; hq.add(beacon);
  for (let i = 0; i < 4; i++) { const sign = new THREE.Mesh(new THREE.PlaneGeometry(9, 1.7), new THREE.MeshStandardMaterial({ map: signTexture("AGENT HQ", 0x3b6fd6), roughness: 0.8 })); const a = i * Math.PI / 2; sign.position.set(7.6 * Math.sin(a), 22.4, 7.6 * Math.cos(a)); sign.rotation.y = a; hq.add(sign); }
  brain = new THREE.Group(); brain.position.set(0, 8.5, 0);
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(3.4, 4), new THREE.MeshStandardMaterial({ color: 0x8fc2ff, emissive: 0x5a9cf0, emissiveIntensity: 1.1, roughness: 0.25, metalness: 0.1 })); brain.add(core); brain.userData.core = core;
  const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(4.6, 1), new THREE.MeshBasicMaterial({ color: 0x8fc2ff, wireframe: true, transparent: true, opacity: 0.18 })); brain.add(shell); brain.userData.shell = shell;
  for (let i = 0; i < 2; i++) { const t = new THREE.Mesh(new THREE.TorusGeometry(6.2 + i * 1.4, 0.12, 8, 96), M.frame); t.rotation.set(Math.PI / 2 + i * 0.6, i * 0.9, 0); brain.add(t); brainRings.push(t); }
  brainLight = new THREE.PointLight(0x7fb3ff, 25, 40, 1.8); brainLight.position.set(0, 1, 0); brain.add(brainLight);
  const plinth = new THREE.Mesh(new THREE.CylinderGeometry(2.2, 3, 2.5, 32), M.wallDark); plinth.position.y = -6.2; brain.add(plinth);
  const lbl = textSprite("HEADQUARTERS · the brain", { size: 24 }); lbl.position.set(0, 27, 0); brain.add(lbl); brain.userData.label = lbl;
  hq.add(brain); scene.add(hq);
  for (let i = 0; i < 4; i++) { const a = i * Math.PI / 2 + Math.PI / 4; const canopy = box(5, 0.3, 3, M.roof); canopy.position.set(15 * Math.cos(a), 4.2, 15 * Math.sin(a)); canopy.rotation.y = -a; hq.add(canopy); }
}
export function setBrain(count) {
  if (!brain) return; const old = brain.userData.label; brain.remove(old); old.material.map.dispose();
  const lbl = textSprite(`HEADQUARTERS · ${count} notes in the brain`, { size: 24 }); lbl.position.set(0, 27, 0); brain.add(lbl); brain.userData.label = lbl;
}

/* ----------------------------------------------------------------------------- department wings */
export function setRoster(list) {
  Object.values(roomGroups).forEach(g => scene.remove(g)); Object.values(figures).forEach(f => { scene.remove(f.group); scene.remove(f.label); if (f.bubbleSprite) scene.remove(f.bubbleSprite); });
  roomGroups = {}; figures = {}; labels = [];
  const byOffice = {}; list.forEach(a => (byOffice[a.office] = byOffice[a.office] || []).push(a));
  const names = Object.keys(byOffice).sort((a, b) => (OFFICE_ORDER.indexOf(a) + 99) % 100 - (OFFICE_ORDER.indexOf(b) + 99) % 100);
  const n = names.length; const R = 50;
  names.forEach((name, i) => {
    const members = byOffice[name]; const cols = Math.min(4, Math.ceil(Math.sqrt(members.length))), rows = Math.ceil(members.length / cols);
    const w = cols * 7 + 7, d = rows * 7.5 + 8; const ang = -Math.PI / 2 + (i / n) * Math.PI * 2;
    const g = new THREE.Group(); g.position.set(R * Math.cos(ang), 0, R * Math.sin(ang)); g.rotation.y = Math.PI / 2 - ang;
    const accent = ACCENT[name] || 0x3b6fd6;
    const slab = box(w + 1, 0.8, d + 1, M.wallDark); slab.position.y = 0.4; g.add(slab);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(w, d), M.carpet); floor.rotation.x = -Math.PI / 2; floor.position.y = 0.81; floor.receiveShadow = true; g.add(floor);
    const H = 6;
    // dollhouse cut: three walls, no roof, a parapet in the department colour, the front open towards HQ
    const backWall = box(w, H, 0.5, M.wall); backWall.position.set(0, 0.8 + H / 2, -d / 2); g.add(backWall);
    for (const sx of [-1, 1]) { const side = box(0.5, H, d * 0.55, M.wall); side.position.set(sx * w / 2, 0.8 + H / 2, -d * 0.225); g.add(side);
      const sideGlass = new THREE.Mesh(new THREE.PlaneGeometry(d * 0.45, H - 0.4), M.glass); sideGlass.rotation.y = Math.PI / 2; sideGlass.position.set(sx * w / 2, 0.8 + H / 2, d * 0.275); g.add(sideGlass);
      const mull = box(0.3, H, 0.3, M.frame); mull.position.set(sx * w / 2, 0.8 + H / 2, d / 2); g.add(mull);
      const parapetSide = box(0.7, 0.35, d + 0.7, M.accentBand(accent)); parapetSide.position.set(sx * w / 2, 0.8 + H + 0.17, 0); g.add(parapetSide); }
    const parapetBack = box(w + 0.7, 0.35, 0.7, M.accentBand(accent)); parapetBack.position.set(0, 0.8 + H + 0.17, -d / 2); g.add(parapetBack);
    const lintel = box(w + 0.7, 0.35, 0.7, M.accentBand(accent)); lintel.position.set(0, 0.8 + H + 0.17, d / 2); g.add(lintel);
    const sign = textSprite(TITLE[name] || name, { size: 34, accent: "#" + accent.toString(16).padStart(6, "0") }); sign.position.set(0, 0.8 + H + 4.2, d / 2); g.add(sign);
    const sw = Math.min(w - 4, 11), sh = sw / 2; const tex = screenTexture(name, accent);
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(sw, sh), new THREE.MeshStandardMaterial({ map: tex, emissive: 0xffffff, emissiveMap: tex, emissiveIntensity: 0.35, roughness: 0.4 }));
    screen.position.set(0, 0.8 + 2.3 + sh / 2, -d / 2 + 0.46); g.add(screen);
    const bezel = box(sw + 0.5, sh + 0.5, 0.2, M.monitor); bezel.position.set(0, 0.8 + 2.3 + sh / 2, -d / 2 + 0.22); g.add(bezel);
    for (const sx of [-1, 1]) { const plant = new THREE.Group(); const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.6, 1.3, 14), M.pot); pot.position.y = 1.45; plant.add(pot); for (let k = 0; k < 5; k++) { const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.75, 10, 8), M.plant); leaf.position.set(Math.cos(k * 1.26) * 0.55, 2.7 + (k % 2) * 0.4, Math.sin(k * 1.26) * 0.55); leaf.castShadow = true; plant.add(leaf); } plant.position.set(sx * (w / 2 - 1.8), 0.8, -d / 2 + 1.9); g.add(plant); }
    if (name === "front-desk") { const counter = box(6.5, 2.6, 1.6, M.wall); counter.position.set(0, 2.1, d / 2 - 2.4); g.add(counter); const ctop = box(6.9, 0.2, 2.0, M.wood); ctop.position.set(0, 3.5, d / 2 - 2.4); g.add(ctop); const strip = box(6.1, 0.25, 0.1, M.accentBand(accent)); strip.position.set(0, 2.3, d / 2 - 1.55); g.add(strip); }
    const L = R - d / 2 - 17;
    const walk = new THREE.Mesh(new THREE.PlaneGeometry(4, L), M.path); walk.rotation.x = -Math.PI / 2; walk.position.set(0, 0.05, d / 2 + L / 2 + 0.5); walk.receiveShadow = true; g.add(walk);
    for (const sx of [-1, 1]) { const kerb = box(0.25, 0.25, L, M.wallDark); kerb.position.set(sx * 2.1, 0.12, d / 2 + L / 2 + 0.5); g.add(kerb); }
    const corridor = new THREE.Mesh(new THREE.BoxGeometry(4.8, 4.2, L), M.glass); corridor.position.set(0, 2.2, d / 2 + L / 2 + 0.5); g.add(corridor);
    for (let k = 0; k <= Math.floor(L / 5); k++) { for (const sx of [-1, 1]) { const post = box(0.22, 4.2, 0.22, M.frame); post.position.set(sx * 2.4, 2.2, d / 2 + 0.5 + k * 5); g.add(post); } }
    const corridorRoof = box(5.2, 0.25, L, M.roof); corridorRoof.position.set(0, 4.4, d / 2 + L / 2 + 0.5); g.add(corridorRoof);
    for (let k = 0; k < 2; k++) { const lamp = new THREE.Group(); const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 4.5, 8), M.frame); pole.position.y = 2.25; lamp.add(pole); const head = new THREE.Mesh(new THREE.SphereGeometry(0.3, 8, 8), M.light(0xfff4dc, 0.6)); head.position.y = 4.6; lamp.add(head); lamp.position.set(2.8, 0, d / 2 + 4 + k * 8); g.add(lamp); }
    const count = textSprite(`${members.length} agent${members.length > 1 ? "s" : ""}`, { size: 19, bold: false, bg: "rgba(255,255,255,.85)" }); count.position.set(0, 0.8 + H + 2.4, d / 2); g.add(count);
    g.userData = { name, w, d, accent }; scene.add(g); roomGroups[name] = g; if (name === "trading") tradingRoom = g;
    members.forEach((a, k) => {
      const cx = (k % cols - (cols - 1) / 2) * 7, cz = (Math.floor(k / cols) - (rows - 1) / 2) * 7.5 - 1.2;
      addDesk(g, cx, cz);
      const seat = new THREE.Vector3(cx, 0.8, cz + 2.0); const world = g.localToWorld(seat.clone());
      const fig = makeFigure(a, k, accent); fig.group.position.copy(world); fig.group.rotation.y = g.rotation.y;
      fig.home = world.clone(); fig.homeRot = g.rotation.y; fig.room = g; scene.add(fig.group);
      fig.label = textSprite(a.name, { size: 21, accent: "#" + accent.toString(16).padStart(6, "0") }); fig.label.position.copy(world).add(new THREE.Vector3(0, 7.6, 0)); scene.add(fig.label);
      figures[a.name] = fig;
    });
  });
}

function addDesk(g, x, z) {
  const top = box(5.4, 0.22, 2.6, M.wood); top.position.set(x, 2.65, z); g.add(top);
  for (const sx of [-1, 1]) { const leg = box(0.25, 1.9, 2.2, M.deskLeg); leg.position.set(x + sx * 2.5, 1.75, z); g.add(leg); }
  const mon = box(2.9, 1.75, 0.14, M.monitor); mon.position.set(x, 3.85, z - 0.85); g.add(mon);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(2.65, 1.5), M.screen); scr.position.set(x, 3.85, z - 0.77); g.add(scr);
  const stand = box(0.35, 0.9, 0.35, M.monitor); stand.position.set(x, 3.1, z - 0.85); g.add(stand);
  const kb = box(1.8, 0.1, 0.6, M.deskLeg); kb.position.set(x, 2.82, z + 0.35); g.add(kb);
  const mouse = box(0.35, 0.12, 0.5, M.deskLeg); mouse.position.set(x + 1.4, 2.82, z + 0.4); g.add(mouse);
  const mug = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.2, 0.42, 12), new THREE.MeshStandardMaterial({ color: [0xffffff, 0xc94a5c, 0x3b6fd6][Math.abs(Math.round(x + z)) % 3] })); mug.position.set(x - 1.9, 2.97, z + 0.2); g.add(mug);
  const seat = box(1.7, 0.3, 1.7, M.chair); seat.position.set(x, 1.85, z + 2.0); g.add(seat);
  const back = box(1.7, 2.1, 0.3, M.chair); back.position.set(x, 3.05, z + 2.85); g.add(back);
  const post = box(0.22, 1.1, 0.22, M.frame); post.position.set(x, 1.25, z + 2.0); g.add(post);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 0.1, 16), M.frame); base.position.set(x, 0.88, z + 2.0); g.add(base);
  const sh = disc(2.3, M.shadow); sh.position.set(x, 0.83, z + 0.6); sh.scale.set(1.4, 0.9, 1); g.add(sh);
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
  const fig = { name: a.name, group, body, legs, parts: { armL, armR, foreL, foreR, thL, thR, shL, shR, shoeL, shoeR, head, light, halo }, state: "idle", seated: true, target: null, bubbleSprite: null, bubbleUntil: 0, phase: Math.random() * 6, hover: false };
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

/* ----------------------------------------------------------------------------- public controls */
export function setState(name, state) { const f = figures[name]; if (!f) return; f.state = state; f.parts.light.material = M.light(STATE_COLOR[state] || STATE_COLOR.idle, state === "idle" ? 0.4 : 1.0); }
export function say(name, text, ms = 6000) {
  const f = figures[name]; if (!f) return;
  if (f.bubbleSprite) { scene.remove(f.bubbleSprite); f.bubbleSprite.material.map.dispose(); }
  f.bubbleSprite = textSprite(text.length > 46 ? text.slice(0, 44) + "…" : text, { size: 19, bold: false }); f.bubbleUntil = Date.now() + ms; scene.add(f.bubbleSprite);
}
export function goBrain(name) { const f = figures[name]; if (!f) return; const a = Math.random() * Math.PI * 2; f.target = new THREE.Vector3(20 * Math.cos(a), 0, 20 * Math.sin(a)); f.lookAt = new THREE.Vector3(0, 0, 0); }
export function goHome(name) { const f = figures[name]; if (!f) return; f.target = f.home.clone(); f.lookAt = null; }
export function goTo(name, other) { const f = figures[name], o = figures[other]; if (!f || !o) return; const dir = o.home.clone().sub(f.home).normalize(); f.target = o.home.clone().sub(dir.multiplyScalar(3.6)); f.lookAt = o.home.clone(); }
export function pulse(fromName, toBrain, color = 0x5a9cf0) {
  const f = figures[fromName]; if (!f) return;
  const from = toBrain ? f.group.position.clone().add(new THREE.Vector3(0, 4, 0)) : new THREE.Vector3(0, 8.5, 0);
  const to = toBrain ? new THREE.Vector3(0, 8.5, 0) : f.home.clone().add(new THREE.Vector3(0, 4, 0));
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.32, 8, 8), M.light(color, 1.2)); mesh.position.copy(from);
  particles.push({ from, to, u: 0, speed: 0.012 + Math.random() * 0.006, mesh, lift: 14 + Math.random() * 6 }); scene.add(mesh);
}
export function focus(name) { const f = figures[name]; if (!f) return; controls.target.copy(f.group.position).add(new THREE.Vector3(0, 2, 0)); }
export function reward(detail = {}) {
  const origin = tradingRoom ? tradingRoom.position.clone().add(new THREE.Vector3(0, 10, 0)) : new THREE.Vector3(0, 12, 0);
  for (let i = 0; i < 48; i++) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.35, 0.08), M.light(i % 3 ? 0xd4a52a : 0xfff0b3, 0.9)); m.position.copy(origin); m.rotation.set(Math.random() * 3, Math.random() * 3, 0);
    const vel = new THREE.Vector3(Math.random() - 0.5, 0.7 + Math.random() * 0.8, Math.random() - 0.5).normalize().multiplyScalar(0.22 + Math.random() * 0.3);
    particles.push({ from: origin.clone(), to: new THREE.Vector3(0, 8.5, 0), u: 0, speed: 0.01, mesh: m, lift: 12, gold: true, vel }); scene.add(m);
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
      if (dist < 0.3) { g.position.copy(f.target); g.position.y = f.home.y; const atHome = f.target.distanceTo(f.home) < 0.5; f.target = null;
        if (atHome) { g.rotation.y = f.homeRot; pose(f, true); } else if (f.lookAt) { const l = f.lookAt.clone().sub(g.position); g.rotation.y = Math.atan2(l.x, l.z); } }
      else { if (f.seated) pose(f, false); const step = Math.min(dist, dt * 13); g.position.add(d.normalize().multiplyScalar(step)); g.rotation.y = Math.atan2(d.x, d.z);
        const sw = Math.sin(t * 10 + f.phase) * 0.7; p.thL.rotation.x = sw; p.thR.rotation.x = -sw; p.shL.rotation.x = Math.max(0, -sw) * 0.8; p.shR.rotation.x = Math.max(0, sw) * 0.8; p.armL.rotation.x = -sw * 0.6; p.armR.rotation.x = sw * 0.6; g.position.y = 0.05 + Math.abs(Math.sin(t * 10 + f.phase)) * 0.14; }
    } else if (f.seated) {
      const working = f.state === "think" || f.state === "tool" || f.state === "delegate";
      if (working) { p.foreL.position.y = 2.55 + Math.sin(t * 17 + f.phase) * 0.09; p.foreR.position.y = 2.55 + Math.cos(t * 16 + f.phase) * 0.09; p.head.position.y = 4.6 + Math.sin(t * 2.3 + f.phase) * 0.03; p.head.rotation.x = -0.14; p.head.rotation.y = Math.sin(t * 1.1 + f.phase) * 0.08; }
      else { p.foreL.position.y = 2.55; p.foreR.position.y = 2.55; p.head.position.y = 4.6 + Math.sin(t * 1.2 + f.phase) * 0.04; p.head.rotation.x = Math.sin(t * 0.45 + f.phase) * 0.06; p.head.rotation.y = Math.sin(t * 0.3 + f.phase) * 0.3; }
      f.body.position.y = Math.sin(t * 1.4 + f.phase) * 0.025;
    } else if (f.lookAt) { p.foreR.rotation.x = -0.6 + Math.sin(t * 5 + f.phase) * 0.25; }
    p.light.scale.setScalar(f.state === "idle" ? 0.75 : 1 + 0.3 * Math.sin(t * 6 + f.phase));
    p.halo.material.opacity = f.hover ? 0.9 : f.state !== "idle" ? 0.35 + 0.2 * Math.sin(t * 4 + f.phase) : 0;
    f.label.position.copy(g.position).add(new THREE.Vector3(0, f.seated ? 7.3 : 7.9, 0));
    if (f.bubbleSprite) { if (Date.now() > f.bubbleUntil) { scene.remove(f.bubbleSprite); f.bubbleSprite.material.map.dispose(); f.bubbleSprite = null; } else f.bubbleSprite.position.copy(g.position).add(new THREE.Vector3(0, (f.seated ? 9.1 : 9.7) + Math.sin(t * 2) * 0.1, 0)); }
  }
  for (let i = particles.length - 1; i >= 0; i--) {
    const q = particles[i];
    if (q.gold) { q.mesh.position.add(q.vel); q.vel.y -= 0.012; q.vel.multiplyScalar(0.985); q.mesh.rotation.x += 0.2; q.u += dt * 0.5; if (q.u > 1.2 || q.mesh.position.y < 0.3) { scene.remove(q.mesh); particles.splice(i, 1); } continue; }
    q.u += q.speed; q.mesh.position.lerpVectors(q.from, q.to, q.u); q.mesh.position.y += Math.sin(q.u * Math.PI) * q.lift;
    if (q.u >= 1) { scene.remove(q.mesh); particles.splice(i, 1); if (q.to.y === 8.5 && brain) brain.userData.flash = Math.max(brain.userData.flash || 0, 0.3); }
  }
  for (let i = labels.length - 1; i >= 0; i--) { const l = labels[i]; const age = now - l.born; l.sprite.position.y += l.rise; l.sprite.material.opacity = Math.max(0, 1 - age / l.ttl); if (age > l.ttl) { scene.remove(l.sprite); l.sprite.material.map.dispose(); labels.splice(i, 1); } }
  controls.update(); renderer.render(scene, camera);
}
