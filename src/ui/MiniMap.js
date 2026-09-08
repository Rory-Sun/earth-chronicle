// Paleogeographic mini map: an equirectangular thumbnail showing where the continents are at the current time.
// For each map pixel we inverse-rotate by every plate's quaternion and test the present-day region polygons.
import * as THREE from 'three';
import { plateQuaternion, lonLatToVec3, PLATE_INFO } from '../earth/Plates.js';

const W = 240, H = 120;

function pointInPoly(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export class MiniMap {
  constructor(regions, colorImage, landImage) {
    this.regions = regions; // [{plate, rings}]
    this.canvas = document.createElement('canvas');
    this.canvas.width = W; this.canvas.height = H;
    this.canvas.id = 'minimap';
    this.canvas.title = '当前时代的大陆分布（近似古地理复原）';
    document.body.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this.color = this.sample(colorImage, 1024, 512);
    this.land = this.sample(landImage, 1024, 512);
    this.lastKey = null;
    this.q = {};
    this.qInv = {};
    for (const p of Object.keys(PLATE_INFO)) { this.q[p] = new THREE.Quaternion(); this.qInv[p] = new THREE.Quaternion(); }
    // precompute unit vectors per pixel
    this.dirs = new Float32Array(W * H * 3);
    const v = new THREE.Vector3();
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      lonLatToVec3((x + 0.5) / W * 360 - 180, 90 - (y + 0.5) / H * 180, v);
      const i = (y * W + x) * 3;
      this.dirs[i] = v.x; this.dirs[i + 1] = v.y; this.dirs[i + 2] = v.z;
    }
    // rasterise region ids once (present-day frame) so per-frame updates are a table lookup instead of polygon tests
    this.RW = 720; this.RH = 360;
    this.regionId = new Uint8Array(this.RW * this.RH);
    for (let y = 0; y < this.RH; y++) {
      const lat = 90 - (y + 0.5) / this.RH * 180;
      for (let x = 0; x < this.RW; x++) {
        const lon = (x + 0.5) / this.RW * 360 - 180;
        for (let k = 0; k < this.regions.length; k++) {
          const reg = this.regions[k];
          if (!pointInPoly(lon, lat, reg.rings[0])) continue;
          let inHole = false;
          for (let h = 1; h < reg.rings.length; h++) if (pointInPoly(lon, lat, reg.rings[h])) { inHole = true; break; }
          if (inHole) continue;
          this.regionId[y * this.RW + x] = k + 1;
          break;
        }
      }
    }
  }

  sample(img, w, h) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0, w, h);
    return { data: ctx.getImageData(0, 0, w, h).data, w, h };
  }

  /** env: environment (uses yearsBP, erosion, iceLat, seaLevel) */
  update(env) {
    const tMa = env.yearsBP / 1e6;
    const key = Math.round(tMa * 4) + '|' + Math.round(env.iceLat) + '|' + Math.round(env.erosion * 20);
    if (key === this.lastKey) return;
    this.lastKey = key;
    for (const p of Object.keys(PLATE_INFO)) { plateQuaternion(p, tMa, this.q[p]); this.qInv[p].copy(this.q[p]).invert(); }
    const img = this.ctx.createImageData(W, H);
    const d = img.data;
    const v = new THREE.Vector3();
    const { color, land } = this;
    for (let y = 0; y < H; y++) {
      const lat = 90 - (y + 0.5) / H * 180;
      const polar = Math.abs(lat) > env.iceLat - 3;
      for (let x = 0; x < W; x++) {
        const i = y * W + x;
        let r = 8, g = 24, b = 58; // deep ocean
        let found = false;
        for (let k = 0; k < this.regions.length && !found; k++) {
          const reg = this.regions[k];
          v.set(this.dirs[i * 3], this.dirs[i * 3 + 1], this.dirs[i * 3 + 2]).applyQuaternion(this.qInv[reg.plate]);
          const lon0 = Math.atan2(v.z, -v.x) * 180 / Math.PI - 180;
          const lonN = lon0 < -180 ? lon0 + 360 : lon0;
          const lat0 = Math.asin(Math.max(-1, Math.min(1, v.y))) * 180 / Math.PI;
          const rx = Math.min(this.RW - 1, Math.max(0, Math.floor((lonN + 180) / 360 * this.RW)));
          const ry = Math.min(this.RH - 1, Math.max(0, Math.floor((90 - lat0) / 180 * this.RH)));
          if (this.regionId[ry * this.RW + rx] !== k + 1) continue;
          found = true;
          const sx = Math.min(land.w - 1, Math.max(0, Math.floor((lonN + 180) / 360 * land.w)));
          const sy = Math.min(land.h - 1, Math.max(0, Math.floor((90 - lat0) / 180 * land.h)));
          const li = (sy * land.w + sx) * 4;
          const isLand = land.data[li] > 128;
          if (isLand && env.erosion > 0.3) {
            const cx = Math.floor(sx / 12), cy = Math.floor(sy / 12);
            const n = Math.abs((Math.sin(cx * 12.9898 + cy * 78.233) * 43758.5453) % 1);
            if (n < (env.erosion - 0.3) * 1.3) { continue; }
          }
          if (isLand) {
            const ci = (Math.floor(sy / land.h * color.h) * color.w + Math.floor(sx / land.w * color.w)) * 4;
            r = color.data[ci]; g = color.data[ci + 1]; b = color.data[ci + 2];
            if (env.iceLat > 82 && r > 190 && g > 190 && b > 190) { r = 150; g = 135; b = 110; }
            if (env.veg < 0.5) { const m = (r + g + b) / 3; r = m * 1.15; g = m * 0.95; b = m * 0.7; }
          }
        }
        if (polar) { r = r * 0.3 + 200; g = g * 0.3 + 210; b = b * 0.3 + 225; }
        const o = i * 4;
        d[o] = r; d[o + 1] = g; d[o + 2] = b; d[o + 3] = 255;
      }
    }
    this.ctx.putImageData(img, 0, 0);
    // graticule
    this.ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    this.ctx.lineWidth = 1;
    this.ctx.beginPath();
    for (let lon = -180; lon <= 180; lon += 60) { const x = (lon + 180) / 360 * W + 0.5; this.ctx.moveTo(x, 0); this.ctx.lineTo(x, H); }
    for (let lat = -60; lat <= 60; lat += 30) { const yy = (90 - lat) / 180 * H + 0.5; this.ctx.moveTo(0, yy); this.ctx.lineTo(W, yy); }
    this.ctx.stroke();
    this.ctx.strokeStyle = 'rgba(255,220,150,0.5)';
    this.ctx.beginPath(); this.ctx.moveTo(0, H / 2 + 0.5); this.ctx.lineTo(W, H / 2 + 0.5); this.ctx.stroke();
  }

  setVisible(v) { this.canvas.style.display = v ? '' : 'none'; }
}
