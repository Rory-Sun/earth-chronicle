import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { Earth } from '../earth/Earth.js';
import { makeStars, makeSun, loadMoon, makeLensflare } from '../earth/Sky.js';
import { lonLatToVec3 } from '../earth/Plates.js';
import { Migration } from '../earth/Migration.js';
import { environmentAt } from './Environment.js';
import { Timeline } from '../ui/Timeline.js';
import { InfoPanel } from '../ui/InfoPanel.js';
import { Labels } from '../ui/Labels.js';
import { MiniMap } from '../ui/MiniMap.js';
import { Tour } from './Tour.js';
import { EVENTS, formatYears } from '../data/eras.js';
import { humanEraAt, populationAt, formatPopulation } from '../data/migration.js';

function loadImage(src) {
  return new Promise((resolve, reject) => { const im = new Image(); im.onload = () => resolve(im); im.onerror = reject; im.src = src; });
}

export class App {
  constructor(canvas) {
    this.canvas = canvas;
    this.mode = 'deep';
    this.opts = { clouds: true, atmosphere: true, lights: true, rotate: true, bloom: true, labels: true, realScale: true };
    this.clock = new THREE.Timer();
    this.env = environmentAt(4540e6);
    this.lastEventIdx = -1;
    this.years = 4540e6;
  }

  setLoader(frac, text) {
    const fill = document.getElementById('loader-fill');
    const status = document.getElementById('loader-status');
    if (fill) fill.style.width = Math.round(frac * 100) + '%';
    if (status && text) status.textContent = text;
  }

  async start() {
    const renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer = renderer;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, window.innerWidth / window.innerHeight, 0.01, 5000);
    this.camera.position.set(0, 0.6, 3.4);

    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.minDistance = 1.25;
    this.controls.maxDistance = 12;
    this.controls.rotateSpeed = 0.5;
    this.controls.zoomSpeed = 0.7;
    this.controls.enablePan = false;
    this.controls.addEventListener('start', () => { this.userInteracting = true; this.flyTo = null; });
    this.controls.addEventListener('end', () => { this.userInteracting = false; this.idleTimer = 4; });

    // sky
    this.stars = makeStars();
    this.scene.add(this.stars);
    this.sunDir = new THREE.Vector3(1, 0.25, 0.55).normalize();
    this.defaultSunDir = this.sunDir.clone();
    this.sunTarget = null;
    this.sun = makeSun();
    this.sun.position.copy(this.sunDir).multiplyScalar(700);
    this.scene.add(this.sun);
    this.flareAnchor = new THREE.Object3D();
    this.flareAnchor.position.copy(this.sunDir).multiplyScalar(650);
    this.flareAnchor.add(makeLensflare());
    this.scene.add(this.flareAnchor);
    this.sunLight = new THREE.DirectionalLight(0xfff4e6, 3.2);
    this.sunLight.position.copy(this.sunDir).multiplyScalar(10);
    this.scene.add(this.sunLight);
    this.scene.add(new THREE.AmbientLight(0x223355, 0.15));

    // earth
    this.setLoader(0.02, '加载贴图');
    this.earth = new Earth(renderer, (f, name) => this.setLoader(0.02 + f * 0.8, `加载 ${name}`));
    await this.earth.load();
    this.earth.setSunDir(this.sunDir);
    this.scene.add(this.earth.group);

    // human migration layer (attached to the globe so it rotates with it)
    this.migration = new Migration(new THREE.Vector2(window.innerWidth, window.innerHeight));
    this.earth.group.add(this.migration.group);
    this.labels = new Labels(this.camera);
    for (const s of this.migration.sites) this.labels.add(s.def.name, s.sprite, { cls: 'site' });

    // paleogeographic minimap (uses region polygons + baked colour map)
    try {
      const [colorImg, landImg] = await Promise.all([loadImage(import.meta.env.BASE_URL + 'textures/earth_color.webp'), loadImage(import.meta.env.BASE_URL + 'textures/landmask_2k.png')]);
      this.minimap = new MiniMap(this.earth.regionsMeta.regions, colorImg, landImg);
    } catch (e) { console.warn('minimap failed', e); }

    // Chicxulub impact flash (child of the North American plate so it drifts with it)
    const flashTex = this.migration.glowTex;
    this.impactFlash = new THREE.Sprite(new THREE.SpriteMaterial({ map: flashTex, color: 0xffe8c0, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 }));
    this.impactFlash.position.copy(lonLatToVec3(-89.5, 21.3)).multiplyScalar(1.02);
    this.impactFlash.scale.setScalar(0.001);
    this.earth.plates.NAM.add(this.impactFlash);

    // moon
    this.setLoader(0.85, '加载 Blender 月球模型');
    try {
      this.moon = await loadMoon();
      this.scene.add(this.moon);
    } catch (e) { console.warn('moon failed', e); }

    // post-processing
    this.composer = new EffectComposer(renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(window.innerWidth, window.innerHeight), 0.28, 0.5, 0.92);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    // ui
    this.info = new InfoPanel();
    this.timeline = new Timeline({ onChange: (years, fromUser) => this.onTime(years, fromUser) });
    this.bindUI();
    this.onTime(this.timeline.years, false);
    this.tour = new Tour(this);
    document.getElementById('btn-tour').addEventListener('click', () => { if (this.tour.active) this.tour.stop(); else this.tour.start(0); });
    this.bindWelcome();

    window.addEventListener('resize', () => this.resize());
    this.resize();
    this.setLoader(1, '完成');
    setTimeout(() => document.getElementById('loader').classList.add('done'), 300);
    this.idleTimer = 0;
    this.loop();
  }

  bindUI() {
    document.querySelectorAll('.mode-btn').forEach((b) => b.addEventListener('click', () => this.setMode(b.dataset.mode)));
    const bind = (id, key) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('change', () => { this.opts[key] = el.checked; });
    };
    bind('opt-clouds', 'clouds'); bind('opt-atmo', 'atmosphere'); bind('opt-lights', 'lights');
    bind('opt-rotate', 'rotate'); bind('opt-bloom', 'bloom'); bind('opt-labels', 'labels');
    const rs = document.getElementById('opt-realscale');
    if (rs) rs.addEventListener('change', () => this.setRealScale(rs.checked));
    this.setRealScale(true, false); // real Earth-Moon distance is the default; no camera flight at startup
    const fov = document.getElementById('opt-fov');
    fov.addEventListener('input', () => { this.userFov = parseFloat(fov.value); this.resize(); });
    const toggle = (btnId, popId) => {
      const btn = document.getElementById(btnId), pop = document.getElementById(popId);
      btn.addEventListener('click', () => {
        const show = pop.hidden;
        document.querySelectorAll('.popover').forEach((p) => (p.hidden = true));
        pop.hidden = !show;
      });
    };
    toggle('btn-settings', 'settings');
    toggle('btn-help', 'help');
    this.canvas.addEventListener('dblclick', (e) => this.focusAt(e.clientX, e.clientY));
  }

  bindWelcome() {
    const w = document.getElementById('welcome');
    const params = new URLSearchParams(location.search);
    const dismiss = () => { w.classList.add('fade'); document.body.classList.remove('welcome-open'); setTimeout(() => { w.hidden = true; }, 700); };
    document.getElementById('welcome-tour').addEventListener('click', () => { dismiss(); this.tour.start(0); });
    document.getElementById('welcome-explore').addEventListener('click', dismiss);
    if (params.has('tour')) { w.hidden = true; setTimeout(() => this.tour.start(parseInt(params.get('tour'), 10) || 0), 400); }
    else if (!params.has('notour')) { document.body.classList.add('welcome-open'); setTimeout(() => { w.hidden = false; }, 500); }
  }

  /** Smoothly steer the sun towards `dir` (null = default direction). */
  setSunTarget(dir) { this.sunTarget = dir ? dir.clone().normalize() : this.defaultSunDir.clone(); }

  /** Toggle true Earth-Moon distance (60.3 Earth radii today) vs the compressed cinematic distance. */
  setRealScale(on, fly = true) {
    this.opts.realScale = !!on;
    this.controls.maxDistance = on ? 260 : 12;
    this.onTime(this.years, false);
    const cb0 = document.getElementById('opt-realscale');
    if (cb0) cb0.checked = !!on;
    if (!this.moon || !fly) return;
    if (on) {
      // fly out perpendicular to the Earth-Moon line so both bodies share the frame
      const m = this.moon.position.clone().normalize();
      const dir = new THREE.Vector3().crossVectors(m, new THREE.Vector3(0, 1, 0)).normalize().addScaledVector(new THREE.Vector3(0, 1, 0), 0.25).normalize();
      // distance at which the whole Earth-Moon line fits the horizontal field of view (Earth stays centred)
      const halfH = Math.atan(Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * this.camera.aspect);
      const D = Math.min(250, Math.max(12, this.moon.position.length() / Math.tan(halfH) * 1.15));
      this.flyToDir(dir, D, 3.2);
      this.info.showToast(`真实尺度：月球距离 ${(this.moon.position.length()).toFixed(1)} 个地球半径（今天约 38.4 万公里）`);
    } else {
      this.flyToDir(this.camera.position.clone().normalize(), 3.4, 2.4);
      this.info.showToast('已恢复压缩的地月距离（便于同框观看）');
    }
    const cb = document.getElementById('opt-realscale');
    if (cb) cb.checked = !!on;
  }

  setSun(x, y, z) {
    this.sunDir.set(x, y, z).normalize();
    this.earth.setSunDir(this.sunDir);
    this.sun.position.copy(this.sunDir).multiplyScalar(700);
    this.flareAnchor.position.copy(this.sunDir).multiplyScalar(650);
    this.sunLight.position.copy(this.sunDir).multiplyScalar(10);
  }

  focusAt(x, y) {
    const ndc = new THREE.Vector2((x / window.innerWidth) * 2 - 1, -(y / window.innerHeight) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const hit = ray.intersectObject(this.earth.base, false)[0];
    if (!hit) return;
    const dist = Math.max(1.6, this.camera.position.length() * 0.7);
    this.flyToDir(hit.point.clone().normalize(), dist, 1.4);
  }

  /** Fly the camera along the sphere to look at world direction `dir` from distance `dist` (seconds). */
  flyToDir(dir, dist, seconds = 2.4) {
    const fromDir = this.camera.position.clone().normalize();
    const toDir = dir.clone().normalize();
    if (fromDir.dot(toDir) < -0.995) toDir.add(new THREE.Vector3(0, 0.15, 0)).normalize(); // avoid the antipodal degenerate case
    this.flyTo = { fromDir, toDir, fromDist: this.camera.position.length(), toDist: dist, t: 0, dur: seconds };
  }

  setMode(mode) {
    if (!this.info || !this.timeline) return;
    this.mode = mode;
    this.info.currentId = null;
    document.querySelectorAll('.mode-btn').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
    this.migration.group.visible = mode === 'human';
    const legend = document.getElementById('legend');
    if (legend) legend.hidden = mode !== 'human';
    if (mode === 'human') {
      this.earth.group.rotation.y = 0;
      if (!(this.tour && this.tour.active)) this.flyToDir(new THREE.Vector3(0.92, 0.42, -0.25), 3.0, 2.0);
    }
    this.timeline.setMode(mode);
    if (mode === 'now') {
      this.info.setCustom('now', {
        eon: '现在 · 2026', title: '今日地球', time: '公元 2026 年',
        desc: '拖动旋转、滚轮缩放，双击聚焦，自由探索这颗蓝色星球。地表与云层来自 NASA Blue Marble 卫星影像，夜灯来自 Black Marble 2016；地形起伏与远古时代的地表由 Blender 程序化生成。转到背光面可以看到夜间的城市灯光。',
        facts: ['赤道半径 6378 km，表面 71% 被海洋覆盖', '最高点珠穆朗玛峰 8849 m，最深点马里亚纳海沟 -10935 m', '大气中氧气 21%，二氧化碳约 420 ppm', '人口约 82 亿，夜间灯光勾勒出人类聚居的轮廓'],
        stats: { 年龄: '45.4 亿年', 均温: '15°C', 海洋: '71%', 卫星: '1（月球）' },
      });
    }
  }

  onTime(years, fromUser) {
    this.years = years;
    this.env = environmentAt(years);
    this.earth.applyEnv(this.env);
    if (this.minimap) {
      this.minimap.setVisible(this.mode === 'deep');
      const now = performance.now();
      const playing = this.timeline && this.timeline.playing;
      // the paleomap is CPU-rendered: throttle it while the timeline is animating
      if (this.mode === 'deep' && (!playing || now - (this.lastMiniAt || 0) > 400)) { this.minimap.update(this.env); this.lastMiniAt = now; }
    }
    const playing = this.timeline ? this.timeline.playing : false;
    if (this.mode === 'deep') {
      this.info.showEra(years);
      let passed = -1;
      for (let i = 0; i < EVENTS.length; i++) if (years <= EVENTS[i].t) passed = i;
      if (playing && passed !== this.lastEventIdx && passed >= 0) this.info.showToast(`◆ ${EVENTS[passed].name} · ${formatYears(EVENTS[passed].t)}`);
      this.lastEventIdx = passed;
    } else if (this.mode === 'human') {
      const ka = years / 1000;
      this.migration.update(ka);
      const era = humanEraAt(years);
      const pop = populationAt(ka);
      const timeLabel = formatYears(years);
      const stats = { 全球人口: formatPopulation(pop), 海平面: `${Math.round(this.env.seaLevel)} m`, 冰盖边缘: this.env.iceLat >= 89 ? '无' : `${Math.round(this.env.iceLat)}°`, 时间: timeLabel };
      this.info.setCustom(era.id, { eon: era.eon, title: era.name, desc: era.desc, facts: era.facts, time: timeLabel, stats });
      this.info.updateStats(stats);
    }
    if (this.moon) {
      const md = this.env.moonDist; // 0.06 at formation -> 1 today
      const real = this.opts.realScale;
      // real: 60.3 Earth radii today (384 400 km), ~3.6 at formation. Compressed: 9 radii today so both fit one frame.
      const d = real ? 60.3 * md : 2.4 + 6.6 * md;
      const ang = -0.9 - (1 - md) * 0.55;
      this.moon.position.set(Math.cos(ang) * d, real ? 0.09 * d : 1.4 + 0.5 * (1 - md), Math.sin(ang) * d);
      // the Moon never changed size; the early-Moon enlargement is a visual cue used only in compressed mode
      this.moon.scale.setScalar(real ? 1 : 1 + 1.3 * (1 - md));
      this.moon.lookAt(0, 0, 0);
    }
    if (this.impactFlash) {
      const k = this.env.impact || 0;
      this.impactFlash.material.opacity = Math.min(1, k * 1.5);
      this.impactFlash.scale.setScalar(0.04 + 0.32 * k);
    }
    this.sun.material.opacity = 0.75 + 0.25 * this.env.sun;
    this.sun.scale.setScalar(90 + 40 * this.env.sun);
    this.sunLight.intensity = 3.2 * this.env.sun;
  }

  /** Move the timeline + info panel into the bottom sheet on narrow screens, back to free panels on wide ones. */
  layout(w) {
    const sheet = document.getElementById('sheet');
    const body = document.getElementById('sheet-body');
    const info = document.getElementById('info');
    const tl = document.getElementById('timeline');
    const mobile = w <= 900 && !document.body.classList.contains('embed');
    if (mobile && !this.isMobileLayout) {
      body.appendChild(info); body.appendChild(tl);
      sheet.hidden = false;
      if (!this.sheetBound) {
        this.sheetBound = true;
        const toggle = () => sheet.classList.toggle('open');
        document.getElementById('sheet-handle').addEventListener('click', toggle);
        info.querySelector('.info-era').addEventListener('click', toggle);
        let y0 = null;
        sheet.addEventListener('touchstart', (e) => { y0 = e.touches[0].clientY; }, { passive: true });
        sheet.addEventListener('touchend', (e) => {
          if (y0 === null) return;
          const dy = e.changedTouches[0].clientY - y0; y0 = null;
          if (dy < -40) sheet.classList.add('open'); else if (dy > 40) sheet.classList.remove('open');
        });
      }
      this.isMobileLayout = true;
    } else if (!mobile && this.isMobileLayout) {
      const labels = document.getElementById('labels');
      document.body.insertBefore(info, labels); document.body.insertBefore(tl, labels);
      sheet.hidden = true; sheet.classList.remove('open');
      this.isMobileLayout = false;
    }
    return mobile;
  }

  resize() {
    const w = window.innerWidth, h = window.innerHeight;
    this.camera.aspect = w / h;
    const mobile = this.layout(w);
    // portrait screens: keep the horizontal field of view constant so the globe still fits the width
    const baseFov = this.userFov || 38;
    const aspect = w / h;
    this.camera.fov = aspect < 1 ? Math.min(95, THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(baseFov / 2)) / aspect))) : baseFov;
    // wide: the info panel sits on the left, nudge the globe right. narrow: the sheet covers the bottom, lift the globe.
    if (mobile) this.camera.setViewOffset(w, h, 0, h * 0.16, w, h);
    else if (w > 900 && !document.body.classList.contains('embed')) this.camera.setViewOffset(w, h, -w * 0.11, -h * 0.03, w, h);
    else this.camera.clearViewOffset();
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.composer.setSize(w, h);
    this.migration.setResolution(w, h);
  }

  loop() {
    requestAnimationFrame(() => this.loop());
    this.clock.update();
    const dt = Math.min(this.clock.getDelta(), 0.1);
    this.timeline.tick(dt);
    if (this.tour) this.tour.tick(dt);
    if (this.sunTarget && this.sunDir.distanceToSquared(this.sunTarget) > 1e-6) {
      const k = Math.min(1, dt * 1.6);
      const d = this.sunDir.clone().lerp(this.sunTarget, k).normalize();
      this.setSun(d.x, d.y, d.z);
    }
    if (this.opts.rotate && !this.userInteracting && this.mode !== 'human' && !(this.tour && this.tour.active)) {
      this.idleTimer = Math.max(0, this.idleTimer - dt);
      if (this.idleTimer <= 0) this.earth.group.rotation.y += dt * 0.035;
    }
    if (this.flyTo) {
      const f = this.flyTo;
      f.t = Math.min(1, f.t + dt / f.dur);
      const s = f.t * f.t * (3 - 2 * f.t);
      const dir = f.fromDir.clone().lerp(f.toDir, s).normalize();
      this.camera.position.copy(dir.multiplyScalar(f.fromDist + (f.toDist - f.fromDist) * s));
      if (f.t >= 1) this.flyTo = null;
    }
    this.earth.update(dt, { clouds: this.opts.clouds, atmosphere: this.opts.atmosphere });
    this.earth.uniforms.uLights.value = this.opts.lights ? this.env.lights : 0;
    this.stars.material.uniforms.uTime.value += dt;
    this.stars.rotation.y += dt * 0.002;
    if (this.moon) this.moon.rotation.y += dt * 0.01;
    this.migration.tick();
    this.controls.update();
    this.bloom.enabled = this.opts.bloom;
    this.composer.render();
    this.labels.update(window.innerWidth, window.innerHeight, this.opts.labels && this.mode === 'human');
    this.updateScaleLabels();
  }

  /** In real-scale mode both bodies are tiny: mark them with rings + labels so the distance reads. */
  updateScaleLabels() {
    const root = document.getElementById('scale-labels');
    if (!root) return;
    const show = this.opts.realScale && this.moon && !document.body.classList.contains('clear');
    root.hidden = !show;
    if (!show) return;
    const w = window.innerWidth, h = window.innerHeight;
    const place = (el, pos, text) => {
      const p = pos.clone().project(this.camera);
      const visible = p.z < 1 && Math.abs(p.x) < 1.05 && Math.abs(p.y) < 1.05;
      el.style.display = visible ? 'block' : 'none';
      if (!visible) return;
      el.classList.toggle('left', p.x > 0.55);
      el.style.left = ((p.x + 1) / 2 * w) + 'px';
      el.style.top = ((1 - p.y) / 2 * h) + 'px';
      if (text) el.lastChild.textContent = text;
    };
    const earthEl = document.getElementById('slabel-earth');
    if (this.camera.position.length() > 20) place(earthEl, new THREE.Vector3(0, 0, 0)); else earthEl.style.display = 'none';
    const km = Math.round(6371 * this.moon.position.length() / 1000) * 1000;
    const moonEl = document.getElementById('slabel-moon');
    // only label the Moon while it is too small to recognise (apparent radius under ~22 px)
    const moonPx = 0.2727 / this.camera.position.distanceTo(this.moon.position) / Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * h / 2;
    if (moonPx < 22) place(moonEl, this.moon.position, `月球 · ${(km / 10000).toFixed(1)} 万 km`); else moonEl.style.display = 'none';
  }
}
