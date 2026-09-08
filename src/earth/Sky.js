import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { Lensflare, LensflareElement } from 'three/addons/objects/Lensflare.js';
import { starsVertex, starsFragment } from './shaders.js';

const BASE = import.meta.env.BASE_URL;

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Star field with a Milky Way band, procedurally generated (no textures). */
export function makeStars() {
  const rnd = mulberry32(1234567);
  const N = 9000, M = 26000;
  const count = N + M;
  const pos = new Float32Array(count * 3), size = new Float32Array(count), tint = new Float32Array(count * 3);
  const R = 900;
  // galactic plane orientation
  const gal = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(1.05, 0.4, 0.6));
  const v = new THREE.Vector3();
  const colorOf = (t) => {
    // t 0..1: blue-white -> yellow -> orange
    if (t < 0.6) return [0.75 + 0.25 * (1 - t), 0.82 + 0.15 * (1 - t), 1.0];
    if (t < 0.85) return [1.0, 0.95, 0.8];
    return [1.0, 0.75, 0.55];
  };
  for (let i = 0; i < count; i++) {
    if (i < N) {
      // uniform stars
      const z = rnd() * 2 - 1, a = rnd() * Math.PI * 2, r = Math.sqrt(1 - z * z);
      v.set(r * Math.cos(a), z, r * Math.sin(a));
      const mag = Math.pow(rnd(), 3.5);
      size[i] = 1.2 + mag * 9.0;
      const c = colorOf(rnd());
      const b = 0.55 + 0.45 * mag;
      tint[i * 3] = c[0] * b; tint[i * 3 + 1] = c[1] * b; tint[i * 3 + 2] = c[2] * b;
    } else {
      // milky way band: gaussian around galactic plane
      const a = rnd() * Math.PI * 2;
      const zg = (rnd() + rnd() + rnd() - 1.5) * 0.22 * (0.6 + 0.8 * Math.pow(Math.abs(Math.sin(a * 0.5 + 1.0)), 2));
      const r = Math.sqrt(Math.max(0, 1 - zg * zg));
      v.set(r * Math.cos(a), zg, r * Math.sin(a)).applyMatrix4(gal);
      size[i] = 0.9 + Math.pow(rnd(), 2) * 2.4;
      const warm = rnd();
      const b = 0.25 + 0.35 * rnd();
      tint[i * 3] = (0.85 + 0.15 * warm) * b; tint[i * 3 + 1] = (0.82 + 0.1 * warm) * b; tint[i * 3 + 2] = (0.95 - 0.2 * warm) * b;
    }
    pos[i * 3] = v.x * R; pos[i * 3 + 1] = v.y * R; pos[i * 3 + 2] = v.z * R;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('size', new THREE.BufferAttribute(size, 1));
  geo.setAttribute('tint', new THREE.BufferAttribute(tint, 3));
  const mat = new THREE.ShaderMaterial({
    glslVersion: THREE.GLSL3, vertexShader: starsVertex, fragmentShader: starsFragment,
    uniforms: { uTime: { value: 0 }, uScale: { value: 1 }, uBrightness: { value: 1 } },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const points = new THREE.Points(geo, mat);
  points.name = 'stars';
  points.frustumCulled = false;
  return points;
}

/** Sun sprite (additive glow) drawn with a generated canvas gradient. */
export function makeSun() {
  const c = document.createElement('canvas');
  c.width = c.height = 512;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(256, 256, 0, 256, 256, 256);
  g.addColorStop(0.0, 'rgba(255,255,250,1)');
  g.addColorStop(0.06, 'rgba(255,250,235,1)');
  g.addColorStop(0.11, 'rgba(255,225,170,0.85)');
  g.addColorStop(0.25, 'rgba(255,190,110,0.28)');
  g.addColorStop(0.5, 'rgba(255,160,90,0.08)');
  g.addColorStop(1.0, 'rgba(255,140,80,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 512);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.SpriteMaterial({ map: tex, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: true, transparent: true });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.setScalar(120);
  sprite.name = 'sun';
  return sprite;
}

/** Load the Blender-modelled Moon (glb) and upgrade its material with the hi-res baked maps. */
export async function loadMoon() {
  const loader = new GLTFLoader();
  const gltf = await loader.loadAsync(BASE + 'models/moon.glb');
  let mesh = null;
  gltf.scene.traverse((o) => { if (o.isMesh && !mesh) mesh = o; });
  const texLoader = new THREE.TextureLoader();
  const [map, normalMap] = await Promise.all([
    texLoader.loadAsync(BASE + 'textures/moon_color.webp'),
    texLoader.loadAsync(BASE + 'textures/moon_normal.webp'),
  ]);
  map.colorSpace = THREE.SRGBColorSpace;
  normalMap.colorSpace = THREE.NoColorSpace;
  map.anisotropy = normalMap.anisotropy = 4;
  const mat = new THREE.MeshStandardMaterial({ map, normalMap, roughness: 0.95, metalness: 0.0, normalScale: new THREE.Vector2(1.2, 1.2) });
  mesh.material = mat;
  mesh.geometry.computeVertexNormals();
  const group = new THREE.Group();
  group.name = 'moon';
  mesh.position.set(0, 0, 0);
  mesh.rotation.set(0, 0, 0);
  mesh.scale.setScalar(1); // glb radius 0.2727 (Moon/Earth ratio)
  group.add(mesh);
  return group;
}


function flareTexture(size, stops, ring = false) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [o, col] of stops) g.addColorStop(o, col);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  if (ring) {
    ctx.globalCompositeOperation = 'lighter';
    ctx.strokeStyle = 'rgba(255,255,255,0.35)';
    ctx.lineWidth = size * 0.04;
    ctx.beginPath(); ctx.arc(size / 2, size / 2, size * 0.36, 0, Math.PI * 2); ctx.stroke();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** Procedural lens flare attached to the sun. */
export function makeLensflare() {
  const core = flareTexture(256, [[0, 'rgba(255,255,255,1)'], [0.12, 'rgba(255,245,225,0.9)'], [0.35, 'rgba(255,205,150,0.18)'], [1, 'rgba(255,180,120,0)']]);
  const ghost = flareTexture(128, [[0, 'rgba(120,180,255,0.0)'], [0.55, 'rgba(120,180,255,0.05)'], [0.75, 'rgba(160,200,255,0.35)'], [0.85, 'rgba(120,180,255,0.05)'], [1, 'rgba(0,0,0,0)']], true);
  const disc = flareTexture(128, [[0, 'rgba(255,220,180,0.35)'], [0.6, 'rgba(255,200,160,0.12)'], [1, 'rgba(255,180,120,0)']]);
  const flare = new Lensflare();
  flare.addElement(new LensflareElement(core, 520, 0, new THREE.Color(1.0, 0.96, 0.88)));
  flare.addElement(new LensflareElement(disc, 70, 0.55, new THREE.Color(0.9, 0.75, 0.6)));
  flare.addElement(new LensflareElement(ghost, 110, 0.72, new THREE.Color(0.6, 0.8, 1.0)));
  flare.addElement(new LensflareElement(disc, 50, 0.86, new THREE.Color(1.0, 0.7, 0.5)));
  flare.addElement(new LensflareElement(ghost, 160, 1.05, new THREE.Color(0.7, 0.85, 1.0)));
  flare.addElement(new LensflareElement(disc, 90, 1.3, new THREE.Color(0.8, 0.9, 1.0)));
  return flare;
}
