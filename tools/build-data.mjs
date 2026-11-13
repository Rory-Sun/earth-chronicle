// Data pipeline: world-atlas coastlines -> equirectangular hint maps for Blender + plate region polygons for the web app.
// Usage: node tools/build-data.mjs [--quick]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as topojson from 'topojson-client';
import { Field, fillPolygons, stampEllipse, stampRidge, stampGaussian, boxBlur, downsample, resample } from './lib/raster.mjs';
import { encodePNG, floatToGray8 } from './lib/png.mjs';
import { buildRegionMeshes } from '../src/earth/regionMesh.js';
import {
  MOUNTAINS, PLATEAUS, PLATEAU_POLYS, DESERTS, RAINFORESTS, ICE_POLYS, ICE_ELLIPSES, LAKES,
  CITIES, CORRIDORS, REGIONAL_GLOWS, SHELVES, REGIONS,
} from './geo/features.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const quick = process.argv.includes('--quick');
const BLENDER_IN = path.join(ROOT, 'blender', 'input');
const SRC_DATA = path.join(ROOT, 'src', 'data');
for (const d of [BLENDER_IN, SRC_DATA]) fs.mkdirSync(d, { recursive: true });

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

// ---------------------------------------------------------------- 4. plate regions for the web
// The app builds the plate meshes from these polygons when it starts (src/earth/regionMesh.js): shipping the
// meshes cost a 2.6 MB download, the polygons are 2 KB inside the script bundle. Built here once as a check.
const CELL = quick ? 2.0 : 1.0;
const regions = REGIONS.map((r) => ({ plate: r.plate, rings: r.rings }));
const meshes = buildRegionMeshes(regions, CELL);
fs.writeFileSync(path.join(SRC_DATA, 'regions.json'), JSON.stringify({ cell: CELL, regions }));
log('region meshes:', meshes.map((m) => `${m.plate}:${m.idx.length / 3}`).join(' '), '(built at runtime from src/data/regions.json)');

log('done');
