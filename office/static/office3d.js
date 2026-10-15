/* Agent HQ: 3D office floor. Low-poly office with real lighting, glass partitions, glowing monitors,
   seated agents who type while they work and walk to the brain core when they recall or remember.
   Public API (window.HQ3D): init(container, opts), setRoster(roster), setState(name, state),
   say(name, text), goBrain(name), goHome(name), goTo(name, otherName), pulse(fromName, toBrain, color),
   reward(detail), setBrain(count), resize(), focus(name). */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const OFFICE_ORDER = ["front-desk", "job-hunt", "pm", "studio", "brand-sales", "trading", "ops"];
const NEON = { "front-desk": 0xff4fd8, "job-hunt": 0x4f8dff, "pm": 0xff9a3c, "studio": 0x9b6bff, "brand-sales": 0xffd23f, "trading": 0xff4d6a, "ops": 0x2fd3b5, "research": 0x4fd0ff, "creative": 0xff6fb5 };
const STATE_COLOR = { idle: 0x4b5566, think: 0x5b8def, tool: 0xe0a93b, delegate: 0xa67cf0, done: 0x3ec28f, error: 0xef5b6e };
const SKIN = [0xf1c9a5, 0xd9a577, 0xb07b4f, 0x8d5a3b, 0xf6d7b7];
const SHIRT = [0x2e3a5c, 0x3b4a6b, 0x4a3b6b, 0x2f5c4a, 0x5c2f3a, 0x1f2d4d, 0x394d2f];

let renderer, scene, camera, controls, container, clock, raycaster, mouse;
let roomGroups = {}, figures = {}, roster = [], brain, brainRings = [], brainLight, particles = [], labels = [];
let opts = {}, lastFrame = 0, treasuryLabel = null, hubGlow = null, tradingRoom = null;

/* ----------------------------------------------------------------------------- helpers */
function textSprite(text, { size = 26, color = "#e6eaf2", bg = "rgba(8,11,20,.72)", pad = 10, bold = true, width } = {}) {
  const c = document.createElement("canvas"); const g = c.getContext("2d");
  g.font = `${bold ? "700" : "500"} ${size}px -apple-system, Inter, system-ui, sans-serif`;
  const w = Math.ceil(Math.max(width || 0, g.measureText(text).width) + pad * 2), h = size + pad * 2;
  c.width = w * 2; c.height = h * 2; g.scale(2, 2);
  g.fillStyle = bg; roundRect(g, 0, 0, w, h, 8); g.fill();
  g.font = `${bold ? "700" : "500"} ${size}px -apple-system, Inter, system-ui, sans-serif`; g.fillStyle = color; g.textBaseline = "middle"; g.textAlign = "center";
  g.fillText(text, w / 2, h / 2);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.minFilter = THREE.LinearFilter;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  sp.scale.set(w / 22, h / 22, 1); sp.userData.w = w; sp.userData.h = h; sp.renderOrder = 10;
  return sp;
}
function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
function box(w, h, d, mat) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.castShadow = true; m.receiveShadow = true; return m; }
const M = {
  floor: new THREE.MeshStandardMaterial({ color: 0x0c1220, roughness: 0.35, metalness: 0.55 }),
  slab: (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.6, metalness: 0.2 }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0x9fd0ff, transmission: 0.85, opacity: 0.35, transparent: true, roughness: 0.08, metalness: 0, thickness: 0.4, side: THREE.DoubleSide }),
  frame: new THREE.MeshStandardMaterial({ color: 0x1b2338, roughness: 0.5, metalness: 0.7 }),
  desk: new THREE.MeshStandardMaterial({ color: 0x1f2a44, roughness: 0.45, metalness: 0.35 }),
  deskTop: new THREE.MeshStandardMaterial({ color: 0x2b3a5e, roughness: 0.3, metalness: 0.5 }),
  chair: new THREE.MeshStandardMaterial({ color: 0x151c2c, roughness: 0.7 }),
  monitor: new THREE.MeshStandardMaterial({ color: 0x0b0f1a, roughness: 0.4, metalness: 0.6 }),
  screen: (c) => new THREE.MeshStandardMaterial({ color: 0x08101c, emissive: c, emissiveIntensity: 0.9, roughness: 0.2 }),
  neon: (c) => new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 2.2, roughness: 0.3 }),
  plant: new THREE.MeshStandardMaterial({ color: 0x2f9e5a, roughness: 0.8 }),
  pot: new THREE.MeshStandardMaterial({ color: 0x3a3f4e, roughness: 0.8 }),
};

/* ----------------------------------------------------------------------------- init */
export function init(el, options = {}) {
  container = el; opts = options; clock = new THREE.Clock();
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1)); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05; renderer.outputColorSpace = THREE.SRGBColorSpace;
  el.appendChild(renderer.domElement); renderer.domElement.style.display = "block";
  scene = new THREE.Scene(); scene.background = new THREE.Color(0x070a12); scene.fog = new THREE.Fog(0x070a12, 220, 420);
  camera = new THREE.PerspectiveCamera(40, 1, 0.5, 700); camera.position.set(0, 112, 138);
  controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.dampingFactor = 0.06;
  controls.maxPolarAngle = Math.PI / 2.25; controls.minPolarAngle = 0.35; controls.minDistance = 30; controls.maxDistance = 260; controls.target.set(0, 0, -4);
  raycaster = new THREE.Raycaster(); mouse = new THREE.Vector2();
  // lights
  scene.add(new THREE.HemisphereLight(0x9fc0ff, 0x141a2a, 1.0));
  const sun = new THREE.DirectionalLight(0xdfe9ff, 1.6); sun.position.set(60, 110, 40); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); sun.shadow.camera.left = -110; sun.shadow.camera.right = 110; sun.shadow.camera.top = 110; sun.shadow.camera.bottom = -110; sun.shadow.camera.far = 300; sun.shadow.bias = -0.0008;
  scene.add(sun);
  // floor + grid + stars
  const floor = new THREE.Mesh(new THREE.CircleGeometry(150, 96), M.floor); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  const grid = new THREE.GridHelper(300, 60, 0x1a2540, 0x121a2e); grid.position.y = 0.02; grid.material.transparent = true; grid.material.opacity = 0.5; scene.add(grid);
  const ring = new THREE.Mesh(new THREE.RingGeometry(149, 150.5, 128), M.neon(0x2a4a8a)); ring.rotation.x = -Math.PI / 2; ring.position.y = 0.05; scene.add(ring);
  const sg = new THREE.BufferGeometry(); const pts = [];
  for (let i = 0; i < 1400; i++) { const r = 260 + Math.random() * 120, t = Math.random() * Math.PI * 2, p = Math.random() * Math.PI / 2.2; pts.push(r * Math.cos(t) * Math.cos(p), 20 + r * Math.sin(p), r * Math.sin(t) * Math.cos(p)); }
  sg.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  scene.add(new THREE.Points(sg, new THREE.PointsMaterial({ color: 0x9fb8ff, size: 0.9, sizeAttenuation: true, transparent: true, opacity: 0.8 })));
  buildBrain();
  renderer.domElement.addEventListener("pointerdown", e => { mouse.userData = { x: e.clientX, y: e.clientY }; });
  renderer.domElement.addEventListener("pointerup", e => { const d = mouse.userData; if (d && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5) pick(e); });
  new ResizeObserver(() => resize()).observe(el); resize();
  requestAnimationFrame(frame);
}

export function resize() {
  if (!renderer) return;
  const w = container.clientWidth || 1, h = container.clientHeight || 1;
  renderer.setSize(w, h, false); renderer.domElement.style.width = w + "px"; renderer.domElement.style.height = h + "px";
  camera.aspect = w / h; camera.updateProjectionMatrix();
}

function pick(e) {
  const r = renderer.domElement.getBoundingClientRect();
  mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(Object.values(figures).map(f => f.group), true);
  if (hits.length) { let o = hits[0].object; while (o && !o.userData.agent) o = o.parent; if (o && opts.onAgentClick) opts.onAgentClick(o.userData.agent); }
}

/* ----------------------------------------------------------------------------- brain core */
function buildBrain() {
  brain = new THREE.Group(); brain.position.set(0, 7, 0);
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(3.2, 2), new THREE.MeshStandardMaterial({ color: 0x7fb8ff, emissive: 0x3f8cff, emissiveIntensity: 1.6, roughness: 0.15, metalness: 0.4 }));
  brain.add(core); brain.userData.core = core;
  const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(4.6, 1), new THREE.MeshBasicMaterial({ color: 0x9cc3ff, wireframe: true, transparent: true, opacity: 0.35 })); brain.add(shell); brain.userData.shell = shell;
  for (let i = 0; i < 3; i++) {
    const t = new THREE.Mesh(new THREE.TorusGeometry(6.5 + i * 1.6, 0.12, 8, 96), M.neon(i === 1 ? 0x7fe0ff : 0x5b8def)); t.rotation.set(Math.PI / 2 + i * 0.5, i * 0.7, 0); brain.add(t); brainRings.push(t);
  }
  brainLight = new THREE.PointLight(0x5b8def, 60, 70, 1.6); brainLight.position.set(0, 3, 0); brain.add(brainLight);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(9, 10.5, 1.2, 48), M.frame); base.position.y = -6.4; base.receiveShadow = true; brain.add(base);
  const baseRing = new THREE.Mesh(new THREE.TorusGeometry(10.2, 0.18, 8, 96), M.neon(0x5b8def)); baseRing.rotation.x = Math.PI / 2; baseRing.position.y = -5.8; brain.add(baseRing);
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.9, 60, 12, 1, true), new THREE.MeshBasicMaterial({ color: 0x7fb8ff, transparent: true, opacity: 0.08, side: THREE.DoubleSide })); beam.position.y = 24; brain.add(beam);
  const lbl = textSprite("THE BRAIN · shared memory", { size: 22 }); lbl.position.set(0, 13.5, 0); brain.add(lbl); brain.userData.label = lbl;
  scene.add(brain);
}

export function setBrain(count) {
  if (!brain) return;
  const old = brain.userData.label; brain.remove(old); old.material.map.dispose();
  const lbl = textSprite(`THE BRAIN · ${count} notes`, { size: 22 }); lbl.position.set(0, 13.5, 0); brain.add(lbl); brain.userData.label = lbl;
}

/* ----------------------------------------------------------------------------- rooms & figures */
export function setRoster(list) {
  roster = list; Object.values(roomGroups).forEach(g => scene.remove(g)); Object.values(figures).forEach(f => { scene.remove(f.group); scene.remove(f.label); });
  roomGroups = {}; figures = {}; labels = [];
  const byOffice = {}; list.forEach(a => (byOffice[a.office] = byOffice[a.office] || []).push(a));
  const names = Object.keys(byOffice).sort((a, b) => (OFFICE_ORDER.indexOf(a) + 99) % 100 - (OFFICE_ORDER.indexOf(b) + 99) % 100);
  const R = 50; const n = names.length;
  names.forEach((name, i) => {
    const members = byOffice[name]; const cols = Math.ceil(Math.sqrt(members.length)), rows = Math.ceil(members.length / cols);
    const w = cols * 7.5 + 5, d = rows * 7.5 + 5; const ang = -Math.PI / 2 + (i / n) * Math.PI * 2;
    const g = new THREE.Group(); g.position.set(R * Math.cos(ang), 0, R * Math.sin(ang)); g.rotation.y = Math.PI / 2 - ang; // open side faces the brain
    const neon = NEON[name] || 0x5b8def; const col = new THREE.Color(neon);
    const slab = box(w, 0.6, d, M.slab(col.clone().multiplyScalar(0.22).lerp(new THREE.Color(0x121a2e), 0.35))); slab.position.y = 0.3; slab.receiveShadow = true; g.add(slab);
    // glass partitions: back and both sides, open towards the brain (local +z faces the brain after rotation)
    const wallH = 6.5;
    const back = new THREE.Mesh(new THREE.PlaneGeometry(w, wallH), M.glass); back.position.set(0, wallH / 2 + 0.6, -d / 2); g.add(back);
    for (const sx of [-1, 1]) { const side = new THREE.Mesh(new THREE.PlaneGeometry(d * 0.7, wallH), M.glass); side.rotation.y = Math.PI / 2; side.position.set(sx * w / 2, wallH / 2 + 0.6, -d * 0.15); g.add(side); }
    const strip = box(w + 0.4, 0.25, 0.25, M.neon(neon)); strip.position.set(0, wallH + 0.75, -d / 2); g.add(strip);
    for (const sx of [-1, 1]) { const post = box(0.3, wallH + 0.4, 0.3, M.frame); post.position.set(sx * w / 2, wallH / 2 + 0.6, -d / 2); g.add(post); }
    const edge = new THREE.Mesh(new THREE.PlaneGeometry(w + 0.6, 0.35), M.neon(neon)); edge.rotation.x = -Math.PI / 2; edge.position.set(0, 0.62, d / 2 + 0.1); g.add(edge);
    const lamp = new THREE.PointLight(neon, 40, 60, 1.6); lamp.position.set(0, 10, -d * 0.2); g.add(lamp);
    const fill = new THREE.PointLight(0xbfd4ff, 18, 45, 1.8); fill.position.set(0, 8, d * 0.3); g.add(fill);
    const plant = new THREE.Group(); const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.5, 1.2, 10), M.pot); pot.position.set(0, 1.2, 0); plant.add(pot);
    const leaves = new THREE.Mesh(new THREE.IcosahedronGeometry(1.1, 1), M.plant); leaves.position.set(0, 2.4, 0); leaves.castShadow = true; plant.add(leaves); plant.position.set(-w / 2 + 1.4, 0, -d / 2 + 1.4); g.add(plant);
    const wallScreen = new THREE.Mesh(new THREE.PlaneGeometry(Math.min(8, w - 2), 3.4), M.screen(col.clone().multiplyScalar(0.6))); wallScreen.position.set(w / 4, 4.2, -d / 2 + 0.08); g.add(wallScreen);
    const title = textSprite(`${name.replace("-", " ")} · ${members.length} agent${members.length > 1 ? "s" : ""}`, { size: 24, bg: "rgba(8,11,20,.8)" }); title.position.set(0, wallH + 3.2, -d / 2); g.add(title);
    g.userData = { name, w, d, neon }; scene.add(g); roomGroups[name] = g; if (name === "trading") tradingRoom = g;
    members.forEach((a, k) => {
      const cx = (k % cols - (cols - 1) / 2) * 7.5, cz = (Math.floor(k / cols) - (rows - 1) / 2) * 7.5 - 0.5;
      addDesk(g, cx, cz, neon); const seat = new THREE.Vector3(cx, 0, cz + 2.1); const world = g.localToWorld(seat.clone());
      const fig = makeFigure(a, k, neon); fig.group.position.copy(world); fig.group.rotation.y = g.rotation.y;
      fig.home = world.clone(); fig.homeRot = g.rotation.y; fig.room = g; scene.add(fig.group);
      fig.label = textSprite(a.name, { size: 20 }); fig.label.position.copy(world).add(new THREE.Vector3(0, 7.4, 0)); scene.add(fig.label);
      figures[a.name] = fig;
    });
  });
  if (tradingRoom && !hubGlow) {
    hubGlow = new THREE.Mesh(new THREE.RingGeometry(0, 1, 48), new THREE.MeshBasicMaterial({ color: 0xffd23f, transparent: true, opacity: 0, side: THREE.DoubleSide }));
    hubGlow.rotation.x = -Math.PI / 2; hubGlow.position.y = 0.7; scene.add(hubGlow);
  }
}

function addDesk(g, x, z, neon) {
  const top = box(5.2, 0.25, 2.4, M.deskTop); top.position.set(x, 2.5, z); g.add(top);
  for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) { const leg = box(0.18, 2.4, 0.18, M.desk); leg.position.set(x + sx * 2.4, 1.25, z + sz * 1.0); g.add(leg); }
  const mon = box(2.6, 1.6, 0.12, M.monitor); mon.position.set(x, 3.6, z - 0.8); g.add(mon);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(2.3, 1.3), M.screen(new THREE.Color(neon).lerp(new THREE.Color(0x7fb8ff), 0.5))); scr.position.set(x, 3.6, z - 0.73); g.add(scr);
  const stand = box(0.3, 0.8, 0.3, M.monitor); stand.position.set(x, 2.95, z - 0.8); g.add(stand);
  const kb = box(1.6, 0.1, 0.6, M.monitor); kb.position.set(x, 2.68, z + 0.3); g.add(kb);
  const seat = box(1.6, 0.25, 1.6, M.chair); seat.position.set(x, 1.7, z + 2.1); g.add(seat);
  const back = box(1.6, 1.9, 0.25, M.chair); back.position.set(x, 2.75, z + 2.9); g.add(back);
  const post = box(0.2, 1.5, 0.2, M.frame); post.position.set(x, 0.95, z + 2.1); g.add(post);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 0.12, 12), M.frame); base.position.set(x, 0.7, z + 2.1); g.add(base);
}

function makeFigure(a, k, neon) {
  const group = new THREE.Group(); group.userData.agent = a.name;
  const skin = new THREE.MeshStandardMaterial({ color: SKIN[(a.name.length + k) % SKIN.length], roughness: 0.7 });
  const shirt = new THREE.MeshStandardMaterial({ color: SHIRT[(a.name.charCodeAt(0) + k) % SHIRT.length], roughness: 0.75 });
  const trousers = new THREE.MeshStandardMaterial({ color: 0x1c2233, roughness: 0.85 });
  const body = new THREE.Group(); group.add(body);
  const hips = box(1.3, 0.5, 0.9, trousers); hips.position.y = 2.05; body.add(hips);
  const torso = box(1.4, 1.6, 0.8, shirt); torso.position.y = 3.1; body.add(torso);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.55, 16, 14), skin); head.position.y = 4.45; head.castShadow = true; body.add(head);
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.57, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2.2), new THREE.MeshStandardMaterial({ color: [0x241b14, 0x3a2a1a, 0x101010, 0x5a3b1e, 0x6b6b6b][k % 5], roughness: 0.9 })); hair.position.y = 4.55; body.add(hair);
  const armL = box(0.35, 1.3, 0.35, shirt); armL.position.set(-0.95, 3.1, 0); body.add(armL); const armR = box(0.35, 1.3, 0.35, shirt); armR.position.set(0.95, 3.1, 0); body.add(armR);
  const foreL = box(0.3, 0.9, 0.3, skin); foreL.position.set(-0.95, 2.55, -0.55); foreL.rotation.x = -Math.PI / 2.4; body.add(foreL);
  const foreR = box(0.3, 0.9, 0.3, skin); foreR.position.set(0.95, 2.55, -0.55); foreR.rotation.x = -Math.PI / 2.4; body.add(foreR);
  const legs = new THREE.Group(); group.add(legs);
  const thL = box(0.5, 1.4, 0.5, trousers), thR = box(0.5, 1.4, 0.5, trousers); legs.add(thL, thR);
  const shL = box(0.42, 1.3, 0.42, trousers), shR = box(0.42, 1.3, 0.42, trousers); legs.add(shL, shR);
  const light = new THREE.Mesh(new THREE.SphereGeometry(0.22, 10, 8), M.neon(STATE_COLOR.idle)); light.position.y = 5.5; group.add(light);
  const fig = { name: a.name, group, body, legs, parts: { armL, armR, foreL, foreR, thL, thR, shL, shR, head, light, hips }, state: "idle", seated: true, target: null, bubble: null, bubbleUntil: 0, bubbleSprite: null, neon, phase: Math.random() * 6 };
  pose(fig, true); return fig;
}

function pose(fig, seated) {
  const p = fig.parts; fig.seated = seated;
  if (seated) {   // thighs forward, shins down, torso sits on the chair at z = 0 (the chair seat is at +2.1 from the desk centre)
    p.thL.position.set(-0.35, 1.85, -0.5); p.thL.rotation.x = Math.PI / 2; p.thR.position.set(0.35, 1.85, -0.5); p.thR.rotation.x = Math.PI / 2;
    p.shL.position.set(-0.35, 0.95, -1.0); p.shL.rotation.x = 0; p.shR.position.set(0.35, 0.95, -1.0); p.shR.rotation.x = 0;
    fig.body.position.y = 0; p.armL.rotation.x = -0.9; p.armR.rotation.x = -0.9;
  } else {        // standing
    p.thL.position.set(-0.35, 1.0, 0); p.thL.rotation.x = 0; p.thR.position.set(0.35, 1.0, 0); p.thR.rotation.x = 0;
    p.shL.position.set(-0.35, 0.65, 0); p.shR.position.set(0.35, 0.65, 0); fig.body.position.y = 0.6; p.armL.rotation.x = 0; p.armR.rotation.x = 0;
  }
}

/* ----------------------------------------------------------------------------- public controls */
export function setState(name, state) {
  const f = figures[name]; if (!f) return; f.state = state;
  f.parts.light.material = M.neon(STATE_COLOR[state] || STATE_COLOR.idle);
}
export function say(name, text, ms = 6000) {
  const f = figures[name]; if (!f) return;
  if (f.bubbleSprite) { scene.remove(f.bubbleSprite); f.bubbleSprite.material.map.dispose(); }
  f.bubbleSprite = textSprite(text.length > 44 ? text.slice(0, 42) + "…" : text, { size: 18, bg: "rgba(14,20,36,.92)", bold: false });
  f.bubbleUntil = Date.now() + ms; scene.add(f.bubbleSprite);
}
export function goBrain(name) { const f = figures[name]; if (!f) return; const a = Math.random() * Math.PI * 2; f.target = new THREE.Vector3(13 * Math.cos(a), 0, 13 * Math.sin(a)); f.lookAt = new THREE.Vector3(0, 0, 0); }
export function goHome(name) { const f = figures[name]; if (!f) return; f.target = f.home.clone(); f.lookAt = null; }
export function goTo(name, other) { const f = figures[name], o = figures[other]; if (!f || !o) return; const dir = o.home.clone().sub(f.home).normalize(); f.target = o.home.clone().sub(dir.multiplyScalar(4)); f.lookAt = o.home.clone(); }
export function pulse(fromName, toBrain, color = 0x9cc3ff) {
  const f = figures[fromName]; if (!f) return;
  const from = toBrain ? f.group.position.clone().add(new THREE.Vector3(0, 4, 0)) : new THREE.Vector3(0, 7, 0);
  const to = toBrain ? new THREE.Vector3(0, 7, 0) : f.home.clone().add(new THREE.Vector3(0, 4, 0));
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.35, 8, 8), M.neon(color)); mesh.position.copy(from);
  particles.push({ from, to, u: 0, speed: 0.012 + Math.random() * 0.006, mesh, lift: 10 + Math.random() * 6 }); scene.add(mesh);
}
export function focus(name) { const f = figures[name]; if (!f) return; controls.target.copy(f.group.position).add(new THREE.Vector3(0, 2, 0)); }

/* a profitable trade: gold fountain at the brain, the trading hub glows, a floating credit label */
export function reward(detail = {}) {
  const origin = tradingRoom ? tradingRoom.position.clone().add(new THREE.Vector3(0, 6, 0)) : new THREE.Vector3(0, 7, 0);
  for (let i = 0; i < 40; i++) {
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.28, 6, 6), M.neon(i % 3 ? 0xffd23f : 0xfff1b0)); m.position.copy(origin);
    const dir = new THREE.Vector3(Math.random() - 0.5, 0.6 + Math.random() * 0.8, Math.random() - 0.5).normalize().multiplyScalar(0.25 + Math.random() * 0.35);
    particles.push({ from: origin.clone(), to: new THREE.Vector3(0, 7, 0), u: 0, speed: 0.008 + Math.random() * 0.01, mesh: m, lift: 14 + Math.random() * 10, gold: true, vel: dir });
    scene.add(m);
  }
  if (hubGlow) { hubGlow.position.x = tradingRoom.position.x; hubGlow.position.z = tradingRoom.position.z; hubGlow.scale.set(1, 1, 1); hubGlow.material.opacity = 0.65; hubGlow.userData.t = 0; }
  if (brain) brain.userData.flash = 1.0;
  const txt = textSprite(`+${detail.pnl != null ? Number(detail.pnl).toFixed(2) : ""} ${detail.currency || ""} · ${detail.strategy || "trade"} · treasury ${detail.treasury ?? ""}`.replace(/\s+·\s+$/, ""), { size: 22, color: "#ffe58a", bg: "rgba(60,44,8,.9)" });
  txt.position.copy(origin).add(new THREE.Vector3(0, 6, 0)); scene.add(txt); labels.push({ sprite: txt, born: performance.now(), ttl: 5000, rise: 0.03 });
  const dot = figures["trader"]; if (dot) say("trader", "💰 profitable trade", 6000);
}

/* ----------------------------------------------------------------------------- animation */
function frame(now) {
  requestAnimationFrame(frame);
  if (document.hidden) return;
  const busy = Object.values(figures).some(f => f.state !== "idle" || f.target) || particles.length;
  if (!busy && now - lastFrame < 1000 / 20) return;   // idle floor: 20 fps is plenty
  lastFrame = now; const dt = Math.min(0.05, clock.getDelta()); const t = now / 1000;
  // brain
  if (brain) {
    brain.rotation.y += dt * 0.25; brain.userData.shell.rotation.x -= dt * 0.18; brainRings.forEach((r, i) => { r.rotation.z += dt * (0.3 + i * 0.12); r.rotation.x += dt * 0.05; });
    const flash = brain.userData.flash || 0; brain.userData.flash = Math.max(0, flash - dt * 0.6);
    const k = 1 + 0.06 * Math.sin(t * 2.2) + flash * 0.35; brain.userData.core.scale.set(k, k, k);
    brain.userData.core.material.emissive.setHex(flash > 0.05 ? 0xffc64a : 0x3f8cff); brainLight.intensity = 60 + 35 * Math.sin(t * 2.2) + flash * 160; brainLight.color.setHex(flash > 0.05 ? 0xffc64a : 0x5b8def);
  }
  if (hubGlow && hubGlow.material.opacity > 0) { hubGlow.userData.t += dt; const s = 6 + hubGlow.userData.t * 16; hubGlow.scale.set(s, s, 1); hubGlow.material.opacity = Math.max(0, 0.65 - hubGlow.userData.t * 0.3); }
  // figures
  for (const f of Object.values(figures)) {
    const p = f.parts; const g = f.group;
    if (f.target) {
      const d = f.target.clone().sub(g.position); d.y = 0; const dist = d.length();
      if (dist < 0.3) {
        g.position.copy(f.target); const atHome = f.target.distanceTo(f.home) < 0.5; f.target = null;
        if (atHome) { g.rotation.y = f.homeRot; pose(f, true); } else if (f.lookAt) { const l = f.lookAt.clone().sub(g.position); g.rotation.y = Math.atan2(l.x, l.z); }
      } else {
        if (f.seated) pose(f, false);
        const step = Math.min(dist, dt * 14); g.position.add(d.normalize().multiplyScalar(step)); g.rotation.y = Math.atan2(d.x, d.z);
        const sw = Math.sin(t * 11 + f.phase) * 0.6; p.thL.rotation.x = sw; p.thR.rotation.x = -sw; p.armL.rotation.x = -sw * 0.7; p.armR.rotation.x = sw * 0.7; g.position.y = Math.abs(Math.sin(t * 11 + f.phase)) * 0.12;
      }
    } else if (f.seated) {
      const working = f.state === "think" || f.state === "tool" || f.state === "delegate";
      if (working) { const ty = Math.sin(t * 16 + f.phase) * 0.08, ty2 = Math.cos(t * 15 + f.phase) * 0.08; p.foreL.position.y = 2.55 + ty; p.foreR.position.y = 2.55 + ty2; p.head.position.y = 4.45 + Math.sin(t * 2 + f.phase) * 0.03; p.head.rotation.x = -0.12; }
      else { p.foreL.position.y = 2.55; p.foreR.position.y = 2.55; p.head.position.y = 4.45 + Math.sin(t * 1.3 + f.phase) * 0.04; p.head.rotation.x = Math.sin(t * 0.5 + f.phase) * 0.05; p.head.rotation.y = Math.sin(t * 0.3 + f.phase) * 0.25; }
      f.body.position.y = Math.sin(t * 1.5 + f.phase) * 0.02;
    } else if (f.lookAt) { p.foreL.position.y = 2.55 + Math.sin(t * 6 + f.phase) * 0.1; }
    p.light.scale.setScalar(f.state === "idle" ? 0.8 : 1 + 0.25 * Math.sin(t * 6 + f.phase));
    f.label.position.copy(g.position).add(new THREE.Vector3(0, f.seated ? 7.2 : 7.8, 0));
    if (f.bubbleSprite) { if (Date.now() > f.bubbleUntil) { scene.remove(f.bubbleSprite); f.bubbleSprite.material.map.dispose(); f.bubbleSprite = null; } else f.bubbleSprite.position.copy(g.position).add(new THREE.Vector3(0, (f.seated ? 9.0 : 9.6) + Math.sin(t * 2) * 0.1, 0)); }
  }
  // particles
  for (let i = particles.length - 1; i >= 0; i--) {
    const q = particles[i];
    if (q.gold) { q.mesh.position.add(q.vel); q.vel.y -= 0.012; q.vel.multiplyScalar(0.985); q.u += dt * 0.5; q.mesh.material.emissiveIntensity = Math.max(0, 2.2 - q.u * 2); if (q.u > 1.1 || q.mesh.position.y < 0.3) { scene.remove(q.mesh); particles.splice(i, 1); } continue; }
    q.u += q.speed; const u = q.u; q.mesh.position.lerpVectors(q.from, q.to, u); q.mesh.position.y += Math.sin(u * Math.PI) * q.lift;
    if (u >= 1) { scene.remove(q.mesh); particles.splice(i, 1); if (q.to.y === 7 && brain) brain.userData.flash = Math.max(brain.userData.flash || 0, 0.35); }
  }
  for (let i = labels.length - 1; i >= 0; i--) { const l = labels[i]; const age = now - l.born; l.sprite.position.y += l.rise; l.sprite.material.opacity = Math.max(0, 1 - age / l.ttl); if (age > l.ttl) { scene.remove(l.sprite); l.sprite.material.map.dispose(); labels.splice(i, 1); } }
  controls.update(); renderer.render(scene, camera);
}
