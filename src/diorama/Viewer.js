// 沙盘 3D 查看器：加载 Blender 导出的 glb + scene.json，按材质名映射 CC0 贴图，实时反射水面（西湖用 LakeSurface.js），
// HDRI 环境光与太阳阴影，西湖的树木用实例化卡片树（impostor），轨道控制 + 自动旋转。
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { RGBELoader } from 'three/examples/jsm/loaders/RGBELoader.js';
import { Water } from 'three/examples/jsm/objects/Water.js';
import { LakeSurface } from './LakeSurface.js';
import { makeBillboardTrees } from './TreeBillboards.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/examples/jsm/postprocessing/GTAOPass.js';
import { BokehPass } from 'three/examples/jsm/postprocessing/BokehPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { SMAAPass } from 'three/examples/jsm/postprocessing/SMAAPass.js';
import { VignetteShader } from 'three/examples/jsm/shaders/VignetteShader.js';

const BASE = import.meta.env.BASE_URL;
const TEX = BASE + 'dioramas/textures/';
const isMobile = /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent) || Math.min(innerWidth, innerHeight) < 600;

// 画质档位：先按显卡猜一个起点，运行 3 秒后按帧率自动升降
const TIERS = {
  high: { dpr: 2, shadow: 4096, soft: true, water: 1024, treesInReflection: true, treeShadow: true, gtao: true, dof: true, bloom: true, aa: true },
  mid: { dpr: 1.25, shadow: 2048, soft: true, water: 512, treesInReflection: false, treeShadow: true, gtao: false, dof: true, bloom: true, aa: true },
  low: { dpr: 1, shadow: 1024, soft: false, water: 256, treesInReflection: false, treeShadow: false, gtao: false, dof: false, bloom: false, aa: false },
};

function gradientTexture(c0, c1) {
  const c = document.createElement('canvas'); c.width = 4; c.height = 256;
  const ctx = c.getContext('2d'); const g = ctx.createLinearGradient(0, 0, 0, 256);
  const css = (v) => 'rgb(' + v.map((x) => Math.round(x * 255)).join(',') + ')';
  g.addColorStop(0, css(c0)); g.addColorStop(1, css(c1));
  ctx.fillStyle = g; ctx.fillRect(0, 0, 4, 256);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; return tex;
}
function guessTier(renderer) {
  if (isMobile) return 'mid';
  try {
    const gl = renderer.getContext(); const ext = gl.getExtension('WEBGL_debug_renderer_info');
    const gpu = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : '';
    if (/Intel|Mali|Adreno|PowerVR|SwiftShader|llvmpipe/i.test(gpu)) return 'mid';
  } catch (e) { /* ignore */ }
  return 'high';
}

// 材质名 → 贴图/参数（贴图名对应 public/dioramas/textures/<set>_<kind>.webp，由 tools/optimize_web_assets.py 压缩）
const TILE = (tint) => ({ set: 'RoofingTiles014A', gray: true, repeat: 0.38, tint, roughness: 0.42, envMapIntensity: 0.9 });
const MATERIALS = {
  GlazedGold: TILE([1.75, 1.3, 0.35]), GlazedGreen: TILE([0.45, 1.1, 0.75]), GlazedBlack: TILE([0.35, 0.4, 0.5]),
  GreyTile: TILE([0.75, 0.78, 0.82]), DaiWa: TILE([0.55, 0.58, 0.64]), BronzeTile: TILE([1.1, 0.9, 0.55]),
  WhiteMarble: { set: 'Marble020', repeat: 0.5, tint: [1.15, 1.12, 1.05], roughness: 0.5 },
  StonePaving: { set: 'PavingStones128', repeat: 0.7, tint: [1.05, 1.05, 1.0], roughness: 0.85 },
  Granite: { set: 'Rock051', normalOnly: true, repeat: 1.5, roughness: 0.8 },
  // 草地不用粗糙度贴图（matte）：那张图偏亮滑，太阳会在草坡上打出一片片白色高光
  Grass: { set: 'Grass004', repeat: 0.8, tint: [0.95, 1.0, 0.72], roughness: 0.95, matte: true },
  Lawn: { set: 'Grass004', repeat: 0.9, tint: [0.95, 1.0, 0.72], roughness: 0.95, matte: true },
  Terrain: { set: 'Grass004', repeat: 0.8, tint: [1.0, 1.02, 0.78], roughness: 0.95, vertexColors: true, matte: true },
  EarthCut: { set: 'Rock051', repeat: 0.14, tint: [1.5, 1.4, 1.2], roughness: 0.95, vertexColors: true },
  LakeBed: { tint: [1, 1, 1], roughness: 0.9, vertexColors: true },
  Leaf: { tint: [1, 1, 1], roughness: 0.9, vertexColors: true },
  Dirt: { set: 'Rock051', repeat: 0.5, tint: [1.2, 1.05, 0.85], roughness: 0.95 },
  GardenRock: { set: 'Rock051', repeat: 0.6, tint: [1.0, 0.98, 0.9], roughness: 0.9 },
  Finial: { metalness: 0.9, roughness: 0.3 }, GoldTrim: { metalness: 0.6, roughness: 0.4 },
  Steel: { metalness: 0.6, roughness: 0.45 }, Concrete: { set: 'Rock051', normalOnly: true, repeat: 1.2, roughness: 0.85 }, Asphalt: { roughness: 0.95 },
  Reed: { roughness: 0.9 }, ReedHead: { roughness: 0.95 },
  HuiWa: TILE([0.85, 0.87, 0.9]), Kerb: { set: 'PavingStones128', normalOnly: true, repeat: 2.0, roughness: 0.9 }, FlatRoof: { roughness: 0.95 },
  Hedge: { roughness: 0.95 }, Facade3: { roughness: 0.7 },
  HillRock: { set: 'Rock051', repeat: 0.8, tint: [1.0, 0.97, 0.9], roughness: 0.9 },
  Glass: { metalness: 0.7, roughness: 0.18, envMapIntensity: 1.2 }, RedBrick: { set: 'PavingStones128', normalOnly: true, repeat: 1.5, roughness: 0.85 },
};
// 苏州园林（1 单位 = 1 米）的材质
Object.assign(MATERIALS, {
  FangZhuan: { set: 'PavingStones128', repeat: 0.42, tint: [0.92, 0.94, 0.92], roughness: 0.9 },
  JieShi: { set: 'PavingStones128', repeat: 0.36, tint: [0.86, 0.86, 0.83], roughness: 0.9 },
  TaiDi: { set: 'Grass004', repeat: 0.33, tint: [1.35, 1.25, 1.0], roughness: 0.95, vertexColors: true, matte: true },
  ChiDi: { tint: [1, 1, 1], roughness: 0.9, vertexColors: true },
  TaiHuShi: { set: 'Rock051', normalOnly: true, repeat: 0.6, tint: [1.12, 1.12, 1.09], roughness: 0.88, vertexColors: true },
  HuangShi: { set: 'Rock051', normalOnly: true, repeat: 0.5, roughness: 0.9, vertexColors: true },
  JinShanShi: { set: 'Rock051', normalOnly: true, repeat: 1.2, roughness: 0.85 }, ShiBan: { set: 'Rock051', normalOnly: true, repeat: 1.0, roughness: 0.9 },
  FenQiang: { roughness: 0.92 }, LiKeMu: { roughness: 0.55 }, ChuangGe: { roughness: 0.6 }, ChuangAn: { roughness: 0.2, envMapIntensity: 1.2 },
  WaLong: { roughness: 0.6 }, WuJi: { roughness: 0.65 }, QingZhuan: { roughness: 0.85 }, HuaJie: { set: 'PavingStones128', normalOnly: true, repeat: 2.5, roughness: 0.85 },
});
const WATER = { Water: { color: 0x1d5a5c, distortion: 0.35, size: 2.5 }, LakeWater: { color: 0x4f6b78, distortion: 0.9, size: 2.6 }, RiverWater: { color: 0x7a6442, distortion: 0.6, size: 3.0 } };

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
    img.src = TEX + name + '.webp';
  });
  texCache.set(key, p);
  return p;
}

let MAT_OVERRIDE = {};   // scene.json 的 mat 字段：逐场景覆盖贴图比例等
async function applyMaterial(mesh) {
  const m = mesh.material; if (!m) return;
  const spec = MATERIALS[m.name] ? Object.assign({}, MATERIALS[m.name], MAT_OVERRIDE[m.name]) : null;
  if (!spec) { m.roughness = Math.min(0.95, Math.max(0.35, m.roughness)); return; }
  const mat = new THREE.MeshStandardMaterial({ color: m.color.clone(), roughness: spec.roughness ?? m.roughness, metalness: spec.metalness ?? m.metalness });
  if (spec.tint) mat.color.multiply(new THREE.Color(...spec.tint));
  if (spec.vertexColors && mesh.geometry.attributes.color) mat.vertexColors = true;
  if (spec.envMapIntensity != null) mat.envMapIntensity = spec.envMapIntensity;
  if (spec.set) {
    const [col, nor, rgh] = await Promise.all([
      spec.normalOnly ? null : loadTexture(spec.set + '_Color', { gray: !!spec.gray }),
      loadTexture(spec.set + '_NormalGL', { srgb: false }),
      spec.normalOnly || spec.matte ? null : loadTexture(spec.set + '_Roughness', { srgb: false }),
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
  // 多方向、多尺度的正弦波叠加（整数波数保证可平铺），振幅随波数衰减，相位随机：避免少数几组波形成规则格子
  let seed = 7; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const waves = [];
  for (let i = 0; i < 22; i++) {
    const k = 2 + Math.floor(rnd() * 26), ang = rnd() * Math.PI;
    const a = Math.round(k * Math.cos(ang)), b = Math.round(k * Math.sin(ang));
    if (a === 0 && b === 0) continue;
    waves.push([a, b, 0.55 * Math.pow(Math.hypot(a, b), -1.1), rnd() * 2 * Math.PI]);
  }
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    let v = 0; for (const [a, b, amp, ph] of waves) v += amp * Math.sin(2 * Math.PI * (a * x + b * y) / n + ph);
    h[y * n + x] = v;
  }
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const dx = h[y * n + (x + 1) % n] - h[y * n + (x + n - 1) % n];
    const dy = h[((y + 1) % n) * n + x] - h[((y + n - 1) % n) * n + x];
    const nx = -dx * 2.2, ny = -dy * 2.2, nz = 1; const l = Math.hypot(nx, ny, nz);
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

function impostorAtlas(front, top, tint) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 512;
  const ctx = c.getContext('2d');
  ctx.drawImage(front, 0, 0, 256, 512);
  ctx.drawImage(top, 256, 0, 256, 256);
  if (tint) { ctx.globalCompositeOperation = 'source-atop'; ctx.fillStyle = tint; ctx.fillRect(0, 0, 512, 512); }
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
  return tex;
}
function tintedAtlas(img, tint) {
  // 公告牌图集：原图画进画布，需要时整体染色（枫红、银杏黄、桃花粉）
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
  const ctx = c.getContext('2d');
  ctx.drawImage(img, 0, 0);
  if (tint) { ctx.globalCompositeOperation = 'source-atop'; ctx.fillStyle = tint; ctx.fillRect(0, 0, c.width, c.height); }
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  return tex;
}
function impostorGeometry(fh, fw, top, kind, withTop = true) {
  // 两张交叉的正视面片 + 一张俯视面片（树冠高度处）；UV 指向图集的左半/右上
  const pos = [], uv = [], nrm = [], idx = [];
  const quad = (pts, uvs, n) => { const b = pos.length / 3; for (const p of pts) pos.push(...p); for (const u of uvs) uv.push(...u); for (let i = 0; i < 4; i++) nrm.push(...n); idx.push(b, b + 1, b + 2, b, b + 2, b + 3); };
  const hw = fw / 2;
  quad([[-hw, 0, 0], [hw, 0, 0], [hw, fh, 0], [-hw, fh, 0]], [[0, 0], [0.5, 0], [0.5, 1], [0, 1]], [0, 0, 1]);
  quad([[0, 0, -hw], [0, 0, hw], [0, fh, hw], [0, fh, -hw]], [[0, 0], [0.5, 0], [0.5, 1], [0, 1]], [1, 0, 0]);
  const ht = top / 2, y = kind === 'bush' ? fh * 0.5 : fh * 0.62;
  if (withTop) quad([[-ht, y, ht], [ht, y, ht], [ht, y, -ht], [-ht, y, -ht]], [[0.5, 0.5], [1, 0.5], [1, 1], [0.5, 1]], [0, 1, 0]);
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
  const srcMap = Object.assign({ peach: 'willow' }, meta.plant_src || {});
  const tintMap = Object.assign({ peach: 'rgba(245,150,175,0.72)' }, meta.plant_tint || {});
  for (const [kind, vi, x, y, z, h, rot] of plants) {
    const src = srcMap[kind] || kind;
    const key = `${src}_${vi}${tintMap[kind] ? '#' + kind : ''}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push([x, y, z, h, rot]);
  }
  // 网址加 ?bb=0 / ?bb=1 可临时切换卡片树和公告牌树，方便对比
  const bbFlag = new URLSearchParams(location.search).get('bb');
  const useBB = bbFlag === null ? !!meta.plant_billboard : bbFlag === '1';
  let done = 0;
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  const imgCache = new Map();
  const img = (name) => { if (!imgCache.has(name)) imgCache.set(name, loadImage(BASE + `dioramas/trees/${name}.webp`)); return imgCache.get(name); };
  await Promise.all([...groups].map(async ([key, list]) => {
    const base = key.split('#')[0]; const tintKind = key.split('#')[1];
    const info = treesMeta[base]; if (!info) return;
    if (useBB && info.bb) {
      // 多角度公告牌树（见 TreeBillboards.js）；scene.json 里 plant_billboard: true 的场景启用
      const tex = tintedAtlas(await img(base + '_bb'), tintKind ? tintMap[tintKind] : null);
      scene.add(makeBillboardTrees(tex, info.bb, list, { sunDirection: sunDirection(meta.sun.euler_deg), sunColor: new THREE.Color(...meta.sun.color), light: meta.plant_light }));
      done += list.length; onProgress && onProgress(done / plants.length);
      return;
    }
    const [front, top] = await Promise.all([img(base + '_front'), img(base + '_top')]);
    const tex = impostorAtlas(front, top, tintKind ? tintMap[tintKind] : null);
    // 建筑尺度的沙盘里大树的俯视面片会像一张悬空的圆盘，scene.json 可用 plant_top: false 关掉（灌木保留）
    const geo = impostorGeometry(info.front_h, info.front_w, info.top, info.kind, meta.plant_top !== false || info.kind === 'bush');
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
  }));
  return plants.length;
}

export async function startDiorama(id, ui) {
  const canvas = document.getElementById('scene');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: 'high-performance' });
  let tier = guessTier(renderer);
  const applyTier = () => { const q = TIERS[tier]; renderer.setPixelRatio(Math.min(devicePixelRatio, q.dpr)); renderer.shadowMap.type = q.soft ? THREE.PCFSoftShadowMap : THREE.PCFShadowMap; };
  applyTier();
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 0.98;
  renderer.setClearColor(0xe8e2d2, 1);

  const meta = await (await fetch(BASE + `dioramas/${id}/scene.json`)).json();
  ui.setTitle(meta.title);
  MAT_OVERRIDE = meta.mat || {};
  const scene = new THREE.Scene();
  const fogC = new THREE.Color(...(meta.fog || [0.9, 0.9, 0.9]));
  scene.fog = new THREE.Fog(fogC, meta.camera.dist * 1.3, meta.camera.dist * 3.2);
  const bd = meta.backdrop || [[0.9, 0.9, 0.9], [0.95, 0.95, 0.95]];
  const cleanBg = gradientTexture(bd[1], bd[0]);
  scene.background = cleanBg;
  let skyTex = null;

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
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = meta.shadow_bias ?? 0.35; sun.shadow.radius = 2;
  scene.add(sun, sun.target);
  scene.add(new THREE.HemisphereLight(0xbfd4ee, 0x6a7a55, 0.55));
  // 天空图、树木贴图与模型同时开始下载（国内访问 GitHub Pages 很慢，串行等待会把延迟叠加起来）
  let modelF = 0, plantF = meta.plants ? 0 : 1;
  const report = () => ui.progress(0.08 + 0.57 * modelF + 0.33 * plantF);
  const hdrP = new RGBELoader().loadAsync(BASE + 'dioramas/env/' + (meta.hdri || 'kloppenheim_06_puresky_1k.hdr').replace('_1k.hdr', '_512.hdr'));
  hdrP.catch(() => {});
  const plantsP = meta.plants ? buildPlants(scene, meta, (f) => { plantF = f; report(); }) : Promise.resolve();
  plantsP.catch(() => {});
  const draco = new DRACOLoader(); draco.setDecoderPath(BASE + 'draco/');
  const loader = new GLTFLoader(); loader.setDRACOLoader(draco);
  const gltfP = loader.loadAsync(BASE + `dioramas/${id}/scene.glb`, (e) => { if (e.total) { modelF = 0.95 * e.loaded / e.total; report(); } });
  gltfP.catch(() => {});
  ui.status('加载模型…');
  try {
    const hdr = await hdrP;
    hdr.mapping = THREE.EquirectangularReflectionMapping;
    const pm = new THREE.PMREMGenerator(renderer); scene.environment = pm.fromEquirectangular(hdr).texture;
    scene.environmentIntensity = 0.45; pm.dispose();
    skyTex = hdr;
  } catch (e) { console.warn('HDRI 加载失败', e); }

  // 模型
  const gltf = await gltfP;
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
  modelF = 1; report();

  // 实例（山石、竹、芭蕉）：glb 里每种模型只有一份（名字以 Lib_ 开头），scene.json 的 instances 记录各处的位置、缩放、旋转
  if (meta.instances) {
    const C = new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1), Ci = C.clone().invert();   // Blender Z-up → three Y-up
    const mb = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), pv = new THREE.Vector3(), sv = new THREE.Vector3();
    const libs = [];
    root.traverse((o) => { if (o.name && o.name.startsWith('Lib_') && meta.instances[o.name]) libs.push(o); });
    for (const lib of libs) {
      const recs = meta.instances[lib.name];
      const parts = []; lib.traverse((o) => { if (o.isMesh) parts.push(o); });
      for (const part of parts) {
        const im = new THREE.InstancedMesh(part.geometry, part.material, recs.length);
        recs.forEach(([x, y, z, sx, sy, sz, rx, ry, rz], i) => {
          e.set(rx, ry, rz, 'XYZ'); q.setFromEuler(e);
          mb.compose(pv.set(x, y, z), q, sv.set(sx, sy, sz));
          im.setMatrixAt(i, new THREE.Matrix4().multiplyMatrices(C, mb).multiply(Ci));
        });
        im.instanceMatrix.needsUpdate = true;
        im.castShadow = true; im.receiveShadow = true; im.frustumCulled = false; im.userData.solid = true;
        scene.add(im);
      }
      lib.removeFromParent();
    }
  }

  // 水面：用 glb 里的水面几何做实时反射
  const waterNormals = makeWaterNormals();
  const waters = [];
  for (const wm of waterMeshes) {
    if (wm.material.name === 'LakeWater' || wm.material.name === 'PondWater') {
      // 西湖湖面：水体色 + 镜面倒影 + 条带风痕（见 LakeSurface.js）；顶点色 R = 近岸程度，G = 水深
      const geo = wm.geometry.clone(); wm.updateWorldMatrix(true, false); geo.applyMatrix4(wm.matrixWorld);
      const pos = geo.attributes.position, colAttr = geo.attributes.color;
      let ys = 0; for (let i = 0; i < pos.count; i++) ys += pos.getY(i); ys /= pos.count;
      const shore = new Float32Array(pos.count * 2);
      for (let i = 0; i < pos.count; i++) { pos.setY(i, ys); shore[i * 2] = colAttr ? colAttr.getX(i) : 0; shore[i * 2 + 1] = colAttr ? colAttr.getY(i) : 1; }
      pos.needsUpdate = true;
      geo.setAttribute('shore', new THREE.BufferAttribute(shore, 2));
      geo.deleteAttribute('color'); geo.deleteAttribute('normal'); geo.computeVertexNormals();
      const lake = new LakeSurface(geo, { level: ys, size: TIERS[tier].water, waterNormals, sunDirection: sunDir, sunColor: new THREE.Color(...meta.sun.color), sky: skyTex, params: meta.lake });
      lake.receiveShadow = true; lake.renderOrder = 2;
      wm.removeFromParent();
      scene.add(lake); waters.push(lake);
      continue;
    }
    const spec = WATER[wm.material.name] || WATER.LakeWater;
    const geo = wm.geometry.clone(); wm.updateWorldMatrix(true, false); geo.applyMatrix4(wm.matrixWorld); geo.rotateX(Math.PI / 2);
    // 水面网格经 Draco 量化后顶点高度有微小抖动，反射会出现棋盘格：把高度拉平、重算法线，去掉顶点色
    { const pos = geo.attributes.position; let zs = 0; for (let i = 0; i < pos.count; i++) zs += pos.getZ(i); zs /= pos.count;
      for (let i = 0; i < pos.count; i++) pos.setZ(i, zs); pos.needsUpdate = true;
      geo.deleteAttribute('color'); geo.deleteAttribute('normal'); geo.computeVertexNormals(); }
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
  if (meta.plants) { ui.status('种树…'); await plantsP; }
  const trees = []; scene.traverse((o) => { if (o.isInstancedMesh && !o.userData.solid) trees.push(o); });
  // 水面反射里按档位决定是否画树（反射要把整个场景再画一遍）
  for (const w of waters) {
    const orig = w.onBeforeRender;
    w.onBeforeRender = function (r, s, c, g, m, gr) {
      const hide = !TIERS[tier].treesInReflection && !w.isLakeSurface;   // 西湖的山林倒影是湖面的主体，各档都画
      if (hide) for (const t of trees) t.visible = false;
      orig.call(this, r, s, c, g, m, gr);
      if (hide) for (const t of trees) t.visible = true;
    };
  }
  // 后处理：环境光遮蔽（GTAO）、移轴景深、柔光、暗角、输出色调映射、SMAA
  let composer = null, bokeh = null, gtao = null, dofK = 1;
  const buildComposer = () => {
    const q = TIERS[tier];
    composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    gtao = null; bokeh = null;
    if (q.gtao) {
      gtao = new GTAOPass(scene, camera, innerWidth, innerHeight);
      gtao.output = GTAOPass.OUTPUT.Default;
      gtao.updateGtaoMaterial({ radius: 2.2, distanceExponent: 1, thickness: 1.2, scale: 1.2, samples: 12, distanceFallOff: 1, screenSpaceRadius: false });
      gtao.blendIntensity = 0.85;
      // 卡片树是 alpha 镂空的面片，GTAO 的法线/深度通道不认 alpha，会把整张卡当实心方块压黑：算遮蔽时把树隐藏
      const origRender = gtao.render.bind(gtao);
      gtao.render = (r, wb, rb, dt, mask) => { for (const tr of trees) tr.visible = false; origRender(r, wb, rb, dt, mask); for (const tr of trees) tr.visible = true; };
      composer.addPass(gtao);
    }
    if (q.dof && dofK > 0) {
      bokeh = new BokehPass(scene, camera, { focus: camera.position.distanceTo(controls.target), aperture: 0.00006 * dofK, maxblur: 0.0075 * Math.min(1.3, dofK) });
      composer.addPass(bokeh);
    }
    if (q.bloom) composer.addPass(new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.14, 0.5, 0.92));
    const vig = new ShaderPass(VignetteShader); vig.uniforms.offset.value = 0.98; vig.uniforms.darkness.value = 0.42;
    composer.addPass(vig);
    composer.addPass(new OutputPass());
    if (q.aa) { try { composer.addPass(new SMAAPass()); } catch (e) { try { composer.addPass(new SMAAPass(innerWidth, innerHeight)); } catch (e2) { /* 无 AA */ } } }
    composer.setPixelRatio(renderer.getPixelRatio());
    composer.setSize(innerWidth, innerHeight);
  };
  buildComposer();
  const setSky = (on) => {
    if (on && skyTex) { scene.background = skyTex; scene.backgroundBlurriness = 0.015; scene.backgroundIntensity = 0.9; scene.fog.color.copy(fogC).lerp(new THREE.Color(0.86, 0.86, 0.9), 0.4); }
    else { scene.background = cleanBg; scene.fog.color.copy(fogC); }
  };
  const setDof = (k) => { dofK = k; buildComposer(); };
  const setTier = (name) => {
    if (!TIERS[name] || name === tier) return;
    tier = name; applyTier(); buildComposer();
    const q = TIERS[tier];
    if (sun.shadow.map) { sun.shadow.map.dispose(); sun.shadow.map = null; }
    sun.shadow.mapSize.set(q.shadow, q.shadow);
    for (const t of trees) t.castShadow = q.treeShadow;
    for (const w of waters) if (w.isLakeSurface) w.setSize(q.water);
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
    if (checks === 1 || checks > 5) return;   // 第一段 3 秒是热身（着色器编译、贴图上传），不作判定
    if (fps < 24 && tier === 'high') setTier('mid');
    else if (fps < 20 && tier === 'mid') setTier('low');
    else if (fps > 56 && tier === 'mid' && checks <= 2) setTier('high');
  };
  const onInteract = () => { controls.autoRotate = false; clearTimeout(autoTimer); autoTimer = setTimeout(() => { if (ui.autoRotateWanted()) controls.autoRotate = true; }, 6000); };
  canvas.addEventListener('pointerdown', onInteract); canvas.addEventListener('wheel', onInteract, { passive: true });
  addEventListener('resize', () => { renderer.setSize(innerWidth, innerHeight); fitFov(); composer.setSize(innerWidth, innerHeight); });
  renderer.setSize(innerWidth, innerHeight);
  renderer.setAnimationLoop(() => {
    const dt = clock.getDelta();
    if (document.visibilityState === 'visible') adapt(Math.min(dt, 0.25));
    for (const w of waters) w.material.uniforms.time.value += dt * 0.6;
    controls.update();
    if (bokeh) bokeh.uniforms.focus.value = camera.position.distanceTo(controls.target);
    composer.render(dt);
  });
  return { scene, camera, controls, renderer, setAutoRotate: (v) => { controls.autoRotate = v; }, setTier, getTier: () => tier, setSky, setDof };
}