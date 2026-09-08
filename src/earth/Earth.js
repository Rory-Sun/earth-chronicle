import * as THREE from 'three';
import { surfaceVertex, surfaceFragment, atmosphereVertex, atmosphereFragment, cloudsVertex, cloudsFragment } from './shaders.js';
import { PLATE_INFO, plateQuaternion } from './Plates.js';

const TEX_BASE = import.meta.env.BASE_URL + 'textures/';
const DATA_BASE = import.meta.env.BASE_URL + 'data/';

function loadTexture(loader, name, { srgb = false, anisotropy = 8 } = {}) {
  return new Promise((resolve, reject) => {
    loader.load(TEX_BASE + name, (tex) => {
      tex.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      tex.wrapS = THREE.RepeatWrapping;
      tex.wrapT = THREE.ClampToEdgeWrapping;
      tex.anisotropy = anisotropy;
      tex.minFilter = THREE.LinearMipmapLinearFilter;
      tex.magFilter = THREE.LinearFilter;
      tex.generateMipmaps = true;
      resolve(tex);
    }, undefined, reject);
  });
}

export class Earth {
  constructor(renderer, onProgress) {
    this.renderer = renderer;
    this.onProgress = onProgress || (() => {});
    this.group = new THREE.Group();
    this.group.name = 'Earth';
    this.plates = {};
    this.sunDir = new THREE.Vector3(1, 0.2, 0.4).normalize();
    this.cloudOffset = 0;
    this.time = 0;
  }

  async load() {
    const loader = new THREE.TextureLoader();
    const maxAniso = this.renderer.capabilities.getMaxAnisotropy();
    const A = Math.min(8, maxAniso);
    const hq = new URLSearchParams(location.search).has('hq') && this.renderer.capabilities.maxTextureSize >= 8192;
    const names = [
      [hq ? 'earth_color_8k.webp' : 'earth_color.webp', { srgb: true, anisotropy: A }],
      [hq ? 'earth_normal_8k.webp' : 'earth_normal.webp', { anisotropy: A }],
      ['earth_height.png', { anisotropy: 2 }],
      ['earth_masks_a.png', { anisotropy: 4 }],
      ['earth_masks_b.png', { anisotropy: 4 }],
      ['earth_lights.webp', { anisotropy: 4 }],
      ['earth_clouds.webp', { anisotropy: 4 }],
    ];
    let done = 0;
    const texes = await Promise.all(names.map(([n, o]) => loadTexture(loader, n, o).then((t) => { done++; this.onProgress(done / (names.length + 1), n); return t; })));
    const [tColor, tNormal, tHeight, tMasksA, tMasksB, tLights, tClouds] = texes;
    tHeight.minFilter = THREE.LinearFilter; tHeight.generateMipmaps = false; // keep height exact for the water line

    const regions = await this.loadRegions();
    this.onProgress(1, 'regions');

    this.uniforms = {
      tColor: { value: tColor }, tNormal: { value: tNormal }, tHeight: { value: tHeight },
      tMasksA: { value: tMasksA }, tMasksB: { value: tMasksB }, tLights: { value: tLights }, tClouds: { value: tClouds },
      uSunDir: { value: this.sunDir },
      uSeaLevel: { value: 0 }, uVeg: { value: 1 }, uIceLat: { value: 90 }, uIceBoost: { value: 0 }, uErosion: { value: 0 },
      uLava: { value: 0 }, uLights: { value: 1 }, uCloudOffset: { value: 0 }, uCloudShadow: { value: 1 }, uTime: { value: 0 },
      uAtmoStrength: { value: 1 }, uSunIntensity: { value: 1 }, uNormalStrength: { value: 1 }, uCloudsOn: { value: 1 }, uSeaIce: { value: 1 },
      uOceanDeep: { value: new THREE.Color(0.010, 0.036, 0.11) }, uOceanShallow: { value: new THREE.Color(0.028, 0.13, 0.22) },
      uAtmoColor: { value: new THREE.Color(0.30, 0.55, 1.0) }, uHazeColor: { value: new THREE.Color(1.0, 0.45, 0.18) },
      uBarrenTint: { value: new THREE.Color(1, 1, 1) },
      uDisplace: { value: 0.0012 }, uIsBase: { value: 0 }, uRadius: { value: 1 },
    };

    const makeMaterial = (isBase, radius) => {
      const u = THREE.UniformsUtils.clone(this.uniforms);
      // share texture & scalar objects so a single update drives all materials
      for (const k of Object.keys(this.uniforms)) u[k] = this.uniforms[k];
      const mat = new THREE.ShaderMaterial({
        glslVersion: THREE.GLSL3,
        vertexShader: surfaceVertex,
        fragmentShader: surfaceFragment,
        uniforms: { ...u, uIsBase: { value: isBase ? 1 : 0 }, uRadius: { value: radius } },
        side: THREE.FrontSide,
      });
      mat.extensions = { derivatives: true };
      return mat;
    };

    // base ocean sphere (fills gaps between drifting plates)
    const baseGeo = new THREE.SphereGeometry(1, 192, 96);
    this.base = new THREE.Mesh(baseGeo, makeMaterial(true, 0.9975));
    this.base.name = 'ocean-base';
    this.group.add(this.base);

    // plate region meshes
    let i = 0;
    for (const r of regions) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(r.pos, 3));
      geo.setAttribute('uv', new THREE.BufferAttribute(r.uv, 2));
      geo.setIndex(new THREE.BufferAttribute(r.idx, 1));
      geo.computeBoundingSphere();
      const mesh = new THREE.Mesh(geo, makeMaterial(false, 1.0 + i * 0.0006));
      mesh.material.polygonOffset = true; mesh.material.polygonOffsetFactor = -1 - i; mesh.material.polygonOffsetUnits = -2 * i;
      mesh.name = 'plate-' + r.plate;
      mesh.frustumCulled = false;
      this.plates[r.plate] = mesh;
      this.group.add(mesh);
      i++;
    }

    // clouds
    this.cloudUniforms = {
      tClouds: { value: tClouds }, uSunDir: { value: this.sunDir }, uOffset: { value: 0 }, uOpacity: { value: 0.95 },
      uSunIntensity: this.uniforms.uSunIntensity, uTint: { value: new THREE.Color(1, 1, 1) }, uTime: this.uniforms.uTime,
    };
    this.clouds = new THREE.Mesh(new THREE.SphereGeometry(1.0085, 160, 80), new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: cloudsVertex, fragmentShader: cloudsFragment, uniforms: this.cloudUniforms,
      transparent: true, depthWrite: false,
    }));
    this.clouds.name = 'clouds';
    this.group.add(this.clouds);

    // atmosphere shell
    const limb = Math.sqrt(1 - 1 / (1.035 * 1.035));
    this.atmoUniforms = {
      uSunDir: { value: this.sunDir }, uAtmoColor: this.uniforms.uAtmoColor, uHazeColor: this.uniforms.uHazeColor,
      uStrength: { value: 1.0 }, uLimb: { value: limb },
    };
    this.atmosphere = new THREE.Mesh(new THREE.SphereGeometry(1.035, 128, 64), new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: atmosphereVertex, fragmentShader: atmosphereFragment, uniforms: this.atmoUniforms,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.FrontSide,
    }));
    this.atmosphere.name = 'atmosphere';
    this.group.add(this.atmosphere);
    return this;
  }

  async loadRegions() {
    const meta = await (await fetch(DATA_BASE + 'regions.json')).json();
    this.regionsMeta = meta;
    const buf = await (await fetch(DATA_BASE + 'regions.bin')).arrayBuffer();
    return meta.plates.map((p) => ({
      plate: p.plate,
      pos: new Float32Array(buf, p.posOffset, p.vertexCount * 3),
      uv: new Float32Array(buf, p.uvOffset, p.vertexCount * 2),
      idx: new Uint32Array(buf, p.idxOffset, p.triangleCount * 3),
    }));
  }

  /** Apply environment parameters (see Environment.js) */
  applyEnv(env) {
    const u = this.uniforms;
    u.uSeaLevel.value = env.seaLevel;
    u.uVeg.value = env.veg;
    u.uIceLat.value = env.iceLat;
    u.uIceBoost.value = env.iceBoost;
    u.uErosion.value = env.erosion;
    u.uLava.value = env.lava;
    u.uLights.value = env.lights;
    u.uAtmoStrength.value = env.atmoStrength;
    u.uSunIntensity.value = env.sun;
    u.uSeaIce.value = env.seaIce;
    u.uOceanDeep.value.setRGB(env.oceanDeep[0], env.oceanDeep[1], env.oceanDeep[2]);
    u.uOceanShallow.value.setRGB(env.oceanShallow[0], env.oceanShallow[1], env.oceanShallow[2]);
    u.uAtmoColor.value.setRGB(env.atmoColor[0], env.atmoColor[1], env.atmoColor[2]);
    u.uHazeColor.value.setRGB(env.hazeColor[0], env.hazeColor[1], env.hazeColor[2]);
    u.uBarrenTint.value.setRGB(env.barrenTint[0], env.barrenTint[1], env.barrenTint[2]);
    this.cloudUniforms.uOpacity.value = env.clouds;
    this.cloudUniforms.uTint.value.setRGB(env.cloudTint[0], env.cloudTint[1], env.cloudTint[2]);
    this.atmoUniforms.uStrength.value = env.atmoStrength;
    // plates
    const tMa = env.yearsBP / 1e6;
    for (const [plate, mesh] of Object.entries(this.plates)) plateQuaternion(plate, tMa, mesh.quaternion);
  }

  update(dt, opts) {
    this.time += dt;
    this.uniforms.uTime.value = this.time;
    this.cloudOffset = (this.cloudOffset + dt * 0.0012) % 1;
    this.uniforms.uCloudOffset.value = this.cloudOffset;
    this.cloudUniforms.uOffset.value = this.cloudOffset;
    this.clouds.visible = !!opts.clouds;
    this.uniforms.uCloudsOn.value = opts.clouds ? 1 : 0;
    this.atmosphere.visible = !!opts.atmosphere;
    this.uniforms.uCloudShadow.value = opts.clouds ? 1 : 0;
  }

  setSunDir(dir) {
    this.sunDir.copy(dir).normalize();
  }
}

export { PLATE_INFO };
