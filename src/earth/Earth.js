import * as THREE from 'three';
import { surfaceVertex, surfaceFragment, atmosphereVertex, atmosphereFragment, cloudsVertex, cloudsFragment } from './shaders.js';
import { PLATE_INFO, plateQuaternion } from './Plates.js';
import { buildRegionMeshes } from './regionMesh.js';
import { placeholderTexture, streamFlags, PRIORITY } from './textures.js';
import REGIONS from '../data/regions.json';

export class Earth {
  /**
   * Builds the whole planet synchronously with 1x1 stand-in textures, so the shaders can compile while the
   * real textures download; `stream` (TextureStream) then fills the texture slots level by level.
   */
  constructor(renderer, stream) {
    this.renderer = renderer;
    this.stream = stream;
    this.group = new THREE.Group();
    this.group.name = 'Earth';
    this.plates = {};
    this.regions = REGIONS.regions; // [{ plate, rings }] present-day outlines, also used by the mini map
    this.sunDir = new THREE.Vector3(1, 0.2, 0.4).normalize();
    this.cloudOffset = 0;
    this.time = 0;
    // satellite imagery: shown once all three NASA maps are in, faded in if that happens mid-session
    this.realTarget = 0;
    this.realFade = 0;
    this.realHave = { colorReal: false, lightsReal: false, cloudsReal: false };
    this.build();
    this.registerTextures();
  }

  get realReady() { return this.realHave.colorReal && this.realHave.lightsReal && this.realHave.cloudsReal; }

  build() {
    const black = placeholderTexture(0, 0, 0, { repeatX: true });
    this.uniforms = {
      tColor: { value: black }, tNormal: { value: placeholderTexture(128, 128, 255, { repeatX: true }) }, tHeight: { value: placeholderTexture(128, 128, 128, { repeatX: true }) },
      tMasksA: { value: black }, tMasksB: { value: black }, tLights: { value: black }, tClouds: { value: black },
      tColorReal: { value: black }, tLightsReal: { value: black }, tCloudsReal: { value: black }, uReal: { value: 0 },
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
    // The surface shader derives its normal from the position. Leaving the unused `normal` attribute on this
    // one mesh made three.js build a second, otherwise identical program for it (the plates have no normals),
    // and this shader takes ~17 s to compile on a first visit (Chrome/D3D on an integrated GPU).
    baseGeo.deleteAttribute('normal');
    this.base = new THREE.Mesh(baseGeo, makeMaterial(true, 0.9975));
    this.base.name = 'ocean-base';
    this.group.add(this.base);

    // plate region meshes (generated from the region polygons, see regionMesh.js)
    let i = 0;
    for (const r of buildRegionMeshes(REGIONS.regions, REGIONS.cell)) {
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

    // clouds (the two cloud maps are shared with the surface shader, which uses them for cloud shadows)
    this.cloudUniforms = {
      tClouds: this.uniforms.tClouds, tCloudsReal: this.uniforms.tCloudsReal, uReal: this.uniforms.uReal, uSunDir: { value: this.sunDir }, uOffset: { value: 0 }, uOpacity: { value: 0.95 },
      uSunIntensity: this.uniforms.uSunIntensity, uTint: { value: new THREE.Color(1, 1, 1) }, uTime: this.uniforms.uTime,
    };
    this.clouds = new THREE.Mesh(new THREE.SphereGeometry(1.0085, 160, 80), new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: cloudsVertex, fragmentShader: cloudsFragment, uniforms: this.cloudUniforms,
      transparent: true, depthWrite: false,
    }));
    this.clouds.name = 'clouds';
    // The plates are stacked with growing polygon offsets (above). On a surface seen at a slant the
    // slope term of those offsets exceeds the 0.0085 gap to the cloud shell, so a late plate such as
    // Africa ended up in front of its own clouds in the depth buffer and cut them off along the plate
    // grid. Offset the clouds further than any plate; the Moon is far enough away to be unaffected.
    this.clouds.material.polygonOffset = true;
    this.clouds.material.polygonOffsetFactor = -(i + 2);
    this.clouds.material.polygonOffsetUnits = -2 * (i + 1);
    this.group.add(this.clouds);

    // atmosphere shell
    this.atmoUniforms = {
      uSunDir: { value: this.sunDir }, uAtmoColor: this.uniforms.uAtmoColor, uHazeColor: this.uniforms.uHazeColor,
      uStrength: { value: 1.0 }, uSunIntensity: this.uniforms.uSunIntensity, uMie: { value: 1.0 },
    };
    // ray-marched single-scattering shell; drawn additively over the planet and the clouds (also gives aerial perspective)
    this.atmosphere = new THREE.Mesh(new THREE.SphereGeometry(1.06, 96, 48), new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: atmosphereVertex, fragmentShader: atmosphereFragment, uniforms: this.atmoUniforms,
      transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending, side: THREE.FrontSide,
    }));
    this.atmosphere.renderOrder = 20;
    this.clouds.renderOrder = 3; // under the migration routes (4-6): those are a diagram and must read through the weather
    this.atmosphere.name = 'atmosphere';
    this.group.add(this.atmosphere);
  }

  /**
   * Texture slots and their levels. Level 0 is the first-paint size made by tools/optimize_earth_textures.py;
   * the later levels are the full-size maps (and the optional 8K ones; ?hq adds the 8K procedural colour and
   * normal maps). See streamFlags() for ?lq and ?embed.
   */
  registerTextures() {
    const caps = this.renderer.capabilities;
    const A = Math.min(8, caps.getMaxAnisotropy());
    const { lq, embed, eager, hq: wantHq } = streamFlags();
    const hq = wantHq && caps.maxTextureSize >= 8192;
    // the 8K satellite colour map is the biggest realism win on desktop-class GPUs, but at 3 MB it only
    // downloads once satellite imagery is actually on screen (and in a small embed only on a close-up)
    const real8k = !lq && (hq || (caps.maxTextureSize >= 16384 && window.innerWidth > 900 && !embed));
    this.eager = eager;
    const hold = !eager;
    const u = this.uniforms;
    const lite = (file, priority) => ({ file, priority, tag: 'lite' });
    const full = (file, priority) => (lq ? null : { file, priority, hold, tag: 'full' });
    const extra = (file) => ({ file, priority: PRIORITY.extra, hold, tag: 'full' });
    const slot = (key, uniform, group, opts, levels) => this.stream.add(key, {
      group, opts: { repeatX: true, ...opts }, levels,
      apply: (tex) => { u[uniform].value = tex; if (key in this.realHave) this.realHave[key] = true; },
    });
    const E = PRIORITY.earthFull, R = PRIORITY.realFull, RL = PRIORITY.realLite;
    slot('color', 'tColor', 'earth', { srgb: true, anisotropy: A }, [lite('earth_color_2k.webp', 0), full('earth_color.webp', E), hq && extra('earth_color_8k.webp')]);
    slot('normal', 'tNormal', 'earth', { anisotropy: A }, [lite('earth_normal_2k.webp', 0), full('earth_normal.webp', E + 3), hq && extra('earth_normal_8k.webp')]);
    // height: no mipmaps, so the water line stays exact
    slot('height', 'tHeight', 'earth', { anisotropy: 2, mipmaps: false }, [lite('earth_height_2k.webp', 0), full('earth_height.webp', E + 1)]);
    slot('masksA', 'tMasksA', 'earth', { anisotropy: 4 }, [lite('earth_masks_a_1k.webp', 0), full('earth_masks_a.webp', E + 2)]);
    slot('masksB', 'tMasksB', 'earth', { anisotropy: 4 }, [lite('earth_masks_b_1k.webp', 0), full('earth_masks_b.webp', E + 4)]);
    slot('lights', 'tLights', 'earth', { anisotropy: 4 }, [lite('earth_lights.webp', 0)]);
    slot('clouds', 'tClouds', 'earth', { anisotropy: 4 }, [lite('earth_clouds_2k.webp', 0), full('earth_clouds.webp', E + 5)]);
    // NASA Visible Earth (public domain): Blue Marble NG colour, Black Marble 2016 lights, Blue Marble clouds
    slot('colorReal', 'tColorReal', 'real', { srgb: true, anisotropy: A }, [lite('nasa_color_2k.webp', RL), full('nasa_color_4k.webp', R),
      real8k && { file: 'nasa_color_8k.webp', priority: PRIORITY.extra, hold: true, tag: '8k' }]);
    slot('cloudsReal', 'tCloudsReal', 'real', { anisotropy: 4 }, [lite('nasa_clouds_2k.webp', RL + 1), full('nasa_clouds_4k.webp', R + 1)]);
    slot('lightsReal', 'tLightsReal', 'real', { srgb: true, anisotropy: 4 }, [lite('nasa_lights_2k.webp', RL + 2), full('nasa_lights_4k.webp', R + 2)]);
  }

  /** Slots whose first level must be in before the first frame; `real` adds the satellite maps (present-day deep links). */
  criticalSlots(real = false) {
    const keys = ['color', 'normal', 'height', 'masksA', 'masksB', 'lights', 'clouds'];
    return real ? keys.concat(['colorReal', 'cloudsReal', 'lightsReal']) : keys;
  }

  /** Call once the critical textures are in: satellite imagery that is already complete shows without a fade. */
  settle() {
    this.realFade = this.realReady ? 1 : 0;
    this.uniforms.uReal.value = this.realTarget * this.realFade;
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
    // real satellite imagery for the recent past; procedural palaeo-surface further back (continents drift, biomes differ)
    const tMaReal = env.yearsBP / 1e6;
    this.realTarget = tMaReal <= 8 ? 1 : tMaReal >= 30 ? 0 : 1 - (tMaReal - 8) / 22;
    u.uReal.value = this.realTarget * this.realFade; // until the NASA maps are in, the procedural surface stands in
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
    // satellite imagery that finishes downloading mid-session fades in over the procedural surface
    if (this.realReady && this.realFade < 1) this.realFade = Math.min(1, this.realFade + dt / 1.5);
    this.uniforms.uReal.value = this.realTarget * this.realFade;
    this.hint(opts.globePx);
  }

  /**
   * Tell the texture stream what is on screen, so that is what downloads next.
   * @param globePx radius of the globe on screen in device pixels (undefined while the camera orbits the Moon)
   */
  hint(globePx) {
    const real = this.realTarget > 0 && globePx !== undefined; // around the Moon the Earth is a small disc: no rush
    if (real && !this.hintedReal) {
      this.hintedReal = true;
      this.stream.prioritize('real', 'lite');
      if (this.eager) this.stream.prioritize('real', 'full');
    }
    // The first-paint maps are 2048 texels around the globe: one texel per pixel at the centre of the disc when
    // its radius is 326 px. Well beyond that they start to look soft: fetch the full-size set of what is showing.
    const close = globePx !== undefined && globePx > 430;
    if (close) {
      const group = this.realTarget > 0.5 ? 'real' : 'earth';
      if (this.hintedClose !== group) { this.hintedClose = group; this.stream.prioritize(group, 'full'); }
    }
    // the 8K satellite map follows once satellite imagery is what the user is looking at
    if (real && this.realFade >= 1 && (this.eager || close) && !this.hinted8k) { this.hinted8k = true; this.stream.prioritize('real', '8k'); }
  }

  setSunDir(dir) {
    this.sunDir.copy(dir).normalize();
  }
}

export { PLATE_INFO };
