// Raster utilities for equirectangular maps. x = (lon+180)/360*W, y = (90-lat)/180*H

export class Field {
  constructor(width, height, fill = 0) {
    this.width = width; this.height = height;
    this.data = new Float32Array(width * height);
    if (fill) this.data.fill(fill);
  }
  lonToX(lon) { return (lon + 180) / 360 * this.width; }
  latToY(lat) { return (90 - lat) / 180 * this.height; }
  pxToLon(x) { return x / this.width * 360 - 180; }
  pxToLat(y) { return 90 - y / this.height * 180; }
  get(x, y) {
    x = ((x % this.width) + this.width) % this.width;
    y = Math.max(0, Math.min(this.height - 1, y));
    return this.data[y * this.width + x];
  }
  /** bilinear sample at fractional pixel coords */
  sample(fx, fy) {
    const x0 = Math.floor(fx), y0 = Math.floor(fy);
    const tx = fx - x0, ty = fy - y0;
    const a = this.get(x0, y0), b = this.get(x0 + 1, y0), c = this.get(x0, y0 + 1), d = this.get(x0 + 1, y0 + 1);
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
  }
  /** sample by lon/lat */
  sampleGeo(lon, lat) { return this.sample(this.lonToX(lon) - 0.5, this.latToY(lat) - 0.5); }
  clamp01() { const d = this.data; for (let i = 0; i < d.length; i++) d[i] = d[i] < 0 ? 0 : d[i] > 1 ? 1 : d[i]; return this; }
  multiply(other) { // other must have same size
    const d = this.data, o = other.data; for (let i = 0; i < d.length; i++) d[i] *= o[i]; return this;
  }
  maxWith(other) { const d = this.data, o = other.data; for (let i = 0; i < d.length; i++) if (o[i] > d[i]) d[i] = o[i]; return this; }
  scale(k) { const d = this.data; for (let i = 0; i < d.length; i++) d[i] *= k; return this; }
  map(fn) { const d = this.data; for (let i = 0; i < d.length; i++) d[i] = fn(d[i]); return this; }
}

/**
 * Anti-aliased scanline fill of a polygon (rings in lon/lat degrees). Even-odd rule (holes supported).
 * mode: 'add' | 'max' | 'sub'
 */
/** Unwrap a ring that jumps across the antimeridian into a continuous lon sequence; close rings that wind around a pole. */
function unwrapRing(ring) {
  const out = [[ring[0][0], ring[0][1]]];
  let offset = 0;
  for (let i = 1; i < ring.length; i++) {
    const d = ring[i][0] - ring[i - 1][0];
    if (d > 180) offset -= 360; else if (d < -180) offset += 360;
    out.push([ring[i][0] + offset, ring[i][1]]);
  }
  if (Math.abs(out[0][0] - out[out.length - 1][0]) > 180) {
    let meanLat = 0; for (const p of out) meanLat += p[1]; meanLat /= out.length;
    const pole = meanLat < 0 ? -90 : 90;
    out.push([out[out.length - 1][0], pole], [out[0][0], pole]);
  }
  return out;
}

export function fillPolygons(field, rings, { subRows = 4, value = 1, mode = 'add', wrap = false } = {}) {
  const W = field.width, H = field.height;
  const edges = [];
  let maxY1 = -Infinity;
  let minLon = Infinity, maxLon = -Infinity;
  const prepared = rings.map(r => (wrap ? unwrapRing(r) : r));
  if (wrap) for (const r of prepared) for (const p of r) { if (p[0] < minLon) minLon = p[0]; if (p[0] > maxLon) maxLon = p[0]; }
  const shifts = [0];
  if (wrap && maxLon > 180) shifts.push(-360);
  if (wrap && minLon < -180) shifts.push(360);
  for (const shift of shifts) {
    for (const ring of prepared) {
      const n = ring.length;
      for (let i = 0; i < n; i++) {
        const a = ring[i], b = ring[(i + 1) % n];
        let x0 = field.lonToX(a[0] + shift), y0 = field.latToY(a[1]);
        let x1 = field.lonToX(b[0] + shift), y1 = field.latToY(b[1]);
        if (y0 === y1) continue;
        if (y0 > y1) { const tx = x0; x0 = x1; x1 = tx; const ty = y0; y0 = y1; y1 = ty; }
        edges.push({ x0, y0, x1, y1, dxdy: (x1 - x0) / (y1 - y0) });
        if (y1 > maxY1) maxY1 = y1;
      }
    }
  }
  if (!edges.length) return;
  edges.sort((a, b) => a.y0 - b.y0);
  const minY = Math.max(0, Math.floor(edges[0].y0));
  const maxY = Math.min(H - 1, Math.ceil(maxY1));
  const cov = new Float32Array(W + 2);
  const step = 1 / subRows;
  const inc = value / subRows;
  let nextEdge = 0;
  const active = [];
  const xs = [];
  const d = field.data;
  for (let py = minY; py <= maxY; py++) {
    cov.fill(0);
    let touched = false;
    for (let s = 0; s < subRows; s++) {
      const sy = py + (s + 0.5) * step;
      while (nextEdge < edges.length && edges[nextEdge].y0 <= sy) active.push(edges[nextEdge++]);
      for (let i = active.length - 1; i >= 0; i--) if (active[i].y1 <= sy) active.splice(i, 1);
      xs.length = 0;
      for (const e of active) if (e.y0 <= sy && sy < e.y1) xs.push(e.x0 + (sy - e.y0) * e.dxdy);
      if (xs.length < 2) continue;
      xs.sort((a, b) => a - b);
      for (let i = 0; i + 1 < xs.length; i += 2) {
        let xa = Math.max(0, xs[i]), xb = Math.min(W, xs[i + 1]);
        if (xb <= xa) continue;
        touched = true;
        const ia = Math.floor(xa), ib = Math.floor(xb);
        if (ia === ib) cov[ia] += (xb - xa) * inc;
        else {
          cov[ia] += (ia + 1 - xa) * inc;
          for (let x = ia + 1; x < ib; x++) cov[x] += inc;
          if (ib < W) cov[ib] += (xb - ib) * inc;
        }
      }
    }
    if (!touched) continue;
    const row = py * W;
    if (mode === 'max') { for (let x = 0; x < W; x++) if (cov[x] > d[row + x]) d[row + x] = cov[x]; }
    else if (mode === 'sub') { for (let x = 0; x < W; x++) d[row + x] -= cov[x]; }
    else { for (let x = 0; x < W; x++) d[row + x] += cov[x]; }
  }
}

/**
 * Ellipse stamp. rx, ry in degrees (rx measured along local east-west, corrected for latitude). rot in degrees CCW.
 * power shapes falloff (1 = linear cone, 0.5 = flat top, 2 = soft bump). edge: if set, hard disc with AA edge fraction.
 */
export function stampEllipse(field, lon, lat, rx, ry, { value = 1, rot = 0, power = 1.5, mode = 'max', edge = 0 } = {}) {
  const W = field.width, H = field.height;
  const cosLat = Math.max(0.12, Math.cos(lat * Math.PI / 180));
  const r = Math.max(rx, ry) * 1.02;
  const x0 = Math.floor(field.lonToX(lon - r / cosLat)), x1 = Math.ceil(field.lonToX(lon + r / cosLat));
  const y0 = Math.max(0, Math.floor(field.latToY(lat + r))), y1 = Math.min(H - 1, Math.ceil(field.latToY(lat - r)));
  const cr = Math.cos(rot * Math.PI / 180), sr = Math.sin(rot * Math.PI / 180);
  const d = field.data;
  for (let y = y0; y <= y1; y++) {
    const plat = field.pxToLat(y + 0.5);
    for (let x = x0; x <= x1; x++) {
      const xx = ((x % W) + W) % W;
      const plon = field.pxToLon(x + 0.5);
      let dlon = plon - lon; if (dlon > 180) dlon -= 360; else if (dlon < -180) dlon += 360;
      const dx = dlon * cosLat, dy = plat - lat;
      const u = (dx * cr + dy * sr) / rx, v = (-dx * sr + dy * cr) / ry;
      const q = u * u + v * v;
      if (q >= 1) continue;
      const t = 1 - Math.sqrt(q);
      const w = (edge > 0 ? Math.min(1, t / edge) : Math.pow(t, power)) * value;
      const idx = y * W + xx;
      if (mode === 'max') { if (w > d[idx]) d[idx] = w; }
      else if (mode === 'sub') d[idx] -= w;
      else d[idx] += w;
    }
  }
}

/** Ridge stamp along a polyline of [lon, lat, (strength)] points. width in degrees. */
export function stampRidge(field, pts, width, { value = 1, mode = 'max', power = 1 } = {}) {
  const W = field.width, H = field.height;
  const d = field.data;
  for (let i = 0; i + 1 < pts.length; i++) {
    const lon0 = pts[i][0], lat0 = pts[i][1], lon1 = pts[i + 1][0], lat1 = pts[i + 1][1];
    const v0 = pts[i][2] ?? 1, v1 = pts[i + 1][2] ?? 1;
    const midLat = (lat0 + lat1) / 2;
    const cosLat = Math.max(0.12, Math.cos(midLat * Math.PI / 180));
    const margin = width * 1.05;
    const x0 = Math.floor(field.lonToX(Math.min(lon0, lon1) - margin / cosLat));
    const x1 = Math.ceil(field.lonToX(Math.max(lon0, lon1) + margin / cosLat));
    const y0 = Math.max(0, Math.floor(field.latToY(Math.max(lat0, lat1) + margin)));
    const y1 = Math.min(H - 1, Math.ceil(field.latToY(Math.min(lat0, lat1) - margin)));
    const ax = lon0 * cosLat, ay = lat0, bx = lon1 * cosLat, by = lat1;
    const abx = bx - ax, aby = by - ay, ab2 = abx * abx + aby * aby || 1e-9;
    for (let y = y0; y <= y1; y++) {
      const py = field.pxToLat(y + 0.5);
      for (let x = x0; x <= x1; x++) {
        const xx = ((x % W) + W) % W;
        const px = field.pxToLon(x + 0.5) * cosLat;
        let t = ((px - ax) * abx + (py - ay) * aby) / ab2;
        t = t < 0 ? 0 : t > 1 ? 1 : t;
        const dist = Math.hypot(px - (ax + abx * t), py - (ay + aby * t));
        if (dist >= width) continue;
        let s = 1 - dist / width;
        s = s * s * (3 - 2 * s);
        if (power !== 1) s = Math.pow(s, power);
        const w = s * value * (v0 * (1 - t) + v1 * t);
        const idx = y * W + xx;
        if (mode === 'max') { if (w > d[idx]) d[idx] = w; } else d[idx] += w;
      }
    }
  }
}

/** Gaussian blob. sigma in degrees. */
export function stampGaussian(field, lon, lat, sigma, value, { mode = 'add' } = {}) {
  const W = field.width, H = field.height;
  const cosLat = Math.max(0.15, Math.cos(lat * Math.PI / 180));
  const r = sigma * 3;
  const x0 = Math.floor(field.lonToX(lon - r / cosLat)), x1 = Math.ceil(field.lonToX(lon + r / cosLat));
  const y0 = Math.max(0, Math.floor(field.latToY(lat + r))), y1 = Math.min(H - 1, Math.ceil(field.latToY(lat - r)));
  const d = field.data;
  const inv = -0.5 / (sigma * sigma);
  for (let y = y0; y <= y1; y++) {
    const dy = field.pxToLat(y + 0.5) - lat;
    for (let x = x0; x <= x1; x++) {
      const xx = ((x % W) + W) % W;
      let dlon = field.pxToLon(x + 0.5) - lon; if (dlon > 180) dlon -= 360; else if (dlon < -180) dlon += 360;
      const dx = dlon * cosLat;
      const w = value * Math.exp((dx * dx + dy * dy) * inv);
      const idx = y * W + xx;
      if (mode === 'max') { if (w > d[idx]) d[idx] = w; } else d[idx] += w;
    }
  }
}

/** Separable box blur (wraps horizontally, clamps vertically); passes~3 approximates gaussian. */
export function boxBlur(field, radius, passes = 3) {
  const W = field.width, H = field.height;
  let src = field.data;
  const dst = new Float32Array(W * H);
  const norm = 1 / (2 * radius + 1);
  for (let p = 0; p < passes; p++) {
    for (let y = 0; y < H; y++) {
      const row = y * W;
      let acc = 0;
      for (let k = -radius; k <= radius; k++) acc += src[row + ((k % W + W) % W)];
      for (let x = 0; x < W; x++) {
        dst[row + x] = acc * norm;
        acc += src[row + ((x + radius + 1) % W)] - src[row + ((x - radius + W) % W)];
      }
    }
    for (let x = 0; x < W; x++) {
      let acc = 0;
      for (let k = -radius; k <= radius; k++) acc += dst[Math.max(0, Math.min(H - 1, k)) * W + x];
      for (let y = 0; y < H; y++) {
        src[y * W + x] = acc * norm;
        const yAdd = Math.min(H - 1, y + radius + 1), yRem = Math.max(0, y - radius);
        acc += dst[yAdd * W + x] - dst[yRem * W + x];
      }
    }
  }
  field.data = src;
  return field;
}

/** Downsample by integer factor (box filter). */
export function downsample(field, factor) {
  const W = field.width / factor | 0, H = field.height / factor | 0;
  const out = new Field(W, H);
  const inv = 1 / (factor * factor);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    let acc = 0;
    for (let j = 0; j < factor; j++) {
      const row = (y * factor + j) * field.width + x * factor;
      for (let i = 0; i < factor; i++) acc += field.data[row + i];
    }
    out.data[y * W + x] = acc * inv;
  }
  return out;
}

/** Resample to a new size (bilinear). */
export function resample(field, W, H) {
  const out = new Field(W, H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    out.data[y * W + x] = field.sample((x + 0.5) / W * field.width - 0.5, (y + 0.5) / H * field.height - 0.5);
  }
  return out;
}
