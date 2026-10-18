/* Agent HQ campus, v2: the ring building rebuilt as an architectural model.
   One circular glass building (think Apple Park) with a white cantilevered roof edge, oak floors and full-height
   glass. Each department is a wing of the ring with its own feature wall and signature prop; the shared brain
   lives in a glass atrium on an island in a reflecting pond at the centre, reached by stone walkways and timber
   bridges. Lighting follows golden hour (default) or the real London time of day, with warm interiors at night.
   Labels are screen-sized (always readable) and by default only shown for agents who are working.
   API on window.HQ3D (same as the classic design, plus a few extras):
     init, setRoster, setState, say, goBrain, goHome, goTo, pulse, reward, setBrain, resize, focus, floorView,
     setOffice, setLabelMode, setLighting, overview, flyToDept */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import * as SkeletonUtils from "three/addons/utils/SkeletonUtils.js";

/* People: the motion-captured humanoid from the three.js examples (Mixamo X Bot: real proportions, captured
   idle and walk, a full skeleton we pose to sit and type). Simple built-in figures are the fallback. */
const PERSON_URL = "https://cdn.jsdelivr.net/gh/mrdoob/three.js@r160/examples/models/gltf/Xbot.glb";
const PERSON_HEIGHT = 4.6;                                  // scene units (desk top is 1.85)
// axes measured on the X Bot skeleton: thigh forward = local x-, knee = x+, arm down = z (left -, right +),
// arm forward = y (left -, right +), elbow = y (left -, right +); bone height at scale 1 is 1.78
const SIT = { hip: -1.5, knee: 1.5, drop: 0.72, back: 0.3, armDown: 1.2, armFwd: 0.95, elbow: 1.05, lean: 0.16 };
const PERSON_SCALE = 2.5;
let personAsset = null, personPromise = null, lastRoster = null;
function loadPerson() {
  if (!personPromise) personPromise = new GLTFLoader().loadAsync(PERSON_URL)
    .then(g => { personAsset = { scene: g.scene, clips: g.animations, scale: PERSON_SCALE }; return personAsset; })
    .catch(e => { console.warn("person model unavailable, using simple figures", e); return null; });
  return personPromise;
}

const OFFICE_ORDER = ["front-desk", "job-hunt", "pm", "studio", "brand-sales", "trading", "ops"];
const ACCENT = { "front-desk": 0xc2558f, "job-hunt": 0x3b6fd6, "pm": 0xd98433, "studio": 0x7a5fcf, "brand-sales": 0xd4a52a, "trading": 0xc94a5c, "ops": 0x2e9c86, "research": 0x3a9bc9, "creative": 0xd06a9c };
const TITLE = { "front-desk": "Front Desk", "job-hunt": "Job Hunt", "pm": "Project Office", "studio": "Studio", "brand-sales": "Brand & Sales", "trading": "Trading Desk", "ops": "Operations" };
const STATE_COLOR = { idle: 0x9aa3b5, think: 0x3b6fd6, tool: 0xd98433, delegate: 0x7a5fcf, done: 0x2e9c86, error: 0xc94a5c };
const STATE_WORD = { think: "thinking", tool: "using a tool", delegate: "delegating", done: "done", error: "fallback model" };
const SKIN = [0xf3cfae, 0xe0b08a, 0xc48e63, 0x9c6a45, 0x6f4a30, 0xf7dcc0];
const TOPS = [0x2d3f6b, 0xf2f2f2, 0x6b7a99, 0x8fb0d9, 0xd9c7b0, 0x3f3f4a, 0xb9d3c2, 0xe6b3b3, 0x4a6b8a, 0xf0d9a8];
const HAIR = [0x1d140e, 0x3b2616, 0x6b3f22, 0xb8842d, 0x2a2a2a, 0x8a8a8a, 0xc24b2f];

const RI = 34, RO = 50, H = 7, FLOOR = 0.8;           // ring inner/outer radius, storey height, floor level
const RPOND = 17, RISLAND = 9.5, RATRIUM = 7;          // reflecting pond, the island, the glass atrium
const RPROM = RI - 3;                                   // the promenade agents walk along, just inside the building
const MOBILE = window.matchMedia("(max-width: 700px)").matches || /iPhone|iPad|Android/i.test(navigator.userAgent);

let renderer, scene, camera, controls, container, clock, raycaster, mouse;
let campus = null, figures = {}, depts = {}, brain = null, motes = null, atriumLight, sun, hemi, sky;
let particles = [], floaters = [], pxSprites = [], nightMats = [], deptLights = [], signs = [];
const envMats = [];                                    // reflection strength follows daylight
let slatSpots = [];
let ticker = null, tradeScreen = null, rackTex = [], hqLabel = null, treasuryBoard = null;
let opts = {}, lastFrame = 0, hovered = null, labelMode = "active", lightMode = "golden", night = 0;
let lastUser = -1e9, tween = null, autoFocus = null, lastAuto = 0, officeInfo = { depts: {} }, memories = 0, timeOverride = null;

const polar = (r, th, y = 0) => new THREE.Vector3(r * Math.cos(th), y, -r * Math.sin(th));
const facing = (from, to) => { const d = to.clone().sub(from); return Math.atan2(d.x, d.z) + Math.PI; };   // figures and desks face -z locally
const hex = (c) => "#" + c.toString(16).padStart(6, "0");
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

/* ----------------------------------------------------------------------------- materials */
function std(color, roughness = 0.8, metalness = 0, env = 0.35, extra = {}) {
  const m = new THREE.MeshStandardMaterial({ color, roughness, metalness, ...extra }); m.envMapIntensity = env; envMats.push([m, env]); return m;
}
/* glowing surfaces (screens, lamps): base brightness by day, brighter at night */
function glow(color, base, boost, extra = {}) {
  const m = new THREE.MeshStandardMaterial({ color, emissive: extra.emissive ?? color, emissiveIntensity: base, roughness: 0.4, ...extra });
  nightMats.push({ m, base, boost }); return m;
}
const M = {
  grass: std(0x8fb470, 1, 0, 0.12), lawn: std(0x9dc47d, 1, 0, 0.12), meadow: std(0xa9c98b, 1, 0, 0.1),
  stone: std(0xe7e3d9, 0.85, 0, 0.3), stoneEdge: std(0xc9c3b6, 0.9, 0, 0.25), concrete: std(0xdedbd3, 0.85, 0, 0.3),
  oak: std(0xcfa97c, 0.55, 0, 0.3), timber: std(0xb48a5c, 0.6, 0, 0.3),
  white: std(0xf7f6f2, 0.55, 0, 0.45, { side: THREE.DoubleSide }), frame: std(0xeeece6, 0.4, 0.15, 0.5),
  metal: std(0x3b414d, 0.35, 0.7, 0.6), dark: std(0x262a33, 0.5, 0.3, 0.4),
  glass: new THREE.MeshStandardMaterial({ color: 0xd6e8f3, roughness: 0.05, metalness: 0.15, transparent: true, opacity: 0.2, depthWrite: false, side: THREE.DoubleSide }),
  water: std(0x5d8db0, 0.07, 0.3, 1.1),
  fabric: std(0x59606e, 0.95, 0, 0.2), fabricWarm: std(0xc8b49a, 0.95, 0, 0.2), monitor: std(0x22262e, 0.4, 0.5, 0.5),
  trunk: std(0x6e5238, 1, 0, 0.1), pot: std(0xd8cbb7, 0.85, 0, 0.3), plant: std(0x4f8f55, 0.9, 0, 0.15),
  gold: std(0xd9ae45, 0.3, 0.85, 1.0), darkPanel: std(0x262a33, 0.5, 0.3, 0.4, { side: THREE.DoubleSide }),
  shadow: new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.16, depthWrite: false }),
};
M.glass.envMapIntensity = 1.3; envMats.push([M.glass, 1.3]);
const LEAVES = [std(0x5d9a55, 0.9, 0, 0.15), std(0x6fab5d, 0.9, 0, 0.15), std(0x4d8650, 0.9, 0, 0.15)];
const SHARED = { sphere: new THREE.SphereGeometry(1, 16, 12), blob: new THREE.IcosahedronGeometry(1, 1) };

function box(w, h, d, mat, shadow = true) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.castShadow = shadow; m.receiveShadow = true; return m; }
function flatRing(r0, r1, mat, y, th0 = 0, len = Math.PI * 2, seg = 128) { const m = new THREE.Mesh(new THREE.RingGeometry(r0, r1, seg, 1, th0, len), mat); m.rotation.x = -Math.PI / 2; m.position.y = y; m.receiveShadow = true; return m; }
/* a vertical curved surface following polar(): cylinder theta = polar angle + pi/2 */
function curve(r, y0, h, mat, th0 = 0, len = Math.PI * 2, seg = 160) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, Math.max(8, Math.round(seg * len / (Math.PI * 2))), 1, true, th0 + Math.PI / 2, len), mat); m.position.y = y0 + h / 2; m.receiveShadow = true; return m; }
function disc(r, mat) { const m = new THREE.Mesh(new THREE.CircleGeometry(r, 24), mat); m.rotation.x = -Math.PI / 2; m.renderOrder = 1; return m; }

/* ----------------------------------------------------------------------------- screen-sized labels */
function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
function chipCanvas(lines, { accent, bg = "rgba(255,255,255,.96)", color = "#1b2130", sub = "#5b6475", size = 13, pad = 8, border = "rgba(0,0,0,.13)" } = {}) {
  const dpr = 2, c = document.createElement("canvas"), g = c.getContext("2d");
  const f1 = `700 ${size}px -apple-system, Inter, system-ui, sans-serif`, s2 = Math.round(size * 0.84), f2 = `500 ${s2}px -apple-system, Inter, system-ui, sans-serif`;
  g.font = f1; let w = g.measureText(lines[0]).width; if (lines[1]) { g.font = f2; w = Math.max(w, g.measureText(lines[1]).width); }
  const dot = accent ? 14 : 0, W = Math.ceil(w + pad * 2 + dot), Hh = Math.ceil(size + pad * 2 + (lines[1] ? s2 + 5 : 0));
  c.width = W * dpr; c.height = Hh * dpr; g.scale(dpr, dpr);
  g.fillStyle = bg; roundRect(g, 0.5, 0.5, W - 1, Hh - 1, Math.min(9, Hh / 2)); g.fill(); g.strokeStyle = border; g.lineWidth = 1; g.stroke();
  if (accent) { g.fillStyle = accent; g.beginPath(); g.arc(pad + 4, pad + size / 2 + 0.5, 4.5, 0, Math.PI * 2); g.fill(); }
  g.textBaseline = "middle"; g.font = f1; g.fillStyle = color; g.fillText(lines[0], pad + dot, pad + size / 2 + 1);
  if (lines[1]) { g.font = f2; g.fillStyle = sub; g.fillText(lines[1], pad + dot, pad + size + 5 + s2 / 2); }
  return { c, W, Hh };
}
function texFrom(c) { const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.minFilter = THREE.LinearFilter; t.anisotropy = 4; return t; }
function sizePx(sp) { const k = (MOBILE ? 0.78 : 1) * 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / Math.max(1, container.clientHeight || 1); sp.scale.set(sp.userData.px[0] * k, sp.userData.px[1] * k, 1); }
function pxSprite(lines, o = {}) {
  const { c, W, Hh } = chipCanvas(lines, o);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: texFrom(c), transparent: true, depthTest: false, depthWrite: false, sizeAttenuation: false }));
  sp.center.set(0.5, 0); sp.renderOrder = 20; sp.userData.px = [W, Hh]; sp.userData.key = lines.join("|"); sizePx(sp); pxSprites.push(sp); return sp;
}
function retext(sp, lines, o = {}) {
  const key = lines.join("|"); if (sp.userData.key === key) return; sp.userData.key = key;
  const { c, W, Hh } = chipCanvas(lines, o); sp.material.map.dispose(); sp.material.map = texFrom(c); sp.material.needsUpdate = true; sp.userData.px = [W, Hh]; sizePx(sp);
}
function dropSprite(sp) { if (!sp) return; sp.parent && sp.parent.remove(sp); sp.material.map.dispose(); sp.material.dispose(); pxSprites = pxSprites.filter(x => x !== sp); }

/* ----------------------------------------------------------------------------- canvas textures for feature walls */
function canvas(w, h) { const c = document.createElement("canvas"); c.width = w; c.height = h; return [c, c.getContext("2d")]; }
const font = (wgt, px) => `${wgt} ${px}px -apple-system, Inter, system-ui, sans-serif`;
function wallTexture(kind, accent) {
  const [c, g] = canvas(1024, 512); const acc = hex(accent);
  const header = (title, sub, dark = false) => { g.fillStyle = dark ? "#e8edf6" : "#1b2130"; g.font = font(800, 34); g.fillText(title, 40, 66); g.fillStyle = acc; g.fillRect(40, 80, 90, 5); if (sub) { g.font = font(500, 20); g.fillStyle = dark ? "#9aa6bd" : "#5b6475"; g.fillText(sub, 40, 116); } };
  if (kind === "front-desk") {
    g.fillStyle = "#fbfaf7"; g.fillRect(0, 0, 1024, 512);
    g.fillStyle = "#1b2130"; g.font = font(800, 108); g.fillText("AGENT HQ", 60, 250); g.fillStyle = acc; g.fillRect(64, 280, 160, 8);
    g.font = font(500, 34); g.fillStyle = "#5b6475"; g.fillText("One office. One shared brain. Working round the clock.", 64, 350);
  } else if (kind === "job-hunt") {
    g.fillStyle = "#c9a77c"; g.fillRect(0, 0, 1024, 512); const r = rng(7);
    for (let i = 0; i < 2500; i++) { g.fillStyle = `rgba(80,50,20,${r() * 0.12})`; g.fillRect(r() * 1024, r() * 512, 2, 2); }
    g.fillStyle = "#fffdf8"; roundRect(g, 30, 22, 330, 70, 8); g.fill(); g.fillStyle = "#1b2130"; g.font = font(800, 30); g.fillText("ROLES IN PLAY", 48, 68);
    for (let i = 0; i < 8; i++) { const x = 30 + (i % 4) * 246, y = 120 + Math.floor(i / 4) * 190, rot = (r() - 0.5) * 0.08;
      g.save(); g.translate(x + 110, y + 80); g.rotate(rot); g.fillStyle = "#ffffff"; g.fillRect(-105, -78, 210, 160); g.fillStyle = acc; g.fillRect(-90, -60, 110, 12);
      g.fillStyle = "#c7cedb"; g.fillRect(-90, -36, 170, 9); g.fillRect(-90, -18, 130, 9); g.fillStyle = ["#2e9c86", "#d4a52a", "#3b6fd6"][i % 3]; g.font = font(700, 20); g.fillText(`fit ${3 + (i % 3)}/5`, -90, 52);
      g.fillStyle = "#c94a5c"; g.beginPath(); g.arc(0, -80, 8, 0, 7); g.fill(); g.restore(); }
  } else if (kind === "pm") {
    g.fillStyle = "#fbfaf7"; g.fillRect(0, 0, 1024, 512); header("ROADMAP", "this week's milestones");
    ["TO DO", "DOING", "REVIEW", "SHIPPED"].forEach((t, i) => { const x = 40 + i * 245; g.fillStyle = "#eef1f6"; roundRect(g, x, 140, 225, 350, 12); g.fill(); g.fillStyle = "#4a5568"; g.font = font(800, 18); g.fillText(t, x + 16, 172);
      for (let k = 0; k < 2 + (i * 3) % 4; k++) { g.fillStyle = "#ffffff"; roundRect(g, x + 14, 190 + k * 72, 197, 58, 8); g.fill(); g.fillStyle = ["#d98433", "#3b6fd6", "#d4a52a", "#2e9c86"][i]; g.fillRect(x + 14, 190 + k * 72, 6, 58); g.fillStyle = "#c7cedb"; g.fillRect(x + 32, 206 + k * 72, 130, 9); g.fillRect(x + 32, 224 + k * 72, 90, 8); } });
  } else if (kind === "studio") {
    g.fillStyle = "#fdfdfb"; g.fillRect(0, 0, 1024, 512); g.strokeStyle = "#3b4252"; g.lineWidth = 4; g.font = font(700, 22); g.fillStyle = "#3b4252";
    const boxes = [[70, 90, "client"], [330, 90, "API"], [600, 90, "agents"], [330, 300, "brain"], [600, 300, "tests"]];
    boxes.forEach(([x, y, t]) => { roundRect(g, x, y, 190, 90, 14); g.stroke(); g.fillText(t, x + 40, y + 54); });
    [[260, 135, 330, 135], [520, 135, 600, 135], [425, 180, 425, 300], [695, 180, 695, 300]].forEach(([a, b, c2, d]) => { g.beginPath(); g.moveTo(a, b); g.lineTo(c2, d); g.stroke(); });
    [["#ffe27a", 850, 70], ["#ffb3c7", 870, 230], ["#a8e6cf", 820, 370], ["#bcd4ff", 90, 330]].forEach(([col, x, y], i) => { g.save(); g.translate(x, y); g.rotate((i - 1.5) * 0.06); g.fillStyle = col; g.fillRect(0, 0, 120, 110); g.fillStyle = "rgba(0,0,0,.25)"; g.fillRect(14, 30, 80, 6); g.fillRect(14, 50, 60, 6); g.restore(); });
  } else if (kind === "brand-sales") {
    g.fillStyle = "#fbfaf7"; g.fillRect(0, 0, 1024, 512); header("BRAND & PIPELINE", "posts, leads and proposals");
    for (let i = 0; i < 3; i++) { const x = 40 + i * 320; g.fillStyle = "#ffffff"; roundRect(g, x, 150, 290, 320, 14); g.fill(); g.strokeStyle = "#e3e7ee"; g.lineWidth = 2; g.stroke();
      g.fillStyle = acc; g.beginPath(); g.arc(x + 40, 190, 18, 0, 7); g.fill(); g.fillStyle = "#c7cedb"; g.fillRect(x + 70, 180, 150, 10); g.fillStyle = ["#e8eef9", "#f6eee0", "#e7f3ee"][i]; g.fillRect(x + 20, 225, 250, 140);
      g.fillStyle = "#c2558f"; g.font = font(700, 20); g.fillText("♥ " + (120 + i * 87), x + 20, 410); g.fillStyle = "#5b6475"; g.fillText("↗ " + (14 + i * 9), x + 140, 410); }
  } else if (kind === "ops") {
    g.fillStyle = "#fbfaf7"; g.fillRect(0, 0, 1024, 512); header("OPERATIONS", "pipeline, QA and inbox");
    for (let i = 0; i < 12; i++) { const x = 40 + (i % 6) * 160, y = 150 + Math.floor(i / 6) * 120; g.fillStyle = i % 5 === 3 ? "#fbefd9" : "#e3f3ec"; roundRect(g, x, y, 145, 100, 10); g.fill(); g.fillStyle = i % 5 === 3 ? "#d4a52a" : "#2e9c86"; g.beginPath(); g.arc(x + 22, y + 26, 8, 0, 7); g.fill(); g.fillStyle = "#5b6475"; g.fillRect(x + 16, y + 56, 100, 8); g.fillRect(x + 16, y + 74, 70, 8); }
    g.strokeStyle = acc; g.lineWidth = 4; g.beginPath(); for (let i = 0; i <= 60; i++) { const x = 40 + i * 15.6, y = 470 - 30 * Math.abs(Math.sin(i * 0.37)) - (i % 7) * 2; i ? g.lineTo(x, y) : g.moveTo(x, y); } g.stroke();
  }
  return texFrom(c);
}
/* the trading wall is live: candles move every few seconds */
function tradingCanvas() {
  const [c, g] = canvas(1024, 512); const series = []; let p = 260; for (let i = 0; i < 64; i++) { const o = p, cl = Math.max(110, Math.min(420, o + (Math.random() - 0.48) * 26)); series.push([o, cl]); p = cl; }
  const draw = () => {
    g.fillStyle = "#101826"; g.fillRect(0, 0, 1024, 512); g.fillStyle = "#e8edf6"; g.font = font(800, 28); g.fillText("TRADING DESK · DEMO", 32, 50); g.fillStyle = "#c94a5c"; g.fillRect(32, 62, 80, 4);
    g.strokeStyle = "rgba(255,255,255,.07)"; g.lineWidth = 1; for (let y = 100; y < 480; y += 60) { g.beginPath(); g.moveTo(30, y); g.lineTo(994, y); g.stroke(); }
    const all = series.flat(), lo0 = Math.min(...all), hi0 = Math.max(...all), Y = v => 120 + (v - lo0) / Math.max(1, hi0 - lo0) * 340;
    g.lineWidth = 3; series.forEach(([o, cl], i) => { const x = 36 + i * 15.2; const up = cl < o; g.strokeStyle = g.fillStyle = up ? "#45d6a8" : "#f2707e"; const a = Y(o), b = Y(cl);
      g.beginPath(); g.moveTo(x + 6, Math.min(a, b) - 14); g.lineTo(x + 6, Math.max(a, b) + 14); g.stroke(); g.fillRect(x, Math.min(a, b), 12, Math.max(4, Math.abs(b - a))); });
    g.strokeStyle = "#f0c45a"; g.lineWidth = 5; g.beginPath(); series.forEach((_, i) => { const w = series.slice(Math.max(0, i - 8), i + 1); const avg = w.reduce((s, v) => s + v[1], 0) / w.length; const x = 42 + i * 15.2; i ? g.lineTo(x, Y(avg)) : g.moveTo(x, Y(avg)); }); g.stroke();
  };
  draw(); const tex = texFrom(c);
  return { tex, step() { const last = series[series.length - 1][1]; const cl = Math.max(110, Math.min(420, last + (Math.random() - 0.48) * 26)); series.shift(); series.push([last, cl]); draw(); tex.needsUpdate = true; } };
}
function tickerTexture() {
  const [c, g] = canvas(2048, 64); g.fillStyle = "#0e1420"; g.fillRect(0, 0, 2048, 64); g.font = font(700, 30); g.textBaseline = "middle";
  const items = [["GOLD", "4143.9", "▲0.6%"], ["US500", "7695", "▲0.2%"], ["UK100", "9512", "▼0.1%"], ["EURUSD", "1.164", "▲0.1%"], ["VODL", "1.179", "▼0.3%"], ["NVDA", "212.4", "▲1.4%"], ["BTC", "118,240", "▲0.8%"]];
  let x = 20; for (let rep = 0; rep < 2; rep++) items.forEach(([s, p, ch]) => { g.fillStyle = "#e8edf6"; g.fillText(s, x, 33); x += g.measureText(s).width + 12; g.fillStyle = "#9aa6bd"; g.fillText(p, x, 33); x += g.measureText(p).width + 10; g.fillStyle = ch.startsWith("▲") ? "#3fbf9a" : "#e0606f"; g.fillText(ch, x, 33); x += g.measureText(ch).width + 44; });
  const t = texFrom(c); t.wrapS = THREE.RepeatWrapping; return t;
}
function screenUI(accent) {
  const [c, g] = canvas(256, 160); g.fillStyle = "#f4f6fa"; g.fillRect(0, 0, 256, 160); g.fillStyle = hex(accent); g.fillRect(0, 0, 256, 14);
  for (let i = 0; i < 7; i++) { g.fillStyle = i % 3 ? "#c7cedb" : "#8a94a8"; g.fillRect(14, 26 + i * 18, 60 + (i * 37) % 150, 8); } return texFrom(c);
}
function rackTexture() {
  const [c, g] = canvas(128, 512); g.fillStyle = "#1c2028"; g.fillRect(0, 0, 128, 512);
  for (let half = 0; half < 2; half++) for (let i = 0; i < 18; i++) { const y = half * 256 + 10 + i * 13.5; g.fillStyle = "#2a303b"; g.fillRect(8, y, 112, 10); for (let k = 0; k < 6; k++) { const on = ((i * 7 + k * 3 + half * 5) % 4) !== 0; g.fillStyle = on ? (k === 5 ? "#e0a030" : "#3fbf9a") : "#3a404c"; g.fillRect(80 + k * 6, y + 3, 4, 4); } }
  const t = texFrom(c); t.repeat.set(1, 0.5); return t;
}

/* ----------------------------------------------------------------------------- sky and light */
function buildSky() {
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false, toneMapped: false,
    uniforms: { top: { value: new THREE.Color() }, horizon: { value: new THREE.Color() }, bottom: { value: new THREE.Color() }, sunCol: { value: new THREE.Color() }, sunDir: { value: new THREE.Vector3(0, 1, 0) } },
    vertexShader: "varying vec3 vW; void main(){ vec4 w = modelMatrix * vec4(position,1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }",
    fragmentShader: `uniform vec3 top; uniform vec3 horizon; uniform vec3 bottom; uniform vec3 sunCol; uniform vec3 sunDir; varying vec3 vW;
      void main(){ vec3 d = normalize(vW); float h = d.y; vec3 col = h > 0.0 ? mix(horizon, top, pow(h, 0.55)) : mix(horizon, bottom, pow(-h, 0.35));
        float s = max(dot(d, normalize(sunDir)), 0.0); col += sunCol * (pow(s, 220.0) * 1.2 + pow(s, 12.0) * 0.18);
        gl_FragColor = vec4(col, 1.0);
        #include <colorspace_fragment>
      }`,
  });
  sky = new THREE.Mesh(new THREE.SphereGeometry(900, 32, 16), mat); sky.renderOrder = -10; scene.add(sky);
}
/* palette keyframes over the day (hour, colours, sun) */
const KEYS = [
  { h: 0, top: 0x0c1730, hor: 0x2a3d63, gnd: 0x161d2b, sun: 0x9fb4ff, sunI: 0.55, hemi: 0.65, el: 0.6, night: 1, exp: 1.25 },
  { h: 5, top: 0x0f1d3d, hor: 0x34466e, gnd: 0x1a2233, sun: 0x9fb4ff, sunI: 0.55, hemi: 0.65, el: 0.6, night: 1, exp: 1.25 },
  { h: 6.5, top: 0x5a7bb8, hor: 0xf2b98c, gnd: 0x6b6255, sun: 0xffb27a, sunI: 1.5, hemi: 0.85, el: 0.14, night: 0.45, exp: 1.05 },
  { h: 9, top: 0x5f9ae0, hor: 0xd9e7f5, gnd: 0x8a8f86, sun: 0xfff1dd, sunI: 3.0, hemi: 0.75, el: 0.75, night: 0, exp: 0.92 },
  { h: 15, top: 0x5f9ae0, hor: 0xd9e7f5, gnd: 0x8a8f86, sun: 0xfff1dd, sunI: 3.0, hemi: 0.75, el: 0.75, night: 0, exp: 0.92 },
  { h: 17.5, top: 0x6a8fcd, hor: 0xf4c391, gnd: 0x7d7060, sun: 0xffb36b, sunI: 2.9, hemi: 0.62, el: 0.3, night: 0.12, exp: 0.95 },
  { h: 19.5, top: 0x2e4174, hor: 0xe09470, gnd: 0x3a3540, sun: 0xff9d66, sunI: 1.0, hemi: 0.7, el: 0.06, night: 0.7, exp: 1.1 },
  { h: 21, top: 0x101e40, hor: 0x2e4068, gnd: 0x161d2b, sun: 0x9fb4ff, sunI: 0.55, hemi: 0.65, el: 0.6, night: 1, exp: 1.25 },
  { h: 24, top: 0x0c1730, hor: 0x2a3d63, gnd: 0x161d2b, sun: 0x9fb4ff, sunI: 0.55, hemi: 0.65, el: 0.6, night: 1, exp: 1.25 },
];
function londonHour() {
  if (timeOverride != null) return timeOverride;
  if (lightMode !== "live") return 17.6;
  const p = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", hour: "numeric", minute: "numeric", hourCycle: "h23" }).formatToParts(new Date());
  const v = k => Number((p.find(x => x.type === k) || {}).value || 0); return v("hour") + v("minute") / 60;
}
function applyLighting() {
  const h = londonHour(); let i = 0; while (i < KEYS.length - 2 && KEYS[i + 1].h <= h) i++;
  const a = KEYS[i], b = KEYS[i + 1], u = THREE.MathUtils.clamp((h - a.h) / Math.max(0.001, b.h - a.h), 0, 1);
  const mix = (k) => new THREE.Color(a[k]).lerp(new THREE.Color(b[k]), u), num = (k) => a[k] + (b[k] - a[k]) * u;
  const top = mix("top"), hor = mix("hor"), gnd = mix("gnd"), sc = mix("sun"); night = num("night");
  const el = num("el"), az = night > 0.9 ? 2.2 : THREE.MathUtils.mapLinear(THREE.MathUtils.clamp(h, 6, 21), 6, 21, -0.4, Math.PI + 0.4);
  const dir = new THREE.Vector3(Math.cos(az) * Math.cos(el), Math.sin(el), -Math.sin(az) * Math.cos(el) * 0.6 + 0.5).normalize();
  sky.material.uniforms.top.value.copy(top); sky.material.uniforms.horizon.value.copy(hor); sky.material.uniforms.bottom.value.copy(gnd);
  sky.material.uniforms.sunCol.value.copy(sc).multiplyScalar(night > 0.9 ? 0.25 : 1); sky.material.uniforms.sunDir.value.copy(dir);
  scene.fog.color.copy(hor).lerp(top, 0.25);
  sun.color.copy(sc); sun.intensity = num("sunI"); sun.position.copy(dir).multiplyScalar(160);
  hemi.color.copy(top).lerp(new THREE.Color(0xffffff), 0.55); hemi.groundColor.copy(gnd).lerp(new THREE.Color(0x8a8270), 0.4); hemi.intensity = num("hemi");
  renderer.toneMappingExposure = num("exp");
  envMats.forEach(([m, e]) => { m.envMapIntensity = e * (1 - 0.8 * night); });
  nightMats.forEach(({ m, base, boost }) => { m.emissiveIntensity = base + night * boost; });
  deptLights.forEach(l => { l.intensity = 40 + night * 260; });
  if (atriumLight) atriumLight.intensity = 30 + night * 90;
}

/* ----------------------------------------------------------------------------- init */
export function init(el, options = {}) {
  container = el; opts = options; clock = new THREE.Clock();
  const tq = new URLSearchParams(location.search).get("time"); if (tq != null && tq !== "") timeOverride = Number(tq) % 24;
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(MOBILE ? 1.5 : 2, window.devicePixelRatio || 1));
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace;
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene(); scene.fog = new THREE.Fog(0xdfe8f2, 280, 700);
  camera = new THREE.PerspectiveCamera(36, 1, 0.5, 2000);
  try { const pm = new THREE.PMREMGenerator(renderer); scene.environment = pm.fromScene(new RoomEnvironment(renderer), 0.04).texture; pm.dispose(); } catch (e) { /* reflections are a nicety */ }
  controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.dampingFactor = 0.07;
  controls.maxPolarAngle = Math.PI / 2.2; controls.minPolarAngle = 0.15; controls.minDistance = 10; controls.maxDistance = 340;
  raycaster = new THREE.Raycaster(); mouse = new THREE.Vector2();
  hemi = new THREE.HemisphereLight(0xeaf2ff, 0x7a725f, 0.9); scene.add(hemi);
  sun = new THREE.DirectionalLight(0xfff2e0, 2.4); sun.castShadow = true; sun.shadow.mapSize.set(MOBILE ? 1024 : 2048, MOBILE ? 1024 : 2048);
  Object.assign(sun.shadow.camera, { left: -78, right: 78, top: 78, bottom: -78, near: 20, far: 420 }); sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.03; sun.shadow.radius = 4;
  scene.add(sun); scene.add(sun.target);
  buildSky(); buildLandscape(); buildCourtyard(); buildAtrium();
  loadPerson().then(a => { if (a && lastRoster) { const st = {}; Object.values(figures).forEach(f => { st[f.name] = f.state; }); setRoster(lastRoster); Object.entries(st).forEach(([n, v]) => setState(n, v)); } });
  camera.position.set(0, 74, 122); controls.target.set(0, 0, 4);
  lastUser = performance.now();                       // the autopilot waits for a quiet spell before it starts gliding
  const el2 = renderer.domElement;
  const touch = () => { lastUser = performance.now(); tween = null; };
  el2.addEventListener("pointerdown", e => { touch(); mouse.userData = { x: e.clientX, y: e.clientY }; });
  el2.addEventListener("wheel", touch, { passive: true });
  el2.addEventListener("pointerup", e => { const d = mouse.userData; if (!d || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 5) return;
    const hit = pick(e); if (hit && hit.fig) { flyToAgent(hit.fig); if (opts.onAgentClick) opts.onAgentClick(hit.fig.name); } else if (hit && hit.dept) flyToDept(hit.dept); });
  el2.addEventListener("dblclick", e => { if (!pick(e)) overview(); });
  el2.addEventListener("pointermove", e => { const h = pick(e); const f = h && h.fig; if (hovered && hovered !== f) hovered.hover = false; hovered = f || null; if (f) f.hover = true; el2.style.cursor = h ? "pointer" : "grab"; });
  new ResizeObserver(() => resize()).observe(el); resize();
  applyLighting(); setInterval(applyLighting, 60000); setInterval(autopilot, 4000);
  setInterval(() => { if (tradeScreen && !document.hidden) tradeScreen.step(); }, 2600);
  setInterval(() => { rackTex.forEach(t => { t.offset.y = t.offset.y ? 0 : 0.5; }); }, 700);
  requestAnimationFrame(frame);
}
export function resize() {
  if (!renderer) return;
  const w = container.clientWidth || 1, h = container.clientHeight || 1;
  renderer.setSize(w, h, false); renderer.domElement.style.width = w + "px"; renderer.domElement.style.height = h + "px";
  const first = !camera.userData.sized; camera.userData.sized = true;
  camera.aspect = w / h; camera.updateProjectionMatrix(); pxSprites.forEach(sizePx);
  if (first) overview(true);                          // frame the whole campus for this screen's shape
}
export function floorView(on) { setTimeout(resize, 30); if (on) overview(); }
function pick(e) {
  const r = renderer.domElement.getBoundingClientRect();
  mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(Object.values(figures).map(f => f.hit || f.group), true);
  if (hits.length) { let o = hits[0].object; while (o && !o.userData.agent) o = o.parent; if (o) return { fig: figures[o.userData.agent] }; }
  const sh = raycaster.intersectObjects(signs, false); if (sh.length) return { dept: sh[0].object.userData.dept };
  return null;
}

/* ----------------------------------------------------------------------------- camera moves */
const ease = u => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
function flyTo(pos, target, dur = 2.4) { tween = { p0: camera.position.clone(), t0: controls.target.clone(), p1: pos, t1: target, start: performance.now(), dur: dur * 1000 }; }
export function overview(instant = false) { const k = Math.max(1, 1.3 / (camera.aspect || 1.3)); const p = new THREE.Vector3(0, 74 * k, 122 * k), t = new THREE.Vector3(0, 0, 4); if (instant) { camera.position.copy(p); controls.target.copy(t); } else flyTo(p, t, 2.4); }
function flyToAgent(f, dur = 2.2) {
  const at = f.group.position.clone(); const inward = at.clone().setY(0).normalize().multiplyScalar(-1);
  flyTo(at.clone().add(inward.multiplyScalar(24)).add(new THREE.Vector3(0, 19, 0)), at.clone().add(new THREE.Vector3(0, 2.5, 0)), dur);
}
export function flyToDept(name) {
  const d = depts[name]; if (!d) return; lastUser = performance.now();
  const c = polar((RI + RO) / 2 + 1, d.mid, 2); const inward = polar(1, d.mid).multiplyScalar(-1);
  flyTo(c.clone().add(inward.multiplyScalar(30)).add(new THREE.Vector3(0, 30, 0)), c, 2.4);
}
export function focus(name) { const f = figures[name]; if (f) flyToAgent(f); }
/* when nobody has touched the view for a while, glide to whoever is working */
function autopilot() {
  const now = performance.now(); if (now - lastUser < 45000 || tween || document.hidden) return;
  const active = Object.values(figures).filter(f => f.state === "think" || f.state === "tool" || f.state === "delegate" || f.target);
  if (active.length) { const f = active.find(x => x.target) || active[0]; if (autoFocus !== f.name || now - lastAuto > 30000) { flyToAgent(f, 3.2); autoFocus = f.name; lastAuto = now; } }
  else if (autoFocus && now - lastAuto > 40000) { overview(); autoFocus = null; }
}

/* ----------------------------------------------------------------------------- landscape */
function addTrees(spots, parent) {
  const n = spots.length; if (!n) return;
  const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.32, 0.5, 1, 7), M.trunk, n); trunks.castShadow = true;
  const blobs = LEAVES.map(m => { const im = new THREE.InstancedMesh(SHARED.blob, m, n); im.castShadow = true; im.receiveShadow = true; return im; });
  const o = new THREE.Object3D();
  spots.forEach(([x, z, s, seed], i) => { const r = rng(seed); const th = 3.6 * s;
    o.position.set(x, th / 2, z); o.rotation.set(0, 0, 0); o.scale.set(s, th, s); o.updateMatrix(); trunks.setMatrixAt(i, o.matrix);
    blobs.forEach((im, k) => { const a = k * 2.1 + r() * 0.6; const rad = (k === 0 ? 0 : 0.9) * s; o.position.set(x + Math.cos(a) * rad, th + (k === 0 ? 2.3 : 1.4) * s + r() * 0.6, z + Math.sin(a) * rad);
      const sc = (k === 0 ? 2.5 : 2.0) * s * (0.85 + r() * 0.3); o.scale.set(sc, sc * 0.88, sc); o.rotation.set(r(), r(), r()); o.updateMatrix(); im.setMatrixAt(i, o.matrix); }); });
  parent.add(trunks); blobs.forEach(b => parent.add(b));
}
function buildLandscape() {
  const ground = new THREE.Mesh(new THREE.CircleGeometry(900, 64), M.grass); ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
  scene.add(flatRing(RO + 8, RO + 30, M.meadow, 0.02));
  scene.add(flatRing(RO + 0.3, RO + 8, M.stone, 0.05)); scene.add(flatRing(RO + 8, RO + 8.6, M.stoneEdge, 0.06));
  const path = flatRing(RO + 44, RO + 48, M.stone, 0.04); scene.add(path);
  const r = rng(42); const spots = [];
  const count = MOBILE ? 44 : 90;
  for (let i = 0; i < count; i++) { const a = r() * Math.PI * 2; let rad = RO + 14 + r() * 26; if (rad > RO + 41 && rad < RO + 51) rad += 12; spots.push([Math.cos(a) * rad, -Math.sin(a) * rad, 0.85 + r() * 0.6, 1000 + i]); }
  for (let i = 0; i < (MOBILE ? 30 : 60); i++) { const a = r() * Math.PI * 2, rad = RO + 52 + r() * 70; spots.push([Math.cos(a) * rad, -Math.sin(a) * rad, 1.0 + r() * 0.8, 3000 + i]); }
  addTrees(spots, scene);
}
function buildCourtyard() {
  // raised promenade inside the ring, lawn, the pond with a stone rim, and the island the atrium stands on
  scene.add(flatRing(RPOND + 1.4, RI - 6, M.lawn, 0.03));
  scene.add(flatRing(RI - 6, RI, M.stone, FLOOR)); scene.add(curve(RI - 6, 0, FLOOR, M.stoneEdge));
  const water = new THREE.Mesh(new THREE.CircleGeometry(RPOND, 96), M.water); water.rotation.x = -Math.PI / 2; water.position.y = 0.35; scene.add(water);
  scene.add(flatRing(RPOND, RPOND + 1.4, M.stone, FLOOR)); scene.add(curve(RPOND, 0.3, FLOOR - 0.3, M.stoneEdge)); scene.add(curve(RPOND + 1.4, 0, FLOOR, M.stoneEdge));
  const island = new THREE.Mesh(new THREE.CircleGeometry(RISLAND, 64), M.stone); island.rotation.x = -Math.PI / 2; island.position.y = FLOOR; island.receiveShadow = true; scene.add(island);
  scene.add(curve(RISLAND, 0.3, FLOOR - 0.3, M.stoneEdge));
}

/* ----------------------------------------------------------------------------- the brain: a glass atrium on the island */
function buildAtrium() {
  const hq = new THREE.Group(), top = FLOOR + 16;
  hq.add(curve(RATRIUM, FLOOR, 16, M.glass, 0, Math.PI * 2, 64));
  const mull = new THREE.InstancedMesh(new THREE.BoxGeometry(0.28, 16, 0.28), M.frame, 20); const o = new THREE.Object3D();
  for (let i = 0; i < 20; i++) { o.position.copy(polar(RATRIUM, (i / 20) * Math.PI * 2, FLOOR + 8)); o.updateMatrix(); mull.setMatrixAt(i, o.matrix); } mull.castShadow = true; hq.add(mull);
  for (const y of [FLOOR + 5.4, FLOOR + 10.8]) { const band = new THREE.Mesh(new THREE.TorusGeometry(RATRIUM, 0.12, 6, 96), M.frame); band.rotation.x = Math.PI / 2; band.position.y = y; hq.add(band); }
  const roof = flatRing(RATRIUM - 0.2, RATRIUM + 2.2, M.white, top); roof.castShadow = true; hq.add(roof); hq.add(curve(RATRIUM + 2.2, top - 0.6, 0.6, M.white));
  const sky2 = new THREE.Mesh(new THREE.CircleGeometry(RATRIUM - 0.2, 48), M.glass); sky2.rotation.x = -Math.PI / 2; sky2.position.y = top - 0.05; hq.add(sky2);
  const floorIn = new THREE.Mesh(new THREE.CircleGeometry(RATRIUM, 48), M.oak); floorIn.rotation.x = -Math.PI / 2; floorIn.position.y = FLOOR + 0.02; floorIn.receiveShadow = true; hq.add(floorIn);
  const plinth = new THREE.Mesh(new THREE.CylinderGeometry(1.6, 2.4, 4, 40), M.white); plinth.position.y = FLOOR + 2; plinth.castShadow = true; hq.add(plinth);
  const lip = new THREE.Mesh(new THREE.CylinderGeometry(1.75, 1.75, 0.25, 40), M.oak); lip.position.y = FLOOR + 4.1; hq.add(lip);
  brain = new THREE.Group(); brain.position.set(0, FLOOR + 9, 0);
  const core = new THREE.Mesh(new THREE.SphereGeometry(2.3, 48, 32), glow(0xa9d2ff, 1.25, 0.6, { emissive: 0x5aa2ff, roughness: 0.15, metalness: 0.0 })); brain.add(core); brain.userData.core = core;
  const halo = new THREE.Mesh(new THREE.SphereGeometry(3.2, 48, 32), new THREE.MeshStandardMaterial({ color: 0xcfe6ff, emissive: 0x9cc9ff, emissiveIntensity: 0.35, transparent: true, opacity: 0.16, depthWrite: false, roughness: 0.1 })); brain.add(halo); brain.userData.halo = halo;
  brain.userData.rings = [4.2, 5.1].map((rad, i) => { const t = new THREE.Mesh(new THREE.TorusGeometry(rad, 0.07, 8, 128), M.frame); t.rotation.set(Math.PI / 2 + i * 0.7, i * 0.9, 0); brain.add(t); return t; });
  atriumLight = new THREE.PointLight(0x9cc9ff, 40, 34, 1.6); brain.add(atriumLight);
  hq.add(brain); scene.add(hq); setMotes(160);
  hqLabel = pxSprite(["Headquarters", "the shared brain"], { size: 15, accent: "#5a9cf0" }); hqLabel.position.set(0, top + 3.5, 0); scene.add(hqLabel);
}
function setMotes(n) {
  n = Math.round(THREE.MathUtils.clamp(n, 60, MOBILE ? 160 : 420)); if (motes && motes.userData.n === n) return;
  if (motes) { brain.remove(motes); motes.geometry.dispose(); }
  const pos = new Float32Array(n * 3); const r = rng(5);
  for (let i = 0; i < n; i++) { const u = r() * 2 - 1, a = r() * Math.PI * 2, rad = 3.3 + r() * 2.2, s = Math.sqrt(1 - u * u); pos.set([Math.cos(a) * s * rad, u * rad * 0.8, Math.sin(a) * s * rad], i * 3); }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  motes = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xbfe0ff, size: 0.2, transparent: true, opacity: 0.85, depthWrite: false })); motes.userData.n = n; brain.add(motes);
}
export function setBrain(count) {
  if (!brain || count === memories) return; memories = count; setMotes(count / 2);
  retext(hqLabel, ["Headquarters", `${count} memories in the shared brain`], { size: 15, accent: "#5a9cf0" });
}

/* ----------------------------------------------------------------------------- the ring building */
export function setRoster(list) {
  lastRoster = list;
  if (campus) { scene.remove(campus); const old = []; campus.traverse(o => { if (o.isSprite) old.push(o); }); old.forEach(dropSprite); }   // collect first: removing while traversing skips children
  Object.values(figures).forEach(f => { scene.remove(f.group); dropSprite(f.label); dropSprite(f.bubbleSprite); if (f.rig) f.rig.mixer.stopAllAction(); });
  figures = {}; depts = {}; signs = []; deptLights = []; rackTex = []; ticker = null; tradeScreen = null; treasuryBoard = null;
  campus = new THREE.Group(); scene.add(campus);
  const byOffice = {}; list.forEach(a => (byOffice[a.office] = byOffice[a.office] || []).push(a));
  const names = Object.keys(byOffice).sort((a, b) => (OFFICE_ORDER.indexOf(a) + 99) % 100 - (OFFICE_ORDER.indexOf(b) + 99) % 100);
  const n = names.length, span = Math.PI * 2 / n, gap = 0.01;
  buildShell();
  const orchard = []; slatSpots = [];
  names.forEach((name, i) => {
    const th0 = Math.PI / 2 + i * span + gap, th1 = Math.PI / 2 + (i + 1) * span - gap, mid = (th0 + th1) / 2;
    buildDepartment(name, byOffice[name], th0, th1, mid, span);
    const wedge = mid + span / 2; for (const dth of [-0.13, 0.13]) { const p = polar(RPOND + 6.8, wedge + dth); orchard.push([p.x, p.z, 0.8, 50 + i * 2 + (dth > 0 ? 1 : 0)]); }
    const bench = box(2.6, 0.45, 0.9, M.timber); bench.position.copy(polar(RPOND + 3.4, wedge, 0.55)); bench.rotation.y = wedge + Math.PI / 2; campus.add(bench);
  });
  addTrees(orchard, campus);
  if (slatSpots.length) {   // every divider's slats as one instanced mesh
    const slats = new THREE.InstancedMesh(new THREE.BoxGeometry(0.2, H - 1.6, 0.34), M.oak, slatSpots.length); const o = new THREE.Object3D();
    slatSpots.forEach(([x, y, z, a], i) => { o.position.set(x, y, z); o.rotation.set(0, a, 0); o.updateMatrix(); slats.setMatrixAt(i, o.matrix); });
    slats.castShadow = true; slats.receiveShadow = true; campus.add(slats);
  }
  if (officeInfo) setOffice(officeInfo);
}
function buildShell() {
  campus.add(flatRing(RI, RO, M.oak, FLOOR + 0.01));
  campus.add(curve(RO + 0.3, 0, FLOOR, M.concrete)); campus.add(flatRing(RO, RO + 0.3, M.concrete, FLOOR));
  campus.add(curve(RO, FLOOR, 0.45, M.white));                                            // sill
  campus.add(curve(RO, FLOOR + 0.45, H - 0.45, M.glass));                                  // full-height glass
  const mull = new THREE.InstancedMesh(new THREE.BoxGeometry(0.22, H, 0.22), M.frame, 112); const o = new THREE.Object3D();
  for (let i = 0; i < 112; i++) { const a = (i / 112) * Math.PI * 2; o.position.copy(polar(RO, a, FLOOR + H / 2)); o.rotation.y = a; o.updateMatrix(); mull.setMatrixAt(i, o.matrix); } mull.castShadow = true; campus.add(mull);
  const eave = flatRing(RO - 0.8, RO + 3.2, M.white, FLOOR + H); eave.castShadow = true; campus.add(eave);   // the white cantilevered roof edge
  campus.add(curve(RO + 3.2, FLOOR + H - 0.7, 0.7, M.white)); campus.add(curve(RO - 0.8, FLOOR + H - 0.35, 0.35, M.white));
  campus.add(curve(RI, FLOOR + H - 0.35, 0.35, M.white));                                 // slim beam on the courtyard side (no inner roof: it hid the desks)
}
function buildDepartment(name, members, th0, th1, mid, span) {
  const accent = ACCENT[name] || 0x3b6fd6; const acc = new THREE.Color(accent); const door = 2.7 / RI;
  depts[name] = { name, mid, accent, gate: polar(RI - 1.2, mid, FLOOR), prom: polar(RPROM, mid, FLOOR), rim: polar(RPOND + 0.7, mid, FLOOR), isle: polar(RATRIUM + 1.4, mid, FLOOR), centre: polar((RI + RO) / 2, mid, FLOOR), flash: 0 };
  // inner facade: glass either side of the doorway, a white door frame
  campus.add(curve(RI, FLOOR, H, M.glass, th0, mid - door - th0, 64)); campus.add(curve(RI, FLOOR, H, M.glass, mid + door, th1 - mid - door, 64));
  for (const th of [mid - door, mid + door]) { const post = box(0.35, H, 0.35, M.frame); post.position.copy(polar(RI, th, FLOOR + H / 2)); campus.add(post); }
  const lintel = box(0.45, 0.5, 2 * door * RI + 0.4, M.frame); lintel.position.copy(polar(RI, mid, FLOOR + 3.6)); lintel.rotation.y = mid; campus.add(lintel);
  // partition at th0: white base, glass above, slim cap
  // divider between wings: a white plinth with a planter, oak slats above it, a slim white cap, a white end column
  const a0 = th0 - 0.01, r0 = RI + 0.6, r1 = RO - 1.0, len = r1 - r0, rc = (r0 + r1) / 2;
  const base = box(len, 0.9, 0.7, M.white); base.position.copy(polar(rc, a0, FLOOR + 0.45)); base.rotation.y = a0 + Math.PI / 2; campus.add(base);
  const soil = box(len - 0.4, 0.06, 0.5, M.trunk, false); soil.position.copy(polar(rc, a0, FLOOR + 0.92)); soil.rotation.y = a0 + Math.PI / 2; campus.add(soil);
  for (let x = 0.8; x < len - 0.5; x += 2.2) { const leaf = new THREE.Mesh(SHARED.blob, LEAVES[Math.round(x) % 3]); leaf.scale.set(0.55, 0.42, 0.4); leaf.position.copy(polar(r0 + x, a0, FLOOR + 1.15)); leaf.castShadow = true; campus.add(leaf); }
  for (let x = 0.25; x < len; x += 0.62) slatSpots.push(polar(r0 + x, a0, FLOOR + 0.9 + (H - 1.6) / 2).toArray().concat([a0]));
  const cap = box(len, 0.18, 0.5, M.white); cap.position.copy(polar(rc, a0, FLOOR + H - 0.55)); cap.rotation.y = a0 + Math.PI / 2; campus.add(cap);
  const col = box(0.7, H, 0.7, M.white); col.position.copy(polar(r0 - 0.2, a0, FLOOR + H / 2)); campus.add(col);
  // warm interior light (brighter at night)
  const lamp = new THREE.PointLight(0xffd8a8, 40, 30, 1.6); lamp.position.copy(polar((RI + RO) / 2, mid, FLOOR + H - 0.8)); campus.add(lamp); deptLights.push(lamp);
  // walkway across the lawn, timber bridge over the pond, light strips on both edges
  const wl = RI - 6 - (RPOND + 1.4); const walk = box(4.2, FLOOR, wl, M.stone); walk.position.copy(polar(RPOND + 1.4 + wl / 2, mid, FLOOR / 2)); walk.rotation.y = mid; campus.add(walk);
  const bl = RPOND - RISLAND + 0.6; const bridge = box(3.6, 0.35, bl, M.timber); bridge.position.copy(polar(RISLAND - 0.3 + bl / 2, mid, FLOOR - 0.17)); bridge.rotation.y = mid; campus.add(bridge);
  const strip = glow(acc.clone().lerp(new THREE.Color(0xffffff), 0.35).getHex(), 0.12, 0.5);
  for (const sx of [-1, 1]) {
    const s = box(0.14, 0.06, wl, strip, false); s.position.copy(polar(RPOND + 1.4 + wl / 2, mid, FLOOR + 0.03)); s.rotation.y = mid; s.translateX(sx * 1.9); campus.add(s);
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.08, 1.1, bl), M.glass); rail.position.copy(polar(RISLAND - 0.3 + bl / 2, mid, FLOOR + 0.55)); rail.rotation.y = mid; rail.translateX(sx * 1.75); campus.add(rail);
    const cap = box(0.12, 0.08, bl, M.frame, false); cap.position.copy(polar(RISLAND - 0.3 + bl / 2, mid, FLOOR + 1.12)); cap.rotation.y = mid; cap.translateX(sx * 1.75); campus.add(cap);
  }
  depts[name].strip = strip;
  // desks: front desk in one row behind its counter, small teams in one row, larger teams in two
  const n = members.length, rows = n <= 4 ? 1 : 2, cols = Math.ceil(n / rows);
  const radii = name === "front-desk" ? [RI + 10.5] : rows === 1 ? [RI + 8.5] : [RI + 6.2, RI + 12.0];
  const dth0 = 7.0 / radii[0], used = (cols - 1) * dth0 + 7.5 / radii[0];
  const rug = flatRing(radii[0] - 3.4, radii[radii.length - 1] + 3.6, std(acc.clone().lerp(new THREE.Color(0xf3efe7), 0.8).getHex(), 1, 0, 0.1), FLOOR + 0.03, mid - used / 2, used, 32); campus.add(rug);
  const ui = screenUI(accent); const screenMat = glow(0xffffff, 0.35, 0.5, { map: ui, emissiveMap: ui, emissive: 0xffffff });
  members.forEach((a, k) => {
    const row = Math.floor(k / cols), col = k % cols, inRow = Math.min(cols, n - row * cols), r = radii[row], dth = 7.0 / r;
    const th = mid + (col - (inRow - 1) / 2) * dth;
    const deskPos = polar(r, th, FLOOR); const rot = facing(deskPos, new THREE.Vector3(0, FLOOR, 0));
    const desk = addDesk(screenMat); desk.position.copy(deskPos); desk.rotation.y = rot; campus.add(desk);
    const seat = deskPos.clone().add(new THREE.Vector3(Math.sin(rot) * 2.0, 0, Math.cos(rot) * 2.0));
    const fig = (personAsset ? makePerson : makeFigure)(a, k, accent); fig.group.position.copy(seat); fig.group.rotation.y = rot;
    fig.home = seat.clone(); fig.homeRot = rot; fig.dept = name; scene.add(fig.group);
    fig.label = pxSprite([a.name], { accent: hex(accent) }); fig.label.visible = false; scene.add(fig.label);
    figures[a.name] = fig;
  });
  // feature wall on the outer glass, facing the courtyard
  const arcLen = (RO - 0.6) * (th1 - th0); const sw = Math.min(arcLen - 10, 15), sh = sw / 2;
  let tex; if (name === "trading") { tradeScreen = tradingCanvas(); tex = tradeScreen.tex; } else tex = wallTexture(name, accent);
  mirrorU(tex); const wy = FLOOR + 3.7 + sh / 2;
  campus.add(curvedPanel(RO - 0.95, mid, sw, wy, sh, glow(0xffffff, name === "trading" ? 0.95 : 0.2, 0.35, { map: tex, emissiveMap: tex, emissive: 0xffffff, roughness: 0.5, side: THREE.BackSide })));
  campus.add(curvedPanel(RO - 0.8, mid, sw + 0.5, wy, sh + 0.5, name === "trading" ? M.darkPanel : M.white));
  if (name === "trading") {
    const tt = tickerTexture(); tt.repeat.set(-0.5, 1); ticker = tt;
    campus.add(curvedPanel(RO - 0.95, mid, sw, FLOOR + 3.1, 0.9, glow(0xffffff, 0.6, 0.3, { map: tt, emissiveMap: tt, emissive: 0xffffff, side: THREE.BackSide })));
    treasuryBoard = pxSprite(["Treasury", "0.00 GBP · level 1"], { size: 14, accent: "#d9ae45" }); treasuryBoard.position.copy(polar(RO - 1, mid, FLOOR + H + 3.4)); campus.add(treasuryBoard);
  }
  addProp(name, polar(RI + 3.2, th0 + 3.6 / (RI + 3.2), FLOOR), th0, accent);
  const plant = addPlant(); plant.position.copy(polar(RI + 2.6, th1 - 2.6 / (RI + 2.6), FLOOR)); campus.add(plant);
  const plant2 = addPlant(1.25); plant2.position.copy(polar(RO - 2.4, th1 - 2.4 / (RO - 2.4), FLOOR)); campus.add(plant2);
  // the department's board above its doorway: name plus live status (clickable: flies into the department)
  const sign = pxSprite([TITLE[name] || name, `${n} agent${n > 1 ? "s" : ""}`], { size: 15, accent: hex(accent) }); sign.position.copy(polar((RI + RO) / 2 + 2, mid, FLOOR + H + 2.2)); sign.userData.dept = name; campus.add(sign); signs.push(sign);
  depts[name].sign = sign; depts[name].count = n;
}
/* a panel that follows the curved outer wall (seen from the courtyard side) */
function curvedPanel(r, mid, width, y, h, mat) { const len = width / r; const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 40, 1, true, mid - len / 2 + Math.PI / 2, len), mat); m.position.y = y; return m; }
function mirrorU(t) { t.wrapS = THREE.RepeatWrapping; t.repeat.x = -1; t.offset.x = 1; return t; }   // cylinder interiors run right-to-left
function addDesk(screenMat) {
  const g = new THREE.Group();
  const top = box(5.4, 0.18, 2.6, M.oak); top.position.set(0, 1.85, 0); g.add(top);
  for (const sx of [-1, 1]) { const leg = box(0.16, 1.75, 2.3, M.frame); leg.position.set(sx * 2.5, 0.9, 0); g.add(leg); }
  const mon = box(2.9, 1.7, 0.1, M.monitor); mon.position.set(0, 3.05, -0.85); g.add(mon);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(2.7, 1.52), screenMat); scr.position.set(0, 3.05, -0.79); g.add(scr);
  const stand = box(0.3, 0.9, 0.3, M.monitor); stand.position.set(0, 2.3, -0.9); g.add(stand);
  const kb = box(1.8, 0.08, 0.6, M.frame, false); kb.position.set(0, 2.0, 0.35); g.add(kb);
  const lampArm = box(0.08, 1.3, 0.08, M.metal, false); lampArm.position.set(-2.1, 2.55, -0.6); g.add(lampArm);
  const shade = new THREE.Mesh(new THREE.ConeGeometry(0.32, 0.35, 16, 1, true), M.metal); shade.position.set(-2.1, 3.3, -0.5); g.add(shade);
  const bulb = new THREE.Mesh(SHARED.sphere, glow(0xfff1d6, 0.05, 1.1)); bulb.scale.setScalar(0.12); bulb.position.set(-2.1, 3.17, -0.5); g.add(bulb);
  const seat = box(1.7, 0.3, 1.7, M.fabric); seat.position.set(0, 1.05, 2.0); g.add(seat);
  const back = box(1.7, 2.0, 0.28, M.fabric); back.position.set(0, 2.2, 2.85); g.add(back);
  const post = box(0.2, 0.9, 0.2, M.metal, false); post.position.set(0, 0.5, 2.0); g.add(post);
  const sh = disc(2.4, M.shadow); sh.position.set(0, 0.04, 0.7); sh.scale.set(1.35, 0.95, 1); g.add(sh);
  return g;
}
function addPlant(s = 1) {
  const g = new THREE.Group(); const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.6, 1.3, 16), M.pot); pot.position.y = 0.65; pot.castShadow = true; g.add(pot);
  for (let k = 0; k < 6; k++) { const leaf = new THREE.Mesh(SHARED.blob, LEAVES[k % 3]); leaf.scale.setScalar(0.75); leaf.position.set(Math.cos(k * 1.05) * 0.55, 1.9 + (k % 2) * 0.5, Math.sin(k * 1.05) * 0.55); leaf.castShadow = true; g.add(leaf); }
  g.scale.setScalar(s); return g;
}
/* one signature object per department */
function addProp(name, at, th0, accent) {
  const g = new THREE.Group(); g.position.copy(at); g.rotation.y = th0 + Math.PI / 2;
  if (name === "front-desk") {
    const d = depts[name]; const counter = new THREE.Mesh(new THREE.CylinderGeometry(RI + 6.2, RI + 6.2, 2.4, 40, 1, true, d.mid + Math.PI / 2 - 0.14, 0.28), M.white); counter.position.y = FLOOR + 1.2; counter.material.side = THREE.DoubleSide; campus.add(counter);
    const ctop = flatRing(RI + 5.9, RI + 6.9, M.oak, FLOOR + 2.45, d.mid - 0.15, 0.3, 24); campus.add(ctop);
    const bowl = new THREE.Mesh(new THREE.SphereGeometry(0.6, 16, 12), std(accent, 0.4)); bowl.position.y = 0.6; g.add(bowl);
  } else if (name === "job-hunt") {   // a quiet phone booth for interviews
    const booth = box(2.6, 4.6, 2.6, M.white); booth.position.y = 2.3; g.add(booth); const door = new THREE.Mesh(new THREE.PlaneGeometry(1.7, 3.6), M.glass); door.position.set(0, 2.1, 1.31); g.add(door);
    const roofStripe = box(2.7, 0.3, 2.7, std(accent, 0.6)); roofStripe.position.y = 4.65; g.add(roofStripe);
  } else if (name === "pm") {        // stand-up table with a kanban on top
    const t = box(3.2, 0.15, 1.8, M.oak); t.position.y = 2.7; g.add(t); for (const sx of [-1, 1]) { const l = box(0.15, 2.6, 1.5, M.frame); l.position.set(sx * 1.4, 1.35, 0); g.add(l); }
    ["#ffe27a", "#ffb3c7", "#a8e6cf", "#bcd4ff"].forEach((c, i) => { const n = box(0.5, 0.04, 0.5, std(new THREE.Color(c).getHex(), 0.9), false); n.position.set(-1.1 + i * 0.72, 2.8, (i % 2) * 0.4 - 0.2); g.add(n); });
  } else if (name === "studio") {    // bean bags around a low table
    for (let i = 0; i < 2; i++) { const b = new THREE.Mesh(SHARED.sphere, std([0x7a5fcf, 0xd9c7b0][i], 0.95)); b.scale.set(1.2, 0.75, 1.2); b.position.set(-1.3 + i * 2.6, 0.75, 0); b.castShadow = true; g.add(b); }
    const t = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 0.9, 20), M.oak); t.position.set(0, 0.45, 1.3); g.add(t);
  } else if (name === "brand-sales") {   // podcast table with two mics and a soft ring light
    const t = new THREE.Mesh(new THREE.CylinderGeometry(1.3, 1.3, 0.12, 24), M.oak); t.position.y = 2.2; g.add(t); const leg = box(0.2, 2.1, 0.2, M.metal); leg.position.y = 1.05; g.add(leg);
    for (const sx of [-1, 1]) { const mic = box(0.18, 0.7, 0.18, M.metal); mic.position.set(sx * 0.6, 2.6, 0); g.add(mic); }
    const ring = new THREE.Mesh(new THREE.TorusGeometry(1.0, 0.09, 8, 48), glow(0xfff6e8, 0.4, 0.6)); ring.position.set(0, 4.1, -1.4); g.add(ring); const st = box(0.1, 3.4, 0.1, M.metal); st.position.set(0, 1.7, -1.4); g.add(st);
  } else if (name === "trading") {   // the trophy that grows with the treasury
    const plinth = box(1.6, 1.6, 1.6, M.white); plinth.position.y = 0.8; g.add(plinth);
    const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.35, 1.3, 24), M.gold); cup.position.y = 2.3; cup.castShadow = true; g.add(cup);
    for (const sx of [-1, 1]) { const h = new THREE.Mesh(new THREE.TorusGeometry(0.35, 0.07, 8, 24, Math.PI), M.gold); h.position.set(sx * 0.8, 2.4, 0); h.rotation.z = sx * Math.PI / 2; g.add(h); }
    depts.trading.trophy = cup;
  } else if (name === "ops") {       // two server racks with blinking lights
    for (let i = 0; i < 2; i++) { const t = rackTexture(); rackTex.push(t); const rack = box(1.4, 4.4, 1.4, M.dark); rack.position.set(-0.8 + i * 1.6, 2.2, 0); g.add(rack);
      const face = new THREE.Mesh(new THREE.PlaneGeometry(1.2, 4.1), new THREE.MeshStandardMaterial({ map: t, emissiveMap: t, emissive: 0xffffff, emissiveIntensity: 0.8 })); face.position.set(-0.8 + i * 1.6, 2.2, 0.71); g.add(face); }
  }
  campus.add(g);
}

/* ----------------------------------------------------------------------------- live office status */
export function setOffice(info = {}) {
  officeInfo = info; const d2 = info.depts || {};
  Object.values(depts).forEach(d => {
    const s = d2[d.name] || {}; const bits = [];
    if (s.running) bits.push(`${s.running} working`); if (s.queued) bits.push(`${s.queued} queued`);
    if (d.name === "front-desk" && info.approvals) bits.push(`${info.approvals} approval${info.approvals > 1 ? "s" : ""} for you`);
    if (d.sign) retext(d.sign, [TITLE[d.name] || d.name, bits.join(" · ") || `${d.count} agent${d.count > 1 ? "s" : ""} · quiet`], { size: 15, accent: hex(d.accent) });
  });
  const t = info.treasury; if (t && treasuryBoard) {
    retext(treasuryBoard, ["Treasury", `${Number(t.credits || 0).toFixed(2)} ${t.currency || "GBP"} · level ${t.level || 1} · ${t.wins || 0} wins`], { size: 14, accent: "#d9ae45" });
    if (depts.trading && depts.trading.trophy) depts.trading.trophy.scale.setScalar(1 + Math.min(0.8, (t.level || 1) * 0.08));
  }
}
export function setLabelMode(mode) { labelMode = mode === "all" ? "all" : "active"; }
export function setLighting(mode) { lightMode = mode === "live" ? "live" : "golden"; if (sky) applyLighting(); }

/* ----------------------------------------------------------------------------- characters */
function capsule(r, len, mat) { const m = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 6, 12), mat); m.castShadow = true; return m; }
function makeFigure(a, k, accent) {
  const group = new THREE.Group(); group.userData.agent = a.name;
  const seed = [...a.name].reduce((s, ch) => s + ch.charCodeAt(0), 0) + k;
  const skin = std(SKIN[seed % SKIN.length], 0.6, 0, 0.2), top = std(TOPS[(seed * 7) % TOPS.length], 0.75, 0, 0.2);
  const trousers = std([0x2a3042, 0x3f3f4a, 0x4a5a7a, 0x6b5a4a][seed % 4], 0.85, 0, 0.2), hairMat = std(HAIR[(seed * 3) % HAIR.length], 0.9, 0, 0.2);
  const body = new THREE.Group(); group.add(body);
  const hips = capsule(0.72, 0.3, trousers); hips.rotation.z = Math.PI / 2; hips.position.y = 2.0; body.add(hips);
  const torso = capsule(0.78, 1.2, top); torso.position.y = 3.05; torso.scale.set(1, 1, 0.78); body.add(torso);
  const badge = box(0.28, 0.36, 0.05, std(accent, 0.5), false); badge.position.set(0.32, 3.2, -0.62); body.add(badge);
  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.26, 0.35, 10), skin); neck.position.y = 3.95; body.add(neck);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.62, 20, 16), skin); head.position.y = 4.6; head.scale.set(1, 1.08, 1); head.castShadow = true; body.add(head);
  const style = seed % 5;
  if (style !== 4) { const hair = new THREE.Mesh(new THREE.SphereGeometry(0.66, 20, 12, 0, Math.PI * 2, 0, style === 1 ? Math.PI / 1.7 : Math.PI / 2.1), hairMat); hair.position.set(0, 0.06, -0.02); hair.scale.set(1, style === 2 ? 1.25 : 1, 1); head.add(hair); }
  if (style === 3) { const bun = new THREE.Mesh(new THREE.SphereGeometry(0.3, 12, 10), hairMat); bun.position.set(0, 0.62, -0.35); head.add(bun); }
  const eyeMat = std(0x1a1a22, 0.3);
  for (const sx of [-1, 1]) { const eye = new THREE.Mesh(new THREE.SphereGeometry(0.07, 8, 8), eyeMat); eye.position.set(sx * 0.22, 0.05, -0.56); head.add(eye); }
  if (seed % 3 === 0) { const glasses = new THREE.Mesh(new THREE.TorusGeometry(0.14, 0.025, 6, 16), M.metal); glasses.position.set(-0.22, 0.05, -0.6); head.add(glasses); const g2 = glasses.clone(); g2.position.x = 0.22; head.add(g2); }
  const armL = capsule(0.22, 0.9, top); armL.position.set(-0.95, 3.15, 0); body.add(armL); const armR = capsule(0.22, 0.9, top); armR.position.set(0.95, 3.15, 0); body.add(armR);
  const foreL = capsule(0.18, 0.75, skin); foreL.position.set(-0.95, 2.55, -0.6); body.add(foreL); const foreR = capsule(0.18, 0.75, skin); foreR.position.set(0.95, 2.55, -0.6); body.add(foreR);
  const legs = new THREE.Group(); group.add(legs);
  const thL = capsule(0.3, 1.0, trousers), thR = capsule(0.3, 1.0, trousers), shL = capsule(0.26, 1.0, trousers), shR = capsule(0.26, 1.0, trousers); legs.add(thL, thR, shL, shR);
  const shoeMat = std(0x2a2a30, 0.6); const shoeL = box(0.5, 0.25, 0.85, shoeMat), shoeR = box(0.5, 0.25, 0.85, shoeMat); legs.add(shoeL, shoeR);
  const light = new THREE.Mesh(SHARED.sphere, new THREE.MeshStandardMaterial({ color: STATE_COLOR.idle, emissive: STATE_COLOR.idle, emissiveIntensity: 0.4 })); light.scale.setScalar(0.2); light.position.y = 5.65; group.add(light);
  const halo = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.25, 32), new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false })); halo.rotation.x = -Math.PI / 2; halo.position.y = 0.06; group.add(halo);
  const fig = { name: a.name, accent, group, body, legs, parts: { armL, armR, foreL, foreR, thL, thR, shL, shR, shoeL, shoeR, head, light, halo }, state: "idle", seated: true, target: null, path: [], bubbleSprite: null, bubbleUntil: 0, phase: Math.random() * 6, hover: false };
  pose(fig, true); return fig;
}
const _q = new THREE.Quaternion(), AX = { x: new THREE.Vector3(1, 0, 0), y: new THREE.Vector3(0, 1, 0), z: new THREE.Vector3(0, 0, 1) };
const qa = (axis, a) => _q.setFromAxisAngle(AX[axis], a);
function makePerson(a, k, accent) {
  const group = new THREE.Group(); group.userData.agent = a.name;
  const seed = [...a.name].reduce((s, ch) => s + ch.charCodeAt(0), 0) + k;
  const model = SkeletonUtils.clone(personAsset.scene); model.scale.setScalar(personAsset.scale); model.rotation.y = Math.PI; group.add(model);
  const suit = new THREE.Color([0xeeece7, 0xe4e6ea, 0xdcd8d0, 0xd2d6dc][seed % 4]), trim = new THREE.Color(accent).multiplyScalar(0.8);
  model.traverse(o => { if (!o.isMesh) return; o.castShadow = !MOBILE; o.receiveShadow = false; o.frustumCulled = false;
    const m = o.material.clone(); if (/joint/i.test(m.name)) m.color.copy(trim); else m.color.copy(suit);
    m.roughness = 0.42; m.metalness = 0.08; m.envMapIntensity = 0.55; envMats.push([m, 0.55]); o.material = m; });
  const bones = {}; model.traverse(o => { if (o.isBone) bones[o.name.replace(/^mixamorig:?/, "")] = o; });
  const rest = {}; for (const n of ["LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg", "LeftArm", "RightArm", "LeftForeArm", "RightForeArm", "Spine"]) if (bones[n]) rest[n] = bones[n].quaternion.clone();
  const mixer = new THREE.AnimationMixer(model); const clip = n => personAsset.clips.find(c => c.name === n);
  const idle = mixer.clipAction(clip("idle")), walkA = mixer.clipAction(clip("walk"));
  idle.play(); walkA.play(); walkA.setEffectiveWeight(0); walkA.timeScale = 1.6; idle.time = (seed % 17) / 17 * idle.getClip().duration;
  const hit = new THREE.Mesh(new THREE.BoxGeometry(1.8, PERSON_HEIGHT, 1.8), new THREE.MeshBasicMaterial({ visible: false })); hit.position.y = PERSON_HEIGHT / 2; hit.userData.agent = a.name; group.add(hit);
  const light = new THREE.Mesh(SHARED.sphere, new THREE.MeshStandardMaterial({ color: STATE_COLOR.idle, emissive: STATE_COLOR.idle, emissiveIntensity: 0.4 })); light.scale.setScalar(0.18); light.position.y = PERSON_HEIGHT + 0.5; group.add(light);
  const halo = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.25, 32), new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false })); halo.rotation.x = -Math.PI / 2; halo.position.y = 0.06; group.add(halo);
  return { name: a.name, accent, group, hit, rig: { model, bones, rest, mixer, idle, walk: walkA, w: 0 }, parts: { light, halo }, state: "idle", seated: true, target: null, path: [], bubbleSprite: null, bubbleUntil: 0, phase: (seed % 31) / 5, hover: false };
}
/* blend idle/walk, then (when seated) pose the skeleton: thighs forward, knees bent, hands on the keyboard */
function rigUpdate(f, t, dt) {
  const r = f.rig, moving = !!f.target, B = r.bones, R = r.rest;
  r.w += ((moving ? 1 : 0) - r.w) * Math.min(1, dt * 6); r.walk.setEffectiveWeight(r.w); r.idle.setEffectiveWeight(1 - r.w);
  r.mixer.update(dt);
  const sit = f.seated && !moving;
  r.model.position.y += ((sit ? -SIT.drop : 0) - r.model.position.y) * Math.min(1, dt * 8); r.model.position.z = sit ? SIT.back : 0;
  f.parts.light.position.y = (sit ? PERSON_HEIGHT - SIT.drop : PERSON_HEIGHT) + 0.5;
  if (!sit) return;
  for (const s of ["Left", "Right"]) {
    if (B[s + "UpLeg"]) B[s + "UpLeg"].quaternion.copy(R[s + "UpLeg"]).multiply(qa("x", SIT.hip));
    if (B[s + "Leg"]) B[s + "Leg"].quaternion.copy(R[s + "Leg"]).multiply(qa("x", SIT.knee));
  }
  const working = f.state === "think" || f.state === "tool" || f.state === "delegate";
  for (const [s, sg] of [["Left", -1], ["Right", 1]]) {
    if (B[s + "Arm"]) B[s + "Arm"].quaternion.copy(R[s + "Arm"]).multiply(qa("z", sg * SIT.armDown)).multiply(qa("y", sg * SIT.armFwd));
    if (B[s + "ForeArm"]) B[s + "ForeArm"].quaternion.copy(R[s + "ForeArm"]).multiply(qa("y", sg * (SIT.elbow + (working ? Math.sin(t * 16 + f.phase + sg) * 0.07 : 0))));
  }
  if (B.Spine) B.Spine.quaternion.multiply(qa("x", SIT.lean));
}
export function tuneSit(o = {}) { Object.assign(SIT, o); return { ...SIT }; }
function pose(fig, seated) {
  if (fig.rig) { fig.seated = seated; return; }
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

/* ----------------------------------------------------------------------------- routes: desk -> door -> promenade -> walkway -> bridge -> atrium */
function walk(f, points, lookAt = null) { f.path = points.map(p => p.clone()); f.lookAt = lookAt; f.target = f.path.shift(); }
function promArc(a0, a1) {   // points along the promenade between two angles, the short way round
  let d = a1 - a0; while (d > Math.PI) d -= Math.PI * 2; while (d < -Math.PI) d += Math.PI * 2;
  const steps = Math.max(1, Math.ceil(Math.abs(d) / 0.22)); const pts = []; for (let i = 1; i < steps; i++) pts.push(polar(RPROM, a0 + d * i / steps, FLOOR)); return pts;
}
export function setState(name, state) {
  const f = figures[name]; if (!f) return; f.state = state;
  const c = STATE_COLOR[state] || STATE_COLOR.idle; f.parts.light.material.color.setHex(c); f.parts.light.material.emissive.setHex(c); f.parts.light.material.emissiveIntensity = state === "idle" ? 0.4 : 1.1;
  retext(f.label, STATE_WORD[state] ? [name, STATE_WORD[state]] : [name], { accent: hex(f.accent) });
}
export function say(name, text, ms = 6000) {
  const f = figures[name]; if (!f) return;
  if (/^\W*(done|finished|ok)\W*$/i.test(String(text).trim())) return;     // the status light already says it
  dropSprite(f.bubbleSprite);
  f.bubbleSprite = pxSprite([text.length > 54 ? text.slice(0, 52) + "…" : text], { size: 12, bg: "rgba(255,253,246,.97)" }); f.bubbleSprite.center.set(0.5, -1.35); f.bubbleUntil = Date.now() + ms; scene.add(f.bubbleSprite);
}
export function goBrain(name) {
  const f = figures[name]; const d = f && depts[f.dept]; if (!d) return;
  const spot = d.isle.clone().add(new THREE.Vector3((Math.random() - 0.5) * 1.6, 0, (Math.random() - 0.5) * 1.6));
  walk(f, f.seated || f.group.position.distanceTo(f.home) < 1 ? [d.gate, d.prom, d.rim, spot] : [spot], new THREE.Vector3(0, FLOOR, 0));
}
export function goHome(name) {
  const f = figures[name]; const d = f && depts[f.dept]; if (!f) return;
  if (f.group.position.distanceTo(f.home) < 0.5 && !f.target) return;
  const p = f.group.position, rad = Math.hypot(p.x, p.z); if (!d) { walk(f, [f.home]); return; }
  if (rad < RPOND + 1.5) walk(f, [d.rim, d.prom, d.gate, f.home]);                 // on the island or bridge
  else if (rad < RI - 0.5) { const a = Math.atan2(-p.z, p.x); walk(f, [polar(RPROM, a, FLOOR), ...promArc(a, d.mid), d.prom, d.gate, f.home]); }   // on the promenade
  else walk(f, [f.home]);
}
export function goTo(name, other) {
  const f = figures[name], o = figures[other]; const d = f && depts[f.dept], od = o && depts[o.dept]; if (!f || !o || !d || !od) return;
  const stop = o.home.clone().add(o.home.clone().setY(0).normalize().multiplyScalar(-3.2));
  if (f.dept === o.dept) { walk(f, [stop], o.home); return; }
  walk(f, [d.gate, d.prom, ...promArc(d.mid, od.mid), od.prom, od.gate, stop], o.home);
}
/* a small light that travels the route between a desk and the brain (memory written or read) */
export function pulse(fromName, toBrain, color = 0x5a9cf0) {
  const f = figures[fromName]; const d = f && depts[f.dept]; if (!f || !d) return;
  const lift = v => v.clone().setY(FLOOR + 1.2);
  let pts = [lift(f.group.position), lift(d.gate), lift(d.prom), lift(d.rim), new THREE.Vector3(0, FLOOR + 1.2, 0).add(polar(RATRIUM - 1, d.mid)), new THREE.Vector3(0, FLOOR + 9, 0)];
  if (!toBrain) pts = pts.reverse();
  const mesh = new THREE.Mesh(SHARED.sphere, new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 1.4 })); mesh.scale.setScalar(0.32); mesh.position.copy(pts[0]); scene.add(mesh);
  particles.push({ pts, seg: 0, mesh, speed: 26, toBrain, dept: d }); d.flash = 1;
}
export function reward(detail = {}) {
  const origin = depts.trading ? depts.trading.centre.clone().add(new THREE.Vector3(0, 9, 0)) : new THREE.Vector3(0, 12, 0);
  for (let i = 0; i < 46; i++) {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.08, 14), M.gold); m.position.copy(origin); m.rotation.set(Math.random() * 3, Math.random() * 3, 0);
    const vel = new THREE.Vector3(Math.random() - 0.5, 0.7 + Math.random() * 0.8, Math.random() - 0.5).normalize().multiplyScalar(0.22 + Math.random() * 0.3);
    particles.push({ gold: true, mesh: m, vel, u: 0 }); scene.add(m);
  }
  if (brain) brain.userData.flash = 1.0;
  const txt = pxSprite([`+${detail.pnl != null ? Number(detail.pnl).toFixed(2) : ""} ${detail.currency || ""}`.trim(), `${detail.strategy || "trade"} · treasury ${detail.treasury ?? ""}`], { size: 15, color: "#5a3e00", bg: "rgba(255,236,170,.97)", accent: "#d9ae45" });
  txt.position.copy(origin).add(new THREE.Vector3(0, 3, 0)); scene.add(txt); floaters.push({ sprite: txt, born: performance.now(), ttl: 5500 });
  if (figures["trader"]) say("trader", "profitable trade", 6000);
}

/* ----------------------------------------------------------------------------- animation */
function frame(now) {
  requestAnimationFrame(frame);
  if (document.hidden || !renderer) return;
  const busy = tween || particles.length || floaters.length || Object.values(figures).some(f => f.state !== "idle" || f.target || f.hover);
  if (!busy && now - lastFrame < 1000 / 24) return;
  lastFrame = now; const dt = Math.min(0.05, clock.getDelta()); const t = now / 1000;
  if (tween) { const u = Math.min(1, (now - tween.start) / tween.dur), e = ease(u); camera.position.lerpVectors(tween.p0, tween.p1, e); controls.target.lerpVectors(tween.t0, tween.t1, e); if (u >= 1) tween = null; }
  if (brain) {
    const flash = brain.userData.flash || 0; brain.userData.flash = Math.max(0, flash - dt * 0.5);
    brain.rotation.y += dt * 0.12; brain.userData.rings.forEach((r, i) => { r.rotation.z += dt * (0.18 + i * 0.07); });
    if (motes) motes.rotation.y -= dt * 0.05;
    const core = brain.userData.core; core.position.y = Math.sin(t * 1.1) * 0.22; core.scale.setScalar(1 + 0.025 * Math.sin(t * 2) + flash * 0.18);
    core.material.emissive.setHex(flash > 0.08 ? 0xe9b44c : 0x5aa2ff); atriumLight.color.setHex(flash > 0.08 ? 0xf2c46a : 0x9cc9ff);
    atriumLight.intensity = 30 + night * 90 + flash * 160;
  }
  Object.values(depts).forEach(d => { if (d.flash > 0) { d.flash = Math.max(0, d.flash - dt * 0.6); d.strip.emissiveIntensity = 0.12 + night * 0.5 + d.flash * 1.4; } });
  if (treasuryBoard) treasuryBoard.visible = camera.position.distanceTo(treasuryBoard.position) < 75;
  if (ticker) ticker.offset.x = (ticker.offset.x + dt * 0.035) % 1;
  for (const f of Object.values(figures)) {
    const p = f.parts, g = f.group;
    if (f.target) {
      const d = f.target.clone().sub(g.position); d.y = 0; const dist = d.length();
      if (dist < 0.35) {
        g.position.x = f.target.x; g.position.z = f.target.z; g.position.y = f.home.y;
        if (f.path.length) f.target = f.path.shift();
        else { f.target = null; const atHome = g.position.distanceTo(f.home) < 0.6; if (atHome) { g.rotation.y = f.homeRot; pose(f, true); } else if (f.lookAt) g.rotation.y = facing(g.position, f.lookAt); }
      } else {
        if (f.seated) pose(f, false); const step = Math.min(dist, dt * (f.rig ? 6.5 : 14)); g.position.add(d.normalize().multiplyScalar(step)); g.rotation.y = Math.atan2(d.x, d.z) + Math.PI;
        if (f.rig) { g.position.y = f.home.y; } else {
        const sw = Math.sin(t * 10 + f.phase) * 0.7; p.thL.rotation.x = sw; p.thR.rotation.x = -sw; p.shL.rotation.x = Math.max(0, -sw) * 0.8; p.shR.rotation.x = Math.max(0, sw) * 0.8; p.armL.rotation.x = -sw * 0.6; p.armR.rotation.x = sw * 0.6;
        g.position.y = f.home.y - 0.75 + Math.abs(Math.sin(t * 10 + f.phase)) * 0.14; }
      }
    } else if (f.rig) { /* seated or standing pose handled by rigUpdate */
    } else if (f.seated) {
      const working = f.state === "think" || f.state === "tool" || f.state === "delegate";
      if (working) { p.foreL.position.y = 2.55 + Math.sin(t * 17 + f.phase) * 0.09; p.foreR.position.y = 2.55 + Math.cos(t * 16 + f.phase) * 0.09; p.head.position.y = 4.6 + Math.sin(t * 2.3 + f.phase) * 0.03; p.head.rotation.x = -0.14; p.head.rotation.y = Math.sin(t * 1.1 + f.phase) * 0.08; }
      else { p.foreL.position.y = 2.55; p.foreR.position.y = 2.55; p.head.position.y = 4.6 + Math.sin(t * 1.2 + f.phase) * 0.04; p.head.rotation.x = Math.sin(t * 0.45 + f.phase) * 0.06; p.head.rotation.y = Math.sin(t * 0.3 + f.phase) * 0.3; }
      f.body.position.y = Math.sin(t * 1.4 + f.phase) * 0.025;
    } else if (f.lookAt) { p.foreR.rotation.x = -0.6 + Math.sin(t * 5 + f.phase) * 0.25; }
    if (f.rig) rigUpdate(f, t, dt);
    const ls = f.rig ? 0.6 : 1; p.light.scale.setScalar(ls * (f.state === "idle" ? 0.15 : 0.2 + 0.05 * Math.sin(t * 6 + f.phase)));
    p.halo.material.opacity = f.hover ? 0.9 : (f.state !== "idle" && f.state !== "done") ? 0.35 + 0.2 * Math.sin(t * 4 + f.phase) : 0;
    const head = g.position.clone().add(new THREE.Vector3(0, f.rig ? (f.seated && !f.target ? PERSON_HEIGHT - SIT.drop + 1.2 : PERSON_HEIGHT + 1.2) : (f.seated ? 6.0 : 6.9), 0));
    const bubble = f.bubbleSprite && Date.now() < f.bubbleUntil;
    const crowded = MOBILE && camera.position.distanceTo(controls.target) > 110;     // phone overview: names appear once you zoom in
    f.label.visible = f.hover || (!crowded && (labelMode === "all" || !!f.target || bubble || (f.state !== "idle" && f.state !== "done")));
    f.label.position.copy(head);
    if (f.bubbleSprite) { if (!bubble) { dropSprite(f.bubbleSprite); f.bubbleSprite = null; } else { f.bubbleSprite.position.copy(head); f.bubbleSprite.visible = !crowded || f.hover; } }
  }
  for (let i = particles.length - 1; i >= 0; i--) {
    const q = particles[i];
    if (q.gold) { q.mesh.position.add(q.vel); q.vel.y -= 0.012; q.vel.multiplyScalar(0.985); q.mesh.rotation.x += 0.2; q.u += dt * 0.5; if (q.u > 1.2 || q.mesh.position.y < FLOOR) { scene.remove(q.mesh); q.mesh.geometry.dispose(); particles.splice(i, 1); } continue; }
    let move = q.speed * dt;
    while (move > 0 && q.seg < q.pts.length - 1) { const to = q.pts[q.seg + 1]; const d = to.clone().sub(q.mesh.position); const L = d.length(); if (L <= move) { q.mesh.position.copy(to); q.seg++; move -= L; } else { q.mesh.position.add(d.multiplyScalar(move / L)); move = 0; } }
    if (q.seg >= q.pts.length - 1) { scene.remove(q.mesh); q.mesh.material.dispose(); particles.splice(i, 1); if (q.toBrain && brain) brain.userData.flash = Math.max(brain.userData.flash || 0, 0.35); }
  }
  for (let i = floaters.length - 1; i >= 0; i--) { const l = floaters[i]; const age = now - l.born; l.sprite.position.y += 0.03; l.sprite.material.opacity = Math.max(0, 1 - age / l.ttl); if (age > l.ttl) { dropSprite(l.sprite); floaters.splice(i, 1); } }
  controls.update(); renderer.render(scene, camera);
}
export function debugView() { return { cam: camera.position.toArray().map(v => +v.toFixed(1)), target: controls.target.toArray().map(v => +v.toFixed(1)), tween: !!tween, lastFrameAgo: Math.round(performance.now() - lastFrame), hidden: document.hidden, depts: Object.keys(depts), lastUser: Math.round(lastUser) }; }
export function _debugFigures() { return figures; }
export function _fly(pos, target) { lastUser = performance.now(); flyTo(pos, target, 0.5); }
