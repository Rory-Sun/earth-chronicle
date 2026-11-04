// 沙盘 3D 查看器：加载 Blender 导出的 glb + scene.json，按材质名映射 CC0 贴图，实时反射水面，
// HDRI 环境光与太阳阴影，西湖的树木用实例化卡片树（impostor），轨道控制 + 自动旋转。
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { RGBELoader } from 'three/examples/jsm/loaders/RGBELoader.js';
import { Water } from 'three/examples/jsm/objects/Water.js';

const BASE = import.meta.env.BASE_URL;
const TEX = BASE + 'dioramas/textures/';
const isMobile = /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent) || Math.min(innerWidth, innerHeight) < 600;

// 画质档位：先按显卡猜一个起点，运行 3 秒后按帧率自动升降
const TIERS = {
  high: { dpr: 2, shadow: 4096, soft: true, water: 1024, treesInReflection: true, treeShadow: true },
  mid: { dpr: 1.25, shadow: 2048, soft: true, water: 512, treesInReflection: false, treeShadow: true },
  low: { dpr: 1, shadow: 1024, soft: false, water: 256, treesInReflection: false, treeShadow: false },
};
function guessTier(renderer) {
  if (isMobile) return 'mid';
  try {
    const gl = renderer.getContext(); const ext = gl.getExtension('WEBGL_debug_renderer_info');
    const gpu = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : '';
    if (/Intel|Mali|Adreno|PowerVR|SwiftShader|llvmpipe/i.test(gpu)) return 'mid';
  } catch (e) { /* ignore */ }
  return 'high';
}

// 材质名 → 贴图/参数（贴图名对应 public/dioramas/textures/<set>_<kind>.jpg）
const TILE = (tint) => ({ set: 'RoofingTiles014A', gray: true, repeat: 0.38, tint, roughness: 0.42, envMapIntensity: 0.9 });
const MATERIALS = {
  GlazedGold: TILE([1.75, 1.3, 0.35]), GlazedGreen: TILE([0.45, 1.1, 0.75]), GlazedBlack: TILE([0.35, 0.4, 0.5]),
  GreyTile: TILE([0.75, 0.78, 0.82]), DaiWa: TILE([0.55, 0.58, 0.64]), BronzeTile: TILE([1.1, 0.9, 0.55]),
  WhiteMarble: { set: 'Marble020', repeat: 0.5, tint: [1.15, 1.12, 1.05], roughness: 0.5 },
  StonePaving: { set: 'PavingStones128', repeat: 0.7, tint: [1.05, 1.05, 1.0], roughness: 0.85 },
  Granite: { set: 'Rock051', normalOnly: true, repeat: 1.5, roughness: 0.8 },
  Grass: { set: 'Grass004', repeat: 0.8, tint: [0.95, 1.0, 0.72], roughness: 0.95 },
  Lawn: { set: 'Grass004', repeat: 0.9, tint: [0.95, 1.0, 0.72], roughness: 0.95 },
  Terrain: { set: 'Grass004', repeat: 0.8, tint: [1.0, 1.02, 0.78], roughness: 0.95, vertexColors: true },
  EarthCut: { set: 'Rock051', repeat: 0.14, tint: [1.5, 1.4, 1.2], roughness: 0.95, vertexColors: true },
  LakeBed: { tint: [1, 1, 1], roughness: 0.9, vertexColors: true },
  Leaf: { tint: [1, 1, 1], roughness: 0.9, vertexColors: true },
  Dirt: { set: 'Rock051', repeat: 0.5, tint: [1.2, 1.05, 0.85], roughness: 0.95 },
  GardenRock: { set: 'Rock051', repeat: 0.6, tint: [1.0, 0.98, 0.9], roughness: 0.9 },
  Finial: { metalness: 0.9, roughness: 0.3 }, GoldTrim: { metalness: 0.6, roughness: 0.4 },
};
const WATER = { Water: { color: 0x1d5a5c, distortion: 0.35, size: 2.5 }, LakeWater: { color: 0x3f8f7c, distortion: 0.5, size: 3.5 } };

const texCache = new Map();
function loadTexture(name, { gray = false, srgb = true } = {}) {
  const key = name + (gray ? '#g' : '');
  if (texCache.has(key)) return texCache.get(key);
  const p = new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      let tex;
      if (gray) {
        const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
        const ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
        const d = ctx.getImageData(0, 0, c.width, c.height);
        for (let i = 0; i < d.data.length; i += 4) { const l = d.data[i] * 0.3 + d.data[i + 1] * 0.59 + d.data[i + 2] * 0.11; d.data[i] = d.data[i + 1] = d.data[i + 2] = l; }
        ctx.putImageData(d, 0, 0);
        tex = new THREE.CanvasTexture(c);
      } else tex = new THREE.Texture(img);
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      tex.anisotropy = 8;
      tex.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      tex.needsUpdate = true;
      resolve(tex);
    };
    img.onerror = () => resolve(null);
    img.src = TEX + name + '.jpg';
  });
  texCache.set(key, p);
  return p;
}

async function applyMaterial(mesh) {
  const m = mesh.material; if (!m) return;
  const spec = MATERIALS[m.name];
  if (!spec) { m.roughness = Math.min(0.95, Math.max(0.35, m.roughness)); return; }
  const mat = new THREE.MeshStandardMaterial({ color: m.color.clone(), roughness: spec.roughness ?? m.roughness, metalness: spec.metalness ?? m.metalness });
  if (spec.tint) mat.color.multiply(new THREE.Color(...spec.tint));
  if (spec.vertexColors && mesh.geometry.attributes.color) mat.vertexColors = true;
  if (spec.envMapIntensity != null) mat.envMapIntensity = spec.envMapIntensity;
  if (spec.set) {
    const [col, nor, rgh] = await Promise.all([
      spec.normalOnly ? null : loadTexture(spec.set + '_Color', { gray: !!spec.gray }),
      loadTexture(spec.set + '_NormalGL', { srgb: false }),
      spec.normalOnly ? null : loadTexture(spec.set + '_Roughness', { srgb: false }),
    ]);
    for (const t of [col, nor, rgh]) if (t) { t.repeat.set(spec.repeat, spec.repeat); }
    if (col) { mat.map = col; if (spec.gray) mat.color.multiplyScalar(1.0); }
    if (nor) { mat.normalMap = nor; mat.normalScale.set(0.7, 0.7); }
    if (rgh) { mat.roughnessMap = rgh; mat.roughness = 1.0; }
    if (spec.gray && col) { mat.color.multiplyScalar(1.15); }
  }
  mesh.material = mat;
}

function makeWaterNormals(n = 256) {
  const c = document.createElement('canvas'); c.width = c.height = n;
  const ctx = c.getContext('2d'); const d = ctx.createImageData(n, n);
  const h = new Float32Array(n * n);
  const waves = [[3, 1, 0.5], [5, -2, 0.3], [-2, 7, 0.25], [8, 3, 0.15], [11, -6, 0.1], [1, 13, 0.08]];
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    let v = 0; for (const [a, b, amp] of waves) v += amp * Math.sin(2 * Math.PI * (a * x + b * y) / n + a);
    h[y * n + x] = v;
  }
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const dx = h[y * n + (x + 1) % n] - h[y * n + (x + n - 1) % n];
    const dy = h[((y + 1) % n) * n + x] - h[((y + n - 1) % n) * n + x];
    const nx = -dx * 1.5, ny = -dy * 1.5, nz = 1; const l = Math.hypot(nx, ny, nz);
    const i = (y * n + x) * 4;
    d.data[i] = 128 + 127 * nx / l; d.data[i + 1] = 128 + 127 * ny / l; d.data[i + 2] = 128 + 127 * nz / l; d.data[i + 3] = 255;
  }
  ctx.putImageData(d, 0, 0);
  const tex = new THREE.CanvasTexture(c); tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.colorSpace = THREE.NoColorSpace;
  return tex;
}

function sunDirection(eulerDeg) {
  // Blender 太阳灯：绕 X 转 θ 再绕 Z 转 φ，光束方向 (−sinφ sinθ, cosφ sinθ, −cosθ)；太阳在其反方向
  const th = THREE.MathUtils.degToRad(eulerDeg[0]), ph = THREE.MathUtils.degToRad(eulerDeg[2]);
  const d = new THREE.Vector3(-Math.sin(ph) * Math.sin(th), Math.cos(ph) * Math.sin(th), -Math.cos(th));
  return toThree(d.negate());
}
function toThree(v) { return new THREE.Vector3(v.x, v.z, -v.y); }   // Blender Z-up → three Y-up

function impostorAtlas(front, top, pink) {
  const c = document.createElement('canvas'); c.width = 1024; c.height = 1024;
  const ctx = c.getContext('2d');
  ctx.drawImage(front, 0, 0, 512, 1024);
  ctx.drawImage(top, 512, 0, 512, 512);
  if (pink) { ctx.globalCompositeOperation = 'source-atop'; ctx.fillStyle = 'rgba(245,150,175,0.72)'; ctx.fillRect(0, 0, 1024, 1024); }
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
  return tex;
}
function impostorGeometry(fh, fw, top, kind) {
  // 两张交叉的正视面片 + 一张俯视面片（树冠高度处）；UV 指向图集的左半/右上
  const pos = [], uv = [], nrm = [], idx = [];
  const quad = (pts, uvs, n) => { const b = pos.length / 3; for (const p of pts) pos.push(...p); for (const u of uvs) uv.push(...u); for (let i = 0; i < 4; i++) nrm.push(...n); idx.push(b, b + 1, b + 2, b, b + 2, b + 3); };
  const hw = fw / 2;
  quad([[-hw, 0, 0], [hw, 0, 0], [hw, fh, 0], [-hw, fh, 0]], [[0, 0], [0.5, 0], [0.5, 1], [0, 1]], [0, 0, 1]);
  quad([[0, 0, -hw], [0, 0, hw], [0, fh, hw], [0, fh, -hw]], [[0, 0], [0.5, 0], [0.5, 1], [0, 1]], [1, 0, 0]);
  const ht = top / 2, y = kind === 'bush' ? fh * 0.5 : fh * 0.62;
  quad([[-ht, y, ht], [ht, y, ht], [ht, y, -ht], [-ht, y, -ht]], [[0.5, 0.5], [1, 0.5], [1, 1], [0.5, 1]], [0, 1, 0]);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  g.setIndex(idx);
  return g;
}
function loadImage(url) { return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; }); }

async function buildPlants(scene, meta, onProgress) {
  const plants = meta.plants; if (!plants || !plants.length) return 0;
  const treesMeta = await (await fetch(BASE + 'dioramas/trees/trees.json')).json();
  const groups = new Map();   // key(kind_idx[+pink]) → [[x,y,z,h,rot]...]
  for (const [kind, vi, x, y, z, h, rot] of plants) {
    const src = kind === 'peach' ? 'willow' : kind;
    const key = `${src}_${vi}${kind === 'peach' ? '#pink' : ''}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push([x, y, z, h, rot]);
  }
  let done = 0;
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  for (const [key, list] of groups) {
    const base = key.replace('#pink', ''); const pink = key.endsWith('#pink');
    const info = treesMeta[base]; if (!info) continue;
    const [front, top] = await Promise.all([loadImage(BASE + `dioramas/trees/${base}_front.png`), loadImage(BASE + `dioramas/trees/${base}_top.png`)]);
    const tex = impostorAtlas(front, top, pink);
    const geo = impostorGeometry(info.front_h, info.front_w, info.top, info.kind);
    const mat = new THREE.MeshStandardMaterial({ map: tex, alphaTest: 0.45, side: THREE.DoubleSide, roughness: 0.9, metalness: 0 });
    const mesh = new THREE.InstancedMesh(geo, mat, list.length);
    mesh.customDepthMaterial = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, map: tex, alphaTest: 0.45, side: THREE.DoubleSide });
    mesh.castShadow = true; mesh.receiveShadow = false; mesh.frustumCulled = false;
    list.forEach(([x, y, z, h, rot], i) => {
      p.set(x, z, -y); q.setFromAxisAngle(up, rot); s.set(h, h, h);
      m4.compose(p, q, s); mesh.setMatrixAt(i, m4);
    });
    mesh.instanceMatrix.needsUpdate = true;
    scene.add(mesh);
    done += list.length; onProgress && onProgress(done / plants.length);
  }
  return plants.length;
}

export async function startDiorama(id, ui) {
  const canvas = document.getElementById('scene');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
  let tier = guessTier(renderer);
  const applyTier = () => { const q = TIERS[tier]; renderer.setPixelRatio(Math.min(devicePixelRatio, q.dpr)); renderer.shadowMap.type = q.soft ? THREE.PCFSoftShadowMap : THREE.PCFShadowMap; };
  applyTier();
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 0.98;
  renderer.setClearColor(0x000000, 0);

  const meta = await (await fetch(BASE + `dioramas/${id}/scene.json`)).json();
  ui.setTitle(meta.title);
  const scene = new THREE.Scene();
  const fogC = new THREE.Color(...(meta.fog || [0.9, 0.9, 0.9]));
  scene.fog = new THREE.Fog(fogC, meta.camera.dist * 1.3, meta.camera.dist * 3.2);

  // 相机
  const cam = meta.camera;
  const target = toThree(new THREE.Vector3(...cam.target));
  const az = THREE.MathUtils.degToRad(cam.az), pitch = THREE.MathUtils.degToRad(cam.pitch);
  const posB = new THREE.Vector3(cam.target[0] + Math.sin(az) * Math.cos(pitch) * cam.dist, cam.target[1] - Math.cos(az) * Math.cos(pitch) * cam.dist, cam.target[2] + Math.sin(pitch) * cam.dist);
  const hfov = 2 * Math.atan(18 / cam.lens);
  const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 1, 4000);
  const fitFov = () => { camera.aspect = innerWidth / innerHeight; camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(hfov / 2) / Math.max(camera.aspect, 0.6))); camera.updateProjectionMatrix(); };
  camera.position.copy(toThree(posB)); fitFov();
  const controls = new OrbitControls(camera, canvas);
  controls.target.copy(target); controls.enableDamping = true; controls.dampingFactor = 0.06;
  controls.minDistance = cam.min_dist; controls.maxDistance = cam.max_dist;
  controls.minPolarAngle = THREE.MathUtils.degToRad(12); controls.maxPolarAngle = THREE.MathUtils.degToRad(82);
  controls.autoRotate = true; controls.autoRotateSpeed = 0.35; controls.enablePan = !isMobile;
  controls.update();

  // 灯光：太阳（阴影）+ 环境 HDRI + 天光
  const sunDir = sunDirection(meta.sun.euler_deg);
  const sun = new THREE.DirectionalLight(new THREE.Color(...meta.sun.color), 3.2);
  sun.position.copy(target).addScaledVector(sunDir, 500); sun.target.position.copy(target);
  sun.castShadow = true;
  const half = meta.shadow_half || 110;
  sun.shadow.camera.left = -half; sun.shadow.camera.right = half; sun.shadow.camera.top = half; sun.shadow.camera.bottom = -half;
  sun.shadow.camera.near = 50; sun.shadow.camera.far = 1000;
  sun.shadow.mapSize.set(TIERS[tier].shadow, TIERS[tier].shadow);
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.35; sun.shadow.radius = 2;
  scene.add(sun, sun.target);
  scene.add(new THREE.HemisphereLight(0xbfd4ee, 0x6a7a55, 0.55));
  try {
    const hdr = await new RGBELoader().loadAsync(BASE + 'dioramas/env/kloppenheim_06_puresky_1k.hdr');
    hdr.mapping = THREE.EquirectangularReflectionMapping;
    const pm = new THREE.PMREMGenerator(renderer); scene.environment = pm.fromEquirectangular(hdr).texture;
    scene.environmentIntensity = 0.45; hdr.dispose(); pm.dispose();
  } catch (e) { console.warn('HDRI 加载失败', e); }

  // 模型
  ui.status('加载模型…');
  const draco = new DRACOLoader(); draco.setDecoderPath(BASE + 'draco/');
  const loader = new GLTFLoader(); loader.setDRACOLoader(draco);
  const gltf = await loader.loadAsync(BASE + `dioramas/${id}/scene.glb`, (e) => { if (e.total) ui.progress(0.1 + 0.5 * e.loaded / e.total); });
  const root = gltf.scene;
  const waterMeshes = [];
  const tasks = [];
  root.traverse((o) => {
    if (!o.isMesh) return;
    if (meta.water && meta.water.includes(o.material?.name)) { waterMeshes.push(o); return; }
    o.castShadow = true; o.receiveShadow = true;
    tasks.push(applyMaterial(o));
  });
  await Promise.all(tasks);
  scene.add(root);
  ui.progress(0.65);

  // 水面：用 glb 里的水面几何做实时反射
  const waterNormals = makeWaterNormals();
  const waters = [];
  for (const wm of waterMeshes) {
    const spec = WATER[wm.material.name] || WATER.LakeWater;
    const geo = wm.geometry.clone(); wm.updateWorldMatrix(true, false); geo.applyMatrix4(wm.matrixWorld); geo.rotateX(Math.PI / 2);
    const water = new Water(geo, {
      textureWidth: TIERS[tier].water, textureHeight: TIERS[tier].water, waterNormals, sunDirection: sunDir.clone(),
      sunColor: new THREE.Color(...meta.sun.color), waterColor: spec.color, distortionScale: spec.distortion, fog: true,
    });
    water.rotation.x = -Math.PI / 2;
    water.material.uniforms.size.value = spec.size;
    water.material.uniforms.alpha.value = 0.96;
    water.receiveShadow = true;
    wm.removeFromParent();
    scene.add(water); waters.push(water);
  }

  // 树木（西湖）
  if (meta.plants) { ui.status('种树…'); await buildPlants(scene, meta, (f) => ui.progress(0.65 + 0.33 * f)); }
  const trees = []; scene.traverse((o) => { if (o.isInstancedMesh) trees.push(o); });
  // 水面反射里按档位决定是否画树（反射要把整个场景再画一遍）
  for (const w of waters) {
    const orig = w.onBeforeRender;
    w.onBeforeRender = function (r, s, c, g, m, gr) {
      const hide = !TIERS[tier].treesInReflection;
      if (hide) for (const t of trees) t.visible = false;
      orig.call(this, r, s, c, g, m, gr);
      if (hide) for (const t of trees) t.visible = true;
    };
  }
  const setTier = (name) => {
    if (!TIERS[name] || name === tier) return;
    tier = name; applyTier();
    const q = TIERS[tier];
    if (sun.shadow.map) { sun.shadow.map.dispose(); sun.shadow.map = null; }
    sun.shadow.mapSize.set(q.shadow, q.shadow);
    for (const t of trees) t.castShadow = q.treeShadow;
    scene.traverse((o) => { if (o.material) o.material.needsUpdate = true; });
    ui.tier && ui.tier(tier);
  };
  ui.progress(1); ui.ready(); ui.tier && ui.tier(tier);

  // 循环
  const clock = new THREE.Clock();
  let autoTimer = 0;
  // 自适应画质：前几秒按实际帧率升降档
  let frames = 0, fpsT = 0, checks = 0;
  const adapt = (dt) => {
    frames++; fpsT += dt;
    if (fpsT < 3) return;
    const fps = frames / fpsT; frames = 0; fpsT = 0; checks++;
    if (checks > 4) return;
    if (fps < 24 && tier === 'high') setTier('mid');
    else if (fps < 20 && tier === 'mid') setTier('low');
    else if (fps > 56 && tier === 'mid' && checks <= 2) setTier('high');
  };
  const onInteract = () => { controls.autoRotate = false; clearTimeout(autoTimer); autoTimer = setTimeout(() => { if (ui.autoRotateWanted()) controls.autoRotate = true; }, 6000); };
  canvas.addEventListener('pointerdown', onInteract); canvas.addEventListener('wheel', onInteract, { passive: true });
  addEventListener('resize', () => { renderer.setSize(innerWidth, innerHeight); fitFov(); });
  renderer.setSize(innerWidth, innerHeight);
  renderer.setAnimationLoop(() => {
    const dt = clock.getDelta();
    if (document.visibilityState === 'visible') adapt(Math.min(dt, 0.25));
    for (const w of waters) w.material.uniforms.time.value += dt * 0.35;
    controls.update();
    renderer.render(scene, camera);
  });
  return { scene, camera, controls, renderer, setAutoRotate: (v) => { controls.autoRotate = v; }, setTier, getTier: () => tier };
}