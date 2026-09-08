// Data pipeline: world-atlas coastlines -> equirectangular hint maps for Blender + plate region meshes for the web app.
// Usage: node tools/build-data.mjs [--quick]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as topojson from 'topojson-client';
import earcut from 'earcut';
import { Field, fillPolygons, stampEllipse, stampRidge, stampGaussian, boxBlur, downsample, resample } from './lib/raster.mjs';
import { encodePNG, floatToGray8 } from './lib/png.mjs';
import {
  MOUNTAINS, PLATEAUS, PLATEAU_POLYS, DESERTS, RAINFORESTS, ICE_POLYS, ICE_ELLIPSES, LAKES,
  CITIES, CORRIDORS, REGIONAL_GLOWS, SHELVES, REGIONS,
} from './geo/features.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const quick = process.argv.includes('--quick');
const BLENDER_IN = path.join(ROOT, 'blender', 'input');
const PUBLIC_DATA = path.join(ROOT, 'public', 'data');
const PUBLIC_TEX = path.join(ROOT, 'public', 'textures');
for (const d of [BLENDER_IN, PUBLIC_DATA, PUBLIC_TEX]) fs.mkdirSync(d, { recursive: true });

const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);

// ---------------------------------------------------------------- land polygons
const topo = JSON.parse(fs.readFileSync(path.join(ROOT, 'node_modules/world-atlas/land-50m.json'), 'utf8'));
const land = topojson.feature(topo, topo.objects.land).features[0].geometry.coordinates; // MultiPolygon
log('land polygons:', land.length);

// ---------------------------------------------------------------- 1. land mask (8K)
const LW = quick ? 2048 : 8192, LH = LW / 2;
const landmask = new Field(LW, LH);
for (const poly of land) fillPolygons(landmask, poly, { subRows: quick ? 2 : 4, wrap: true });
landmask.clamp01();
for (const [lon, lat, rx, ry, rot] of LAKES) stampEllipse(landmask, lon, lat, rx, ry, { value: 1, rot, edge: 0.12, mode: 'sub' });
landmask.clamp01();
fs.writeFileSync(path.join(BLENDER_IN, 'landmask.png'), encodePNG(LW, LH, 1, floatToGray8(landmask.data)));
log('landmask written', LW, 'x', LH);

// blurred land fraction (for continental shelf / coastal tinting)
const landLow = downsample(landmask, LW / 1024);
const landBlur = boxBlur(new Field(1024, 512).maxWith(landLow), 3, 3);
fs.writeFileSync(path.join(BLENDER_IN, 'landblur.png'), encodePNG(1024, 512, 1, floatToGray8(landBlur.data)));
const landBlurWide = boxBlur(new Field(1024, 512).maxWith(landLow), 22, 3);
fs.writeFileSync(path.join(BLENDER_IN, 'landblur_wide.png'), encodePNG(1024, 512, 1, floatToGray8(landBlurWide.data)));
log('landblur written');

// ---------------------------------------------------------------- 2. geo hint maps (4K RGBA)
const GW = quick ? 1024 : 4096, GH = GW / 2;
const landG = resample(landmask, GW, GH);

const relief = new Field(GW, GH);
for (const m of MOUNTAINS) stampRidge(relief, m.p, m.w, { value: m.h, mode: 'max' });
const plateau = new Field(GW, GH);
for (const [lon, lat, rx, ry, h, rot] of PLATEAUS) if (h > 0) stampEllipse(plateau, lon, lat, rx, ry, { value: h, rot, power: 0.6, mode: 'max' });
for (const pp of PLATEAU_POLYS) fillPolygons(plateau, [pp.p], { value: pp.h, mode: 'max', subRows: 2 });
boxBlur(plateau, Math.max(2, Math.round(GW / 4096 * 10)), 3);
relief.maxWith(plateau);
relief.multiply(landG).clamp01();

const arid = new Field(GW, GH);
for (const [lon, lat, rx, ry, v, rot] of DESERTS) stampEllipse(arid, lon, lat, rx, ry, { value: v, rot, power: 1.25, mode: 'max' });
arid.clamp01();

const moist = new Field(GW, GH);
for (const [lon, lat, rx, ry, v, rot] of RAINFORESTS) stampEllipse(moist, lon, lat, rx, ry, { value: v, rot, power: 1.1, mode: 'max' });
moist.clamp01();

const ice = new Field(GW, GH);
for (const p of ICE_POLYS) fillPolygons(ice, [p], { value: 1, mode: 'max', subRows: 2 });
for (const [lon, lat, rx, ry, v, rot] of ICE_ELLIPSES) stampEllipse(ice, lon, lat, rx, ry, { value: v, rot, power: 0.5, mode: 'max' });
ice.multiply(landG).clamp01();

{
  const rgba = new Uint8Array(GW * GH * 4);
  for (let i = 0; i < GW * GH; i++) {
    rgba[i * 4] = Math.round(relief.data[i] * 255);
    rgba[i * 4 + 1] = Math.round(arid.data[i] * 255);
    rgba[i * 4 + 2] = Math.round(moist.data[i] * 255);
    rgba[i * 4 + 3] = Math.round(ice.data[i] * 255);
  }
  fs.writeFileSync(path.join(BLENDER_IN, 'geo.png'), encodePNG(GW, GH, 4, rgba));
}
log('geo hint map written', GW, 'x', GH);

// continental shelves (exposed at glacial sea levels)
const shelf = new Field(GW, GH);
for (const s of SHELVES) fillPolygons(shelf, [s.p], { value: 1, mode: 'max', subRows: 2 });
boxBlur(shelf, Math.max(2, Math.round(GW / 4096 * 14)), 3);
shelf.clamp01();
fs.writeFileSync(path.join(BLENDER_IN, 'shelf.png'), encodePNG(GW, GH, 1, floatToGray8(shelf.data)));
log('shelf written');

// ---------------------------------------------------------------- 3. night lights (4K)
const lights = new Field(GW, GH);
for (const [lon, lat, w] of CITIES) {
  stampGaussian(lights, lon, lat, 0.12 + 0.35 * w * w, 0.35 + 0.9 * w);
  stampGaussian(lights, lon, lat, 0.5 + 1.2 * w * w, 0.08 * w);
}
for (const c of CORRIDORS) stampRidge(lights, c.p, c.w, { value: c.v, mode: 'add', power: 1.5 });
for (const [lon, lat, s, v] of REGIONAL_GLOWS) stampGaussian(lights, lon, lat, s, v);
lights.map(v => v / (v + 0.6)); // soft clip
lights.multiply(landG).clamp01();
fs.writeFileSync(path.join(BLENDER_IN, 'lights.png'), encodePNG(GW, GH, 1, floatToGray8(lights.data)));
log('lights written');

// ---------------------------------------------------------------- 4. plate region meshes for the web
// A lon/lat grid is clipped against each region polygon: interior cells become quads, boundary cells are clipped
// exactly (Sutherland-Hodgman) so plate edges are precise and there are no T-junctions inside a region.
const CELL = quick ? 2.0 : 1.0;
function buildLines(min, max, step, extra) {
  const s = new Set([min, max, ...extra]);
  for (let v = min + 0.5; v < max; v += step) s.add(+v.toFixed(4));
  return [...s].sort((a, b) => a - b);
}
const holeEdgesLon = [], holeEdgesLat = [];
for (const r of REGIONS) for (let k = 1; k < r.rings.length; k++) for (const [lon, lat] of r.rings[k]) { holeEdgesLon.push(lon); holeEdgesLat.push(lat); }
const lonLines = buildLines(-180, 180, CELL, holeEdgesLon);
const latLines = buildLines(-90, 90, CELL, holeEdgesLat);

function pointInPoly(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function clipHalf(poly, inside, intersect) {
  const res = [];
  for (let i = 0; i < poly.length; i++) {
    const cur = poly[i], prev = poly[(i + poly.length - 1) % poly.length];
    const ci = inside(cur), pi = inside(prev);
    if (ci) { if (!pi) res.push(intersect(prev, cur)); res.push(cur); }
    else if (pi) res.push(intersect(prev, cur));
  }
  return res;
}
const ix = (a, b, x) => { const t = (x - a[0]) / (b[0] - a[0]); return [x, +(a[1] + (b[1] - a[1]) * t).toFixed(6)]; };
const iy = (a, b, y) => { const t = (y - a[1]) / (b[1] - a[1]); return [+(a[0] + (b[0] - a[0]) * t).toFixed(6), y]; };
function clipRect(poly, x0, x1, y0, y1) {
  let out = clipHalf(poly, p => p[0] >= x0, (a, b) => ix(a, b, x0));
  out = clipHalf(out, p => p[0] <= x1, (a, b) => ix(a, b, x1));
  out = clipHalf(out, p => p[1] >= y0, (a, b) => iy(a, b, y0));
  out = clipHalf(out, p => p[1] <= y1, (a, b) => iy(a, b, y1));
  // drop consecutive duplicates
  const res = [];
  for (const p of out) { const q = res[res.length - 1]; if (!q || Math.abs(q[0] - p[0]) > 1e-7 || Math.abs(q[1] - p[1]) > 1e-7) res.push(p); }
  if (res.length > 1 && Math.abs(res[0][0] - res[res.length - 1][0]) < 1e-7 && Math.abs(res[0][1] - res[res.length - 1][1]) < 1e-7) res.pop();
  return res;
}
function polyArea(poly) { let a = 0; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) a += (poly[j][0] + poly[i][0]) * (poly[j][1] - poly[i][1]); return a / 2; }

const buckets = new Map(); // plate -> geometry accumulator
function bucketFor(plate) {
  if (!buckets.has(plate)) buckets.set(plate, { pos: [], uv: [], idx: [], map: new Map(), cells: 0, pieces: 0 });
  return buckets.get(plate);
}
function vertexIndex(b, lon, lat) {
  const key = Math.round(lon * 1e4) + ',' + Math.round(lat * 1e4);
  let i = b.map.get(key);
  if (i !== undefined) return i;
  i = b.pos.length / 3;
  const phi = (90 - lat) * Math.PI / 180, theta = (lon + 180) * Math.PI / 180;
  // Three.js SphereGeometry convention: x = -cos(theta) sin(phi), y = cos(phi), z = sin(theta) sin(phi)
  b.pos.push(-Math.cos(theta) * Math.sin(phi), Math.cos(phi), Math.sin(theta) * Math.sin(phi));
  b.uv.push((lon + 180) / 360, (lat + 90) / 180);
  b.map.set(key, i);
  return i;
}
function emitTri(b, a, c, d) { // CCW in lon/lat
  const area = (c[0] - a[0]) * (d[1] - a[1]) - (d[0] - a[0]) * (c[1] - a[1]);
  if (Math.abs(area) < 1e-10) return;
  if (area < 0) { const t = c; c = d; d = t; }
  b.idx.push(vertexIndex(b, a[0], a[1]), vertexIndex(b, c[0], c[1]), vertexIndex(b, d[0], d[1]));
}
function emitPiece(b, piece) {
  if (piece.length < 3) return;
  if (piece.length === 3) { emitTri(b, piece[0], piece[1], piece[2]); return; }
  const flat = piece.flat();
  const tri = earcut(flat, null, 2);
  for (let i = 0; i < tri.length; i += 3) emitTri(b, piece[tri[i]], piece[tri[i + 1]], piece[tri[i + 2]]);
}

for (const region of REGIONS) {
  const outer = region.rings[0], holes = region.rings.slice(1);
  const b = bucketFor(region.plate);
  const lons = outer.map(p => p[0]), lats = outer.map(p => p[1]);
  const minLon = Math.min(...lons), maxLon = Math.max(...lons), minLat = Math.min(...lats), maxLat = Math.max(...lats);
  for (let j = 0; j + 1 < latLines.length; j++) {
    const y0 = latLines[j], y1 = latLines[j + 1];
    if (y1 <= minLat || y0 >= maxLat) continue;
    for (let i = 0; i + 1 < lonLines.length; i++) {
      const x0 = lonLines[i], x1 = lonLines[i + 1];
      if (x1 <= minLon || x0 >= maxLon) continue;
      const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
      if (holes.some(h => pointInPoly(cx, cy, h))) continue;
      const piece = clipRect(outer, x0, x1, y0, y1);
      if (piece.length < 3) continue;
      const cellArea = (x1 - x0) * (y1 - y0);
      if (piece.length === 4 && Math.abs(Math.abs(polyArea(piece)) - cellArea) < 1e-7) {
        emitTri(b, [x0, y0], [x1, y0], [x1, y1]);
        emitTri(b, [x0, y0], [x1, y1], [x0, y1]);
        b.cells++;
      } else {
        if (Math.abs(polyArea(piece)) < 1e-8) continue;
        emitPiece(b, piece);
        b.pieces++;
      }
    }
  }
}

const meta = { plates: [], cell: CELL, generated: new Date().toISOString(), regions: REGIONS.map((r) => ({ plate: r.plate, rings: r.rings })) };
const buffers = [];
let offset = 0;
for (const [plate, g] of buckets) {
  const pos = new Float32Array(g.pos), uv = new Float32Array(g.uv), idx = new Uint32Array(g.idx);
  const entry = { plate, vertexCount: pos.length / 3, triangleCount: idx.length / 3, posOffset: offset, uvOffset: 0, idxOffset: 0 };
  buffers.push(Buffer.from(pos.buffer)); offset += pos.byteLength;
  entry.uvOffset = offset; buffers.push(Buffer.from(uv.buffer)); offset += uv.byteLength;
  entry.idxOffset = offset; buffers.push(Buffer.from(idx.buffer)); offset += idx.byteLength;
  meta.plates.push(entry);
}
fs.writeFileSync(path.join(PUBLIC_DATA, 'regions.bin'), Buffer.concat(buffers));
fs.writeFileSync(path.join(PUBLIC_DATA, 'regions.json'), JSON.stringify(meta));
log('region meshes:', meta.plates.map(p => `${p.plate}:${p.triangleCount}`).join(' '), `(${(offset / 1e6).toFixed(2)} MB)`);

// low-res land mask for the web app (coastline overlays)
const lm2k = resample(landmask, 2048, 1024);
fs.writeFileSync(path.join(PUBLIC_TEX, 'landmask_2k.png'), encodePNG(2048, 1024, 1, floatToGray8(lm2k.data)));
for (const f of ['plates.bin', 'plates.json']) { try { fs.unlinkSync(path.join(PUBLIC_DATA, f)); } catch {} }
log('done');
