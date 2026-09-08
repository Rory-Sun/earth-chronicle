import * as THREE from 'three';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { ROUTES, SITES } from '../data/migration.js';
import { lonLatToVec3 } from './Plates.js';

const R = 1.006;
const SEG_PER_DEG = 0.35;

/** Great-circle interpolation between waypoints, returns array of Vector3 (radius R) */
function buildPath(pts) {
  const out = [];
  for (let i = 0; i + 1 < pts.length; i++) {
    const a = lonLatToVec3(pts[i][0], pts[i][1]);
    const b = lonLatToVec3(pts[i + 1][0], pts[i + 1][1]);
    const ang = a.angleTo(b);
    const n = Math.max(2, Math.ceil(ang * 180 / Math.PI * SEG_PER_DEG));
    for (let k = (i === 0 ? 0 : 1); k <= n; k++) {
      const t = k / n;
      const v = new THREE.Vector3().copy(a).multiplyScalar(Math.sin((1 - t) * ang)).addScaledVector(b, Math.sin(t * ang)).divideScalar(Math.sin(ang) || 1).normalize();
      // slight arc lift for sea crossings looks nice; keep near surface
      out.push(v.multiplyScalar(R));
    }
  }
  return out;
}

function makeGlowTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.25, 'rgba(255,235,200,0.85)');
  g.addColorStop(0.6, 'rgba(255,200,120,0.25)');
  g.addColorStop(1, 'rgba(255,180,100,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export class Migration {
  constructor(resolution) {
    this.group = new THREE.Group();
    this.group.name = 'migration';
    this.group.visible = false;
    this.resolution = resolution;
    this.routes = [];
    this.glowTex = makeGlowTexture();
    this.currentKa = 300;

    for (const r of ROUTES) {
      const path = buildPath(r.pts);
      const flat = new Float32Array(path.length * 3);
      path.forEach((v, i) => { flat[i * 3] = v.x; flat[i * 3 + 1] = v.y; flat[i * 3 + 2] = v.z; });
      const geo = new LineGeometry();
      geo.setPositions(flat);
      const faint = r.style === 'faint';
      const mat = new LineMaterial({
        color: new THREE.Color(r.color || '#ffcc88'), linewidth: faint ? 2.0 : 3.4, transparent: true, opacity: faint ? 0.6 : 1.0,
        dashed: !!r.sea, dashSize: 0.02, gapSize: 0.012, depthTest: true, depthWrite: false, alphaToCoverage: false,
      });
      mat.resolution.copy(resolution);
      const line = new Line2(geo, mat);
      line.computeLineDistances();
      line.renderOrder = 5;
      line.frustumCulled = false;
      line.visible = false;
      this.group.add(line);
      // soft glow halo underneath
      const glowMat = new LineMaterial({ color: new THREE.Color(r.color || '#ffcc88'), linewidth: faint ? 6 : 10, transparent: true, opacity: faint ? 0.12 : 0.22, depthTest: true, depthWrite: false, blending: THREE.AdditiveBlending });
      glowMat.resolution.copy(resolution);
      const glow = new Line2(geo, glowMat);
      glow.renderOrder = 4;
      glow.frustumCulled = false;
      glow.visible = false;
      line.userData.glow = glow;
      this.group.add(glow);
      // head marker
      const head = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glowTex, color: r.color || '#ffcc88', transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
      head.scale.setScalar(faint ? 0.035 : 0.06);
      head.visible = false;
      head.renderOrder = 6;
      this.group.add(head);
      this.routes.push({ def: r, path, flat, geo, line, head, drawn: -1 });
    }

    // sites
    this.sites = SITES.map((s) => {
      const pos = lonLatToVec3(s.lon, s.lat).multiplyScalar(1.004);
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glowTex, color: '#ffe0a8', transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0.9 }));
      sprite.position.copy(pos);
      sprite.scale.setScalar(0.028);
      sprite.visible = false;
      sprite.renderOrder = 6;
      this.group.add(sprite);
      return { def: s, pos, sprite, age: 0 };
    });
  }

  setResolution(w, h) {
    this.resolution.set(w, h);
    for (const r of this.routes) { r.line.material.resolution.set(w, h); r.line.userData.glow.material.resolution.set(w, h); }
  }

  /** ka: thousand years before present */
  update(ka, dt = 0) {
    this.currentKa = ka;
    for (const r of this.routes) {
      const { t0, t1 } = r.def;
      let p = (t0 - ka) / (t0 - t1);
      p = Math.min(1, Math.max(0, p));
      const n = r.path.length;
      const count = p <= 0 ? 0 : Math.max(2, Math.round(2 + p * (n - 2)));
      if (count !== r.drawn) {
        r.drawn = count;
        if (count < 2) { r.line.visible = false; r.line.userData.glow.visible = false; r.head.visible = false; }
        else {
          r.line.visible = true;
          r.line.userData.glow.visible = true;
          const sub = r.flat.subarray(0, count * 3);
          r.geo.setPositions(sub);
          r.line.computeLineDistances();
          const hx = sub[(count - 1) * 3], hy = sub[(count - 1) * 3 + 1], hz = sub[(count - 1) * 3 + 2];
          r.head.position.set(hx, hy, hz).multiplyScalar(1.003);
          r.head.visible = p < 1;
        }
      }
      // fade completed routes a bit over time (older -> dimmer)
      if (r.line.visible) {
        const age = Math.max(0, t1 - ka) / Math.max(t0, 1);
        const base = r.def.style === 'faint' ? 0.5 : 0.95;
        r.line.material.opacity = base * (1 - Math.min(0.55, age * 0.4));
      }
    }
    for (const s of this.sites) {
      const show = ka <= s.def.t;
      s.sprite.visible = show;
      if (show) {
        const since = s.def.t - ka; // ka since appearance
        const pulse = since < 3 ? 1 + 0.6 * Math.sin(performance.now() * 0.006) : 1;
        s.sprite.scale.setScalar(0.024 * pulse);
        s.sprite.material.opacity = since < 20 ? 0.95 : 0.55;
      }
    }
  }

  tick() {
    // pulse heads
    const k = 1 + 0.35 * Math.sin(performance.now() * 0.005);
    for (const r of this.routes) if (r.head.visible) r.head.scale.setScalar((r.def.style === 'faint' ? 0.035 : 0.06) * k);
  }
}
