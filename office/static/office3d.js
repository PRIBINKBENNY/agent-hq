/* Agent HQ 3D office. Rooms on a ring around the brain core; each agent is a rounded low-poly character
   seated at a glowing desk, typing while it works, walking to the brain to recall or remember, crossing to a
   colleague to delegate. Warm key light, cool fill, bloom on neon and screens, a reflective floor, contact
   shadows, room-specific wall displays. API on window.HQ3D: init, setRoster, setState, say, goBrain, goHome,
   goTo, pulse, reward, setBrain, resize, focus, floorView. */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { Reflector } from "three/addons/objects/Reflector.js";

const OFFICE_ORDER = ["front-desk", "job-hunt", "pm", "studio", "brand-sales", "trading", "ops"];
const ACCENT = { "front-desk": 0xff5fd1, "job-hunt": 0x4f8dff, "pm": 0xff9a3c, "studio": 0x9b6bff, "brand-sales": 0xffd23f, "trading": 0xff4d6a, "ops": 0x2fd3b5, "research": 0x4fd0ff, "creative": 0xff6fb5 };
const TITLE = { "front-desk": "Front Desk", "job-hunt": "Job Hunt", "pm": "Project Office", "studio": "Studio", "brand-sales": "Brand & Sales", "trading": "Trading Desk · financial hub", "ops": "Operations" };
const STATE_COLOR = { idle: 0x55607a, think: 0x5b8def, tool: 0xe0a93b, delegate: 0xa67cf0, done: 0x3ec28f, error: 0xef5b6e };
const SKIN = [0xf3cfae, 0xe0b08a, 0xc48e63, 0x9c6a45, 0x6f4a30, 0xf7dcc0];
const TOPS = [0x3a63d8, 0xd85a5a, 0x2fae8a, 0xf0a63c, 0x8a5be0, 0xe85d9a, 0x5bb0e8, 0xececec, 0x2a2f45, 0xc9a34a];
const HAIR = [0x1d140e, 0x3b2616, 0x6b3f22, 0xb8842d, 0x2a2a2a, 0x8a8a8a, 0xc24b2f];

let renderer, composer, bloom, scene, camera, controls, container, clock, raycaster, mouse, floorReflector;
let roomGroups = {}, figures = {}, brain, brainRings = [], brainLight, particles = [], labels = [], hubGlow = null, tradingRoom = null, opts = {}, lastFrame = 0, hovered = null;

/* ----------------------------------------------------------------------------- canvas textures */
function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
function textSprite(text, { size = 26, color = "#eef2ff", bg = "rgba(10,13,24,.82)", pad = 12, bold = true, accent } = {}) {
  const c = document.createElement("canvas"); const g = c.getContext("2d");
  g.font = `${bold ? "700" : "500"} ${size}px -apple-system, Inter, system-ui, sans-serif`;
  const w = Math.ceil(g.measureText(text).width + pad * 2 + (accent ? 18 : 0)), h = size + pad * 2;
  c.width = w * 2; c.height = h * 2; g.scale(2, 2);
  g.fillStyle = bg; roundRect(g, 0, 0, w, h, h / 2); g.fill();
  if (accent) { g.fillStyle = accent; g.beginPath(); g.arc(pad + 2, h / 2, 5, 0, Math.PI * 2); g.fill(); }
  g.font = `${bold ? "700" : "500"} ${size}px -apple-system, Inter, system-ui, sans-serif`; g.fillStyle = color; g.textBaseline = "middle"; g.textAlign = "left";
  g.fillText(text, pad + (accent ? 18 : 0), h / 2 + 1);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.minFilter = THREE.LinearFilter;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false })); sp.scale.set(w / 24, h / 24, 1); sp.renderOrder = 10; return sp;
}
function screenTexture(kind, accentHex) {
  const c = document.createElement("canvas"); c.width = 512; c.height = 256; const g = c.getContext("2d");
  const acc = "#" + accentHex.toString(16).padStart(6, "0");
  g.fillStyle = "#0a0f1e"; g.fillRect(0, 0, 512, 256);
  g.strokeStyle = "rgba(255,255,255,.06)"; for (let x = 0; x < 512; x += 32) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 256); g.stroke(); } for (let y = 0; y < 256; y += 32) { g.beginPath(); g.moveTo(0, y); g.lineTo(512, y); g.stroke(); }
  g.font = "700 16px system-ui"; g.fillStyle = acc; g.fillText((TITLE[kind] || kind).toUpperCase(), 14, 24);
  if (kind === "trading") {
    let p = 128; for (let i = 0; i < 40; i++) { const o = p, cl = Math.max(40, Math.min(230, o + (Math.random() - 0.48) * 26)); const hi = Math.max(o, cl) - Math.random() * 10, lo = Math.min(o, cl) + Math.random() * 10; const x = 16 + i * 12;
      g.strokeStyle = g.fillStyle = cl < o ? "#39d98a" : "#ff5a6e"; g.beginPath(); g.moveTo(x + 3, hi); g.lineTo(x + 3, lo); g.stroke(); g.fillRect(x, Math.min(o, cl), 6, Math.max(2, Math.abs(cl - o))); p = cl; }
    g.fillStyle = "rgba(255,255,255,.08)"; g.fillRect(0, 236, 512, 20); g.font = "600 13px ui-monospace"; g.fillStyle = "#ffd23f"; g.fillText("GOLD 4143.9 ▲0.6%   US500 7695 ▲0.2%   UK100 ▼0.1%   EURUSD 1.164   VODL 1.179", 8, 250);
  } else if (kind === "studio") {
    const cols = ["#9b6bff", "#5bb0e8", "#39d98a", "#ffd23f", "#eef2ff"]; for (let i = 0; i < 13; i++) { const y = 46 + i * 15; let x = 16 + (i % 3) * 20; for (let k = 0; k < 2 + (i * 7) % 4; k++) { const w = 18 + ((i * 13 + k * 29) % 70); g.fillStyle = cols[(i + k) % cols.length]; g.globalAlpha = 0.8; g.fillRect(x, y, w, 7); x += w + 10; } } g.globalAlpha = 1;
  } else if (kind === "pm") {
    ["TO DO", "DOING", "REVIEW", "DONE"].forEach((t, i) => { const x = 14 + i * 124; g.fillStyle = "rgba(255,255,255,.07)"; roundRect(g, x, 40, 112, 200, 8); g.fill(); g.font = "700 12px system-ui"; g.fillStyle = "#cfd6e6"; g.fillText(t, x + 8, 58); for (let k = 0; k < 2 + (i * 2) % 4; k++) { g.fillStyle = i === 3 ? "#39d98a" : i === 2 ? "#ffd23f" : "#ff9a3c"; g.globalAlpha = 0.85; roundRect(g, x + 8, 70 + k * 36, 96, 26, 5); g.fill(); g.globalAlpha = 1; } });
  } else if (kind === "job-hunt") {
    for (let i = 0; i < 6; i++) { const x = 14 + (i % 3) * 164, y = 44 + Math.floor(i / 3) * 100; g.fillStyle = "rgba(255,255,255,.07)"; roundRect(g, x, y, 150, 86, 8); g.fill(); g.fillStyle = acc; g.fillRect(x + 10, y + 12, 60, 8); g.fillStyle = "#cfd6e6"; g.fillRect(x + 10, y + 30, 120, 6); g.fillRect(x + 10, y + 44, 90, 6); g.fillStyle = "#39d98a"; g.font = "700 12px system-ui"; g.fillText("fit " + (3 + i % 3) + "/5", x + 10, y + 74); }
  } else if (kind === "brand-sales") {
    for (let i = 0; i < 3; i++) { const y = 44 + i * 64; g.fillStyle = "rgba(255,255,255,.07)"; roundRect(g, 14, y, 484, 54, 8); g.fill(); g.fillStyle = acc; g.beginPath(); g.arc(40, y + 27, 14, 0, Math.PI * 2); g.fill(); g.fillStyle = "#cfd6e6"; g.fillRect(66, y + 14, 200 + i * 40, 7); g.fillRect(66, y + 30, 320, 6); g.fillStyle = "#ff6fb5"; g.font = "700 12px system-ui"; g.fillText("♥ " + (120 + i * 87), 430, y + 34); }
  } else if (kind === "ops") {
    for (let i = 0; i < 7; i++) { const y = 50 + i * 27; g.strokeStyle = i < 4 ? "#39d98a" : "#55607a"; g.lineWidth = 2; g.strokeRect(16, y, 14, 14); if (i < 4) { g.beginPath(); g.moveTo(18, y + 7); g.lineTo(23, y + 12); g.lineTo(29, y + 2); g.stroke(); } g.fillStyle = i < 4 ? "#cfd6e6" : "#8a93a8"; g.fillRect(40, y + 4, 180 + (i * 53) % 200, 6); }
  } else {
    g.font = "800 44px system-ui"; g.fillStyle = "#eef2ff"; g.fillText("AGENT HQ", 24, 120); g.font = "500 18px system-ui"; g.fillStyle = acc; g.fillText("reception · one shared brain", 24, 156);
  }
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; return tex;
}

/* ----------------------------------------------------------------------------- materials */
const M = {
  slab: new THREE.MeshStandardMaterial({ color: 0x232a3d, roughness: 0.55, metalness: 0.25 }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0xbfe0ff, transmission: 0.9, opacity: 0.28, transparent: true, roughness: 0.05, metalness: 0, thickness: 0.3, side: THREE.DoubleSide, depthWrite: false }),
  frame: new THREE.MeshStandardMaterial({ color: 0x2a3148, roughness: 0.45, metalness: 0.8 }),
  deskTop: new THREE.MeshStandardMaterial({ color: 0xe8e2d6, roughness: 0.35, metalness: 0.05 }),
  deskSide: new THREE.MeshStandardMaterial({ color: 0x2b3350, roughness: 0.5, metalness: 0.3 }),
  chairPad: new THREE.MeshStandardMaterial({ color: 0x3b4664, roughness: 0.9 }),
  monitor: new THREE.MeshStandardMaterial({ color: 0x0a0d18, roughness: 0.35, metalness: 0.6 }),
  shadow: new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.45, depthWrite: false }),
  neon: (c, i = 2.4) => new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: i, roughness: 0.3 }),
  screen: (c, i = 1.4) => new THREE.MeshStandardMaterial({ color: 0x0a0f1e, emissive: c, emissiveIntensity: i, roughness: 0.2 }),
  plant: new THREE.MeshStandardMaterial({ color: 0x3aa860, roughness: 0.85 }), pot: new THREE.MeshStandardMaterial({ color: 0xd9c9b0, roughness: 0.8 }),
};
function box(w, h, d, mat, rounded = 0) { const geo = rounded ? roundedBox(w, h, d, rounded) : new THREE.BoxGeometry(w, h, d); const m = new THREE.Mesh(geo, mat); m.castShadow = true; m.receiveShadow = true; return m; }
function roundedBox(w, h, d, r) { const s = new THREE.Shape(); const x = -w / 2, y = -h / 2; s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r); s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  const g = new THREE.ExtrudeGeometry(s, { depth: d, bevelEnabled: true, bevelThickness: Math.min(r, 0.15), bevelSize: Math.min(r, 0.15), bevelSegments: 2 }); g.center(); return g; }
function disc(r, mat) { const m = new THREE.Mesh(new THREE.CircleGeometry(r, 24), mat); m.rotation.x = -Math.PI / 2; m.renderOrder = 1; return m; }

/* ----------------------------------------------------------------------------- init */
export function init(el, options = {}) {
  container = el; opts = options; clock = new THREE.Clock();
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1)); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.15; renderer.outputColorSpace = THREE.SRGBColorSpace;
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene(); scene.background = new THREE.Color(0x090c16); scene.fog = new THREE.Fog(0x090c16, 170, 330);
  camera = new THREE.PerspectiveCamera(38, 1, 0.5, 700); camera.position.set(0, 58, 88);
  controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.dampingFactor = 0.07;
  controls.maxPolarAngle = Math.PI / 2.3; controls.minPolarAngle = 0.3; controls.minDistance = 20; controls.maxDistance = 200; controls.target.set(0, 1, -2);
  raycaster = new THREE.Raycaster(); mouse = new THREE.Vector2();
  scene.add(new THREE.HemisphereLight(0xaac4ff, 0x1a1a22, 0.75));
  const key = new THREE.DirectionalLight(0xffe2c2, 1.9); key.position.set(55, 90, 45); key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048); Object.assign(key.shadow.camera, { left: -90, right: 90, top: 90, bottom: -90, far: 280 }); key.shadow.bias = -0.0006; key.shadow.radius = 4; scene.add(key);
  const fill = new THREE.DirectionalLight(0x8fb4ff, 0.7); fill.position.set(-60, 50, -40); scene.add(fill);
  floorReflector = new Reflector(new THREE.CircleGeometry(120, 96), { clipBias: 0.003, textureWidth: 1024, textureHeight: 1024, color: 0x3a4460 });
  floorReflector.rotation.x = -Math.PI / 2; floorReflector.position.y = -0.02; scene.add(floorReflector);
  // labels and bubbles must not be mirrored in the floor: hide every sprite while the reflector renders
  const origBefore = floorReflector.onBeforeRender.bind(floorReflector);
  floorReflector.onBeforeRender = (r, sc, cam, geo, mat, grp) => { const hidden = []; sc.traverse(o => { if (o.isSprite && o.visible) { o.visible = false; hidden.push(o); } }); try { origBefore(r, sc, cam, geo, mat, grp); } finally { hidden.forEach(o => o.visible = true); } };
  const tint = new THREE.Mesh(new THREE.CircleGeometry(120, 96), new THREE.MeshStandardMaterial({ color: 0x0c1120, roughness: 0.3, metalness: 0.6, transparent: true, opacity: 0.86 }));
  tint.rotation.x = -Math.PI / 2; tint.receiveShadow = true; scene.add(tint);
  const grid = new THREE.GridHelper(240, 48, 0x1c2742, 0x141c30); grid.position.y = 0.02; grid.material.transparent = true; grid.material.opacity = 0.45; scene.add(grid);
  const ring = new THREE.Mesh(new THREE.RingGeometry(119, 120.6, 128), M.neon(0x33539a, 1.6)); ring.rotation.x = -Math.PI / 2; ring.position.y = 0.05; scene.add(ring);
  const pts = []; for (let i = 0; i < 1600; i++) { const r = 230 + Math.random() * 120, t = Math.random() * Math.PI * 2, p = Math.random() * Math.PI / 2.1; pts.push(r * Math.cos(t) * Math.cos(p), 15 + r * Math.sin(p), r * Math.sin(t) * Math.cos(p)); }
  const sg = new THREE.BufferGeometry(); sg.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  scene.add(new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xbcd0ff, size: 1.1, transparent: true, opacity: 0.85 })));
  buildBrain();
  composer = new EffectComposer(renderer); composer.addPass(new RenderPass(scene, camera));
  bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.55, 0.45, 0.78); composer.addPass(bloom); composer.addPass(new OutputPass());
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
  camera.aspect = w / h; camera.updateProjectionMatrix(); composer.setSize(w, h); bloom.resolution.set(w, h);
}
export function floorView(on) { setTimeout(resize, 30); if (on) { camera.position.set(0, 52, 80); controls.target.set(0, 1, -2); } }

function pick(e) {
  const r = renderer.domElement.getBoundingClientRect();
  mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(Object.values(figures).map(f => f.group), true);
  if (!hits.length) return null; let o = hits[0].object; while (o && !o.userData.agent) o = o.parent; return o ? figures[o.userData.agent] : null;
}

/* ----------------------------------------------------------------------------- brain core */
function buildBrain() {
  brain = new THREE.Group(); brain.position.set(0, 6.5, 0);
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(2.8, 3), new THREE.MeshStandardMaterial({ color: 0x9fd0ff, emissive: 0x4f9cff, emissiveIntensity: 2.2, roughness: 0.1, metalness: 0.3 })); brain.add(core); brain.userData.core = core;
  const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(4.2, 1), new THREE.MeshBasicMaterial({ color: 0xbfe0ff, wireframe: true, transparent: true, opacity: 0.28 })); brain.add(shell); brain.userData.shell = shell;
  for (let i = 0; i < 3; i++) { const t = new THREE.Mesh(new THREE.TorusGeometry(6 + i * 1.5, 0.1, 8, 120), M.neon(i === 1 ? 0x8fe8ff : 0x5b8def, 1.8)); t.rotation.set(Math.PI / 2 + i * 0.55, i * 0.8, 0); brain.add(t); brainRings.push(t); }
  brainLight = new THREE.PointLight(0x6aa8ff, 90, 60, 1.5); brainLight.position.set(0, 2, 0); brain.add(brainLight);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(8.5, 10, 1, 64), M.frame); base.position.y = -6; base.receiveShadow = true; brain.add(base);
  const baseRing = new THREE.Mesh(new THREE.TorusGeometry(9.6, 0.16, 8, 120), M.neon(0x5b8def, 2)); baseRing.rotation.x = Math.PI / 2; baseRing.position.y = -5.45; brain.add(baseRing);
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.8, 70, 12, 1, true), new THREE.MeshBasicMaterial({ color: 0x8fc0ff, transparent: true, opacity: 0.07, side: THREE.DoubleSide, depthWrite: false })); beam.position.y = 30; brain.add(beam);
  const lbl = textSprite("THE BRAIN · shared memory", { size: 24 }); lbl.position.set(0, 12.5, 0); brain.add(lbl); brain.userData.label = lbl;
  scene.add(brain);
}
export function setBrain(count) {
  if (!brain) return; const old = brain.userData.label; brain.remove(old); old.material.map.dispose();
  const lbl = textSprite(`THE BRAIN · ${count} notes`, { size: 24 }); lbl.position.set(0, 12.5, 0); brain.add(lbl); brain.userData.label = lbl;
}

/* ----------------------------------------------------------------------------- rooms */
export function setRoster(list) {
  Object.values(roomGroups).forEach(g => scene.remove(g)); Object.values(figures).forEach(f => { scene.remove(f.group); scene.remove(f.label); if (f.bubbleSprite) scene.remove(f.bubbleSprite); });
  roomGroups = {}; figures = {}; labels = [];
  const byOffice = {}; list.forEach(a => (byOffice[a.office] = byOffice[a.office] || []).push(a));
  const names = Object.keys(byOffice).sort((a, b) => (OFFICE_ORDER.indexOf(a) + 99) % 100 - (OFFICE_ORDER.indexOf(b) + 99) % 100);
  const n = names.length; const R = 40;
  names.forEach((name, i) => {
    const members = byOffice[name]; const cols = Math.min(4, Math.ceil(Math.sqrt(members.length))), rows = Math.ceil(members.length / cols);
    const w = cols * 7 + 6, d = rows * 7.5 + 6; const ang = -Math.PI / 2 + (i / n) * Math.PI * 2;
    const g = new THREE.Group(); g.position.set(R * Math.cos(ang), 0, R * Math.sin(ang)); g.rotation.y = Math.PI / 2 - ang;
    const accent = ACCENT[name] || 0x5b8def; const acc = new THREE.Color(accent);
    const slab = box(w, 0.7, d, M.slab, 0.4); slab.position.y = 0.35; g.add(slab);
    const rug = new THREE.Mesh(new THREE.PlaneGeometry(w - 3, d - 3), new THREE.MeshStandardMaterial({ color: acc.clone().multiplyScalar(0.18).lerp(new THREE.Color(0x1a2033), 0.5), roughness: 0.95 })); rug.rotation.x = -Math.PI / 2; rug.position.y = 0.72; rug.receiveShadow = true; g.add(rug);
    const wallH = 7;
    const back = new THREE.Mesh(new THREE.PlaneGeometry(w, wallH), M.glass); back.position.set(0, wallH / 2 + 0.7, -d / 2); g.add(back);
    for (const sx of [-1, 1]) { const side = new THREE.Mesh(new THREE.PlaneGeometry(d * 0.72, wallH), M.glass); side.rotation.y = Math.PI / 2; side.position.set(sx * w / 2, wallH / 2 + 0.7, -d * 0.14); g.add(side); const post = box(0.3, wallH + 0.3, 0.3, M.frame); post.position.set(sx * w / 2, wallH / 2 + 0.7, -d / 2); g.add(post); const post2 = box(0.3, wallH + 0.3, 0.3, M.frame); post2.position.set(sx * w / 2, wallH / 2 + 0.7, d * 0.22); g.add(post2); }
    const topStrip = box(w + 0.5, 0.22, 0.22, M.neon(accent, 2.6)); topStrip.position.set(0, wallH + 0.85, -d / 2); g.add(topStrip);
    const edge = new THREE.Mesh(new THREE.PlaneGeometry(w + 0.8, 0.4), M.neon(accent, 2.2)); edge.rotation.x = -Math.PI / 2; edge.position.set(0, 0.73, d / 2 + 0.15); g.add(edge);
    const sw = Math.min(w - 3, 11), sh = sw / 2;
    const screenFrame = box(sw + 0.4, sh + 0.4, 0.25, M.monitor); screenFrame.position.set(0, 1.2 + sh / 2 + 2.2, -d / 2 + 0.3); g.add(screenFrame);
    const tex = screenTexture(name, accent);
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(sw, sh), new THREE.MeshStandardMaterial({ map: tex, emissive: 0xffffff, emissiveMap: tex, emissiveIntensity: 0.9, roughness: 0.3 }));
    screen.position.set(0, 1.2 + sh / 2 + 2.2, -d / 2 + 0.44); g.add(screen);
    const spot = new THREE.SpotLight(0xfff0dc, 70, 50, Math.PI / 3.2, 0.6, 1.4); spot.position.set(0, 14, 0); spot.target.position.set(0, 0, 0); g.add(spot); g.add(spot.target);
    const glow = new THREE.PointLight(accent, 22, 30, 1.8); glow.position.set(0, 6, -d / 2 + 1.5); g.add(glow);
    for (const sx of [-1, 1]) { const plant = new THREE.Group(); const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.6, 1.3, 14), M.pot); pot.position.y = 1.35; plant.add(pot); for (let k = 0; k < 5; k++) { const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.75, 10, 8), M.plant); leaf.position.set(Math.cos(k * 1.26) * 0.55, 2.6 + (k % 2) * 0.4, Math.sin(k * 1.26) * 0.55); leaf.castShadow = true; plant.add(leaf); } plant.position.set(sx * (w / 2 - 1.6), 0.7, -d / 2 + 1.7); g.add(plant); }
    if (name === "front-desk") { const counter = box(6, 2.6, 1.6, M.deskSide, 0.3); counter.position.set(0, 2.0, d / 2 - 2.2); g.add(counter); const ctop = box(6.4, 0.2, 2.0, M.deskTop); ctop.position.set(0, 3.4, d / 2 - 2.2); g.add(ctop); const logo = box(5.6, 0.3, 0.1, M.neon(accent, 2.2)); logo.position.set(0, 2.2, d / 2 - 1.35); g.add(logo); }
    const title = textSprite(TITLE[name] || name, { size: 30, accent: "#" + accent.toString(16).padStart(6, "0") }); title.position.set(0, wallH + 3.4, -d / 2); g.add(title);
    const count = textSprite(`${members.length} agent${members.length > 1 ? "s" : ""}`, { size: 20, bold: false, bg: "rgba(10,13,24,.6)" }); count.position.set(0, wallH + 1.9, -d / 2); g.add(count);
    g.userData = { name, w, d, accent }; scene.add(g); roomGroups[name] = g; if (name === "trading") tradingRoom = g;
    members.forEach((a, k) => {
      const cx = (k % cols - (cols - 1) / 2) * 7, cz = (Math.floor(k / cols) - (rows - 1) / 2) * 7.5 - 1;
      addDesk(g, cx, cz, accent);
      const seat = new THREE.Vector3(cx, 0.7, cz + 2.0); const world = g.localToWorld(seat.clone());
      const fig = makeFigure(a, k, accent); fig.group.position.copy(world); fig.group.rotation.y = g.rotation.y;
      fig.home = world.clone(); fig.homeRot = g.rotation.y; fig.room = g; scene.add(fig.group);
      fig.label = textSprite(a.name, { size: 21, accent: "#" + accent.toString(16).padStart(6, "0") }); fig.label.position.copy(world).add(new THREE.Vector3(0, 7.6, 0)); scene.add(fig.label);
      figures[a.name] = fig;
    });
  });
  if (!hubGlow) { hubGlow = new THREE.Mesh(new THREE.RingGeometry(0.9, 1, 64), new THREE.MeshBasicMaterial({ color: 0xffd23f, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false })); hubGlow.rotation.x = -Math.PI / 2; hubGlow.position.y = 0.8; scene.add(hubGlow); }
}

function addDesk(g, x, z, accent) {
  const top = box(5.4, 0.22, 2.6, M.deskTop, 0.12); top.position.set(x, 2.55, z); g.add(top);
  const under = box(5.0, 0.5, 2.2, M.deskSide); under.position.set(x, 2.2, z); g.add(under);
  for (const sx of [-1, 1]) { const leg = box(0.22, 2.0, 2.0, M.frame); leg.position.set(x + sx * 2.5, 1.7, z); g.add(leg); }
  const mon = box(2.9, 1.75, 0.14, M.monitor, 0.08); mon.position.set(x, 3.75, z - 0.85); g.add(mon);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(2.65, 1.5), M.screen(new THREE.Color(accent).lerp(new THREE.Color(0x9fd0ff), 0.55), 1.3)); scr.position.set(x, 3.75, z - 0.77); g.add(scr);
  const stand = box(0.35, 0.9, 0.35, M.monitor); stand.position.set(x, 3.0, z - 0.85); g.add(stand);
  const kb = box(1.8, 0.1, 0.6, M.monitor, 0.04); kb.position.set(x, 2.72, z + 0.35); g.add(kb);
  const mouse = box(0.35, 0.12, 0.5, M.monitor, 0.05); mouse.position.set(x + 1.4, 2.72, z + 0.4); g.add(mouse);
  const mug = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.2, 0.42, 12), new THREE.MeshStandardMaterial({ color: [0xffffff, 0xff6b6b, 0x5bb0e8][Math.abs(Math.round(x + z)) % 3] })); mug.position.set(x - 1.9, 2.87, z + 0.2); g.add(mug);
  const seat = box(1.7, 0.3, 1.7, M.chairPad, 0.2); seat.position.set(x, 1.75, z + 2.0); g.add(seat);
  const back = box(1.7, 2.1, 0.3, M.chairPad, 0.2); back.position.set(x, 2.95, z + 2.85); g.add(back);
  const post = box(0.22, 1.1, 0.22, M.frame); post.position.set(x, 1.15, z + 2.0); g.add(post);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 0.1, 16), M.frame); base.position.set(x, 0.78, z + 2.0); g.add(base);
  const sh = disc(2.3, M.shadow); sh.position.set(x, 0.74, z + 0.6); sh.scale.set(1.4, 0.9, 1); g.add(sh);
}

/* ----------------------------------------------------------------------------- characters */
function capsule(r, len, mat) { const m = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 6, 12), mat); m.castShadow = true; return m; }
function makeFigure(a, k, accent) {
  const group = new THREE.Group(); group.userData.agent = a.name;
  const seed = [...a.name].reduce((s, ch) => s + ch.charCodeAt(0), 0) + k;
  const skin = new THREE.MeshStandardMaterial({ color: SKIN[seed % SKIN.length], roughness: 0.6 });
  const top = new THREE.MeshStandardMaterial({ color: TOPS[(seed * 7) % TOPS.length], roughness: 0.7 });
  const trousers = new THREE.MeshStandardMaterial({ color: [0x1f2538, 0x2b2b33, 0x3a3f5c, 0x5a4a3a][seed % 4], roughness: 0.85 });
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
  const foreL = capsule(0.18, 0.75, skin); foreL.position.set(-0.95, 2.55, -0.6); foreL.rotation.x = -Math.PI / 2.3; body.add(foreL);
  const foreR = capsule(0.18, 0.75, skin); foreR.position.set(0.95, 2.55, -0.6); foreR.rotation.x = -Math.PI / 2.3; body.add(foreR);
  const legs = new THREE.Group(); group.add(legs);
  const thL = capsule(0.3, 1.0, trousers), thR = capsule(0.3, 1.0, trousers), shL = capsule(0.26, 1.0, trousers), shR = capsule(0.26, 1.0, trousers); legs.add(thL, thR, shL, shR);
  const shoeMat = new THREE.MeshStandardMaterial({ color: 0x15171f, roughness: 0.6 }); const shoeL = box(0.5, 0.25, 0.85, shoeMat, 0.1), shoeR = box(0.5, 0.25, 0.85, shoeMat, 0.1); legs.add(shoeL, shoeR);
  const light = new THREE.Mesh(new THREE.SphereGeometry(0.2, 10, 8), M.neon(STATE_COLOR.idle, 1.6)); light.position.y = 5.65; group.add(light);
  const halo = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.15, 32), new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false })); halo.rotation.x = -Math.PI / 2; halo.position.y = 0.05; group.add(halo);
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
export function setState(name, state) { const f = figures[name]; if (!f) return; f.state = state; f.parts.light.material = M.neon(STATE_COLOR[state] || STATE_COLOR.idle, 1.8); }
export function say(name, text, ms = 6000) {
  const f = figures[name]; if (!f) return;
  if (f.bubbleSprite) { scene.remove(f.bubbleSprite); f.bubbleSprite.material.map.dispose(); }
  f.bubbleSprite = textSprite(text.length > 46 ? text.slice(0, 44) + "…" : text, { size: 19, bg: "rgba(18,24,42,.94)", bold: false }); f.bubbleUntil = Date.now() + ms; scene.add(f.bubbleSprite);
}
export function goBrain(name) { const f = figures[name]; if (!f) return; const a = Math.random() * Math.PI * 2; f.target = new THREE.Vector3(12.5 * Math.cos(a), 0, 12.5 * Math.sin(a)); f.lookAt = new THREE.Vector3(0, 0, 0); }
export function goHome(name) { const f = figures[name]; if (!f) return; f.target = f.home.clone(); f.lookAt = null; }
export function goTo(name, other) { const f = figures[name], o = figures[other]; if (!f || !o) return; const dir = o.home.clone().sub(f.home).normalize(); f.target = o.home.clone().sub(dir.multiplyScalar(3.6)); f.lookAt = o.home.clone(); }
export function pulse(fromName, toBrain, color = 0x9cc3ff) {
  const f = figures[fromName]; if (!f) return;
  const from = toBrain ? f.group.position.clone().add(new THREE.Vector3(0, 4, 0)) : new THREE.Vector3(0, 6.5, 0);
  const to = toBrain ? new THREE.Vector3(0, 6.5, 0) : f.home.clone().add(new THREE.Vector3(0, 4, 0));
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.32, 8, 8), M.neon(color, 2.6)); mesh.position.copy(from);
  particles.push({ from, to, u: 0, speed: 0.012 + Math.random() * 0.006, mesh, lift: 9 + Math.random() * 6 }); scene.add(mesh);
}
export function focus(name) { const f = figures[name]; if (!f) return; controls.target.copy(f.group.position).add(new THREE.Vector3(0, 2, 0)); }
export function reward(detail = {}) {
  const origin = tradingRoom ? tradingRoom.position.clone().add(new THREE.Vector3(0, 6, 0)) : new THREE.Vector3(0, 7, 0);
  for (let i = 0; i < 48; i++) {
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.26, 6, 6), M.neon(i % 3 ? 0xffd23f : 0xfff1b0, 3)); m.position.copy(origin);
    const vel = new THREE.Vector3(Math.random() - 0.5, 0.7 + Math.random() * 0.8, Math.random() - 0.5).normalize().multiplyScalar(0.25 + Math.random() * 0.35);
    particles.push({ from: origin.clone(), to: new THREE.Vector3(0, 6.5, 0), u: 0, speed: 0.01, mesh: m, lift: 12, gold: true, vel }); scene.add(m);
  }
  if (hubGlow && tradingRoom) { hubGlow.position.x = tradingRoom.position.x; hubGlow.position.z = tradingRoom.position.z; hubGlow.scale.set(1, 1, 1); hubGlow.material.opacity = 0.75; hubGlow.userData.t = 0; }
  if (brain) brain.userData.flash = 1.0;
  const txt = textSprite(`+${detail.pnl != null ? Number(detail.pnl).toFixed(2) : ""} ${detail.currency || ""} · ${detail.strategy || "trade"} · treasury ${detail.treasury ?? ""}`, { size: 24, color: "#ffe58a", bg: "rgba(64,46,6,.92)" });
  txt.position.copy(origin).add(new THREE.Vector3(0, 6, 0)); scene.add(txt); labels.push({ sprite: txt, born: performance.now(), ttl: 5500, rise: 0.03 });
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
    brain.rotation.y += dt * 0.22; brain.userData.shell.rotation.x -= dt * 0.16; brainRings.forEach((r, i) => { r.rotation.z += dt * (0.25 + i * 0.1); r.rotation.x += dt * 0.04; });
    const flash = brain.userData.flash || 0; brain.userData.flash = Math.max(0, flash - dt * 0.6);
    const k = 1 + 0.05 * Math.sin(t * 2.2) + flash * 0.35; brain.userData.core.scale.setScalar(k);
    brain.userData.core.material.emissive.setHex(flash > 0.05 ? 0xffc64a : 0x4f9cff); brainLight.intensity = 90 + 40 * Math.sin(t * 2.2) + flash * 220; brainLight.color.setHex(flash > 0.05 ? 0xffc64a : 0x6aa8ff);
  }
  if (hubGlow && hubGlow.material.opacity > 0) { hubGlow.userData.t += dt; const s = 4 + hubGlow.userData.t * 14; hubGlow.scale.set(s, s, 1); hubGlow.material.opacity = Math.max(0, 0.75 - hubGlow.userData.t * 0.35); }
  for (const f of Object.values(figures)) {
    const p = f.parts, g = f.group;
    if (f.target) {
      const d = f.target.clone().sub(g.position); d.y = 0; const dist = d.length();
      if (dist < 0.3) { g.position.copy(f.target); g.position.y = f.home.y; const atHome = f.target.distanceTo(f.home) < 0.5; f.target = null;
        if (atHome) { g.rotation.y = f.homeRot; pose(f, true); } else if (f.lookAt) { const l = f.lookAt.clone().sub(g.position); g.rotation.y = Math.atan2(l.x, l.z); } }
      else { if (f.seated) pose(f, false); const step = Math.min(dist, dt * 13); g.position.add(d.normalize().multiplyScalar(step)); g.rotation.y = Math.atan2(d.x, d.z);
        const sw = Math.sin(t * 10 + f.phase) * 0.7; p.thL.rotation.x = sw; p.thR.rotation.x = -sw; p.shL.rotation.x = Math.max(0, -sw) * 0.8; p.shR.rotation.x = Math.max(0, sw) * 0.8; p.armL.rotation.x = -sw * 0.6; p.armR.rotation.x = sw * 0.6; g.position.y = f.home.y + Math.abs(Math.sin(t * 10 + f.phase)) * 0.14; }
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
    if (q.gold) { q.mesh.position.add(q.vel); q.vel.y -= 0.012; q.vel.multiplyScalar(0.985); q.u += dt * 0.5; if (q.u > 1.2 || q.mesh.position.y < 0.3) { scene.remove(q.mesh); particles.splice(i, 1); } continue; }
    q.u += q.speed; q.mesh.position.lerpVectors(q.from, q.to, q.u); q.mesh.position.y += Math.sin(q.u * Math.PI) * q.lift;
    if (q.u >= 1) { scene.remove(q.mesh); particles.splice(i, 1); if (q.to.y === 6.5 && brain) brain.userData.flash = Math.max(brain.userData.flash || 0, 0.3); }
  }
  for (let i = labels.length - 1; i >= 0; i--) { const l = labels[i]; const age = now - l.born; l.sprite.position.y += l.rise; l.sprite.material.opacity = Math.max(0, 1 - age / l.ttl); if (age > l.ttl) { scene.remove(l.sprite); l.sprite.material.map.dispose(); labels.splice(i, 1); } }
  controls.update(); composer.render();
}
