// Plate region meshes, built from the region polygons (src/data/regions.json) when the app starts.
// They used to be shipped as a 2.6 MB binary; the polygons that describe them are 3 KB and building the
// meshes takes a few dozen milliseconds, so the download was pure waste on a slow connection.
//
// A lon/lat grid is clipped against each region polygon: interior cells become quads, boundary cells are clipped
// exactly (Sutherland-Hodgman) so plate edges are precise and there are no T-junctions inside a region.
import earcut from 'earcut';

function buildLines(min, max, step, extra) {
  const s = new Set([min, max, ...extra]);
  for (let v = min + 0.5; v < max; v += step) s.add(+v.toFixed(4));
  return [...s].sort((a, b) => a - b);
}
/** Ring as flat coordinate arrays plus its bounding box, for fast point-in-polygon tests. */
function flatRing(poly) {
  const n = poly.length, xs = new Float64Array(n), ys = new Float64Array(n);
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < n; i++) {
    const x = poly[i][0], y = poly[i][1];
    xs[i] = x; ys[i] = y;
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  return { n, xs, ys, x0, x1, y0, y1 };
}
function pointInRing(x, y, r) {
  if (x < r.x0 || x > r.x1 || y < r.y0 || y > r.y1) return false;
  const { n, xs, ys } = r;
  let inside = false;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const yi = ys[i], yj = ys[j];
    if ((yi > y) !== (yj > y) && x < (xs[j] - xs[i]) * (y - yi) / (yj - yi) + xs[i]) inside = !inside;
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
  let out = clipHalf(poly, (p) => p[0] >= x0, (a, b) => ix(a, b, x0));
  out = clipHalf(out, (p) => p[0] <= x1, (a, b) => ix(a, b, x1));
  out = clipHalf(out, (p) => p[1] >= y0, (a, b) => iy(a, b, y0));
  out = clipHalf(out, (p) => p[1] <= y1, (a, b) => iy(a, b, y1));
  // drop consecutive duplicates
  const res = [];
  for (const p of out) { const q = res[res.length - 1]; if (!q || Math.abs(q[0] - p[0]) > 1e-7 || Math.abs(q[1] - p[1]) > 1e-7) res.push(p); }
  if (res.length > 1 && Math.abs(res[0][0] - res[res.length - 1][0]) < 1e-7 && Math.abs(res[0][1] - res[res.length - 1][1]) < 1e-7) res.pop();
  return res;
}
function polyArea(poly) { let a = 0; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) a += (poly[j][0] + poly[i][0]) * (poly[j][1] - poly[i][1]); return a / 2; }

/**
 * @param regions [{ plate, rings: [outer, ...holes] }] with rings as [lon, lat] pairs in degrees
 * @param cell grid step in degrees
 * @returns one mesh per plate, in order of first appearance: [{ plate, pos, uv, idx, cells, pieces }]
 */
export function buildRegionMeshes(regions, cell = 1) {
  const holeEdgesLon = [], holeEdgesLat = [];
  for (const r of regions) for (let k = 1; k < r.rings.length; k++) for (const [lon, lat] of r.rings[k]) { holeEdgesLon.push(lon); holeEdgesLat.push(lat); }
  const lonLines = buildLines(-180, 180, cell, holeEdgesLon);
  const latLines = buildLines(-90, 90, cell, holeEdgesLat);

  const buckets = new Map(); // plate -> geometry accumulator
  const bucketFor = (plate) => {
    if (!buckets.has(plate)) buckets.set(plate, { pos: [], uv: [], idx: [], map: new Map(), cells: 0, pieces: 0 });
    return buckets.get(plate);
  };
  const vertexIndex = (b, lon, lat) => {
    const key = Math.round(lon * 1e4) * 4e6 + Math.round(lat * 1e4); // one number per 1e-4 degree cell (a string key cost 3x the time)
    let i = b.map.get(key);
    if (i !== undefined) return i;
    i = b.pos.length / 3;
    const phi = (90 - lat) * Math.PI / 180, theta = (lon + 180) * Math.PI / 180;
    // Three.js SphereGeometry convention: x = -cos(theta) sin(phi), y = cos(phi), z = sin(theta) sin(phi)
    b.pos.push(-Math.cos(theta) * Math.sin(phi), Math.cos(phi), Math.sin(theta) * Math.sin(phi));
    b.uv.push((lon + 180) / 360, (lat + 90) / 180);
    b.map.set(key, i);
    return i;
  };
  const emitTri = (b, a, c, d) => { // CCW in lon/lat
    const area = (c[0] - a[0]) * (d[1] - a[1]) - (d[0] - a[0]) * (c[1] - a[1]);
    if (Math.abs(area) < 1e-10) return;
    if (area < 0) { const t = c; c = d; d = t; }
    b.idx.push(vertexIndex(b, a[0], a[1]), vertexIndex(b, c[0], c[1]), vertexIndex(b, d[0], d[1]));
  };
  const emitPiece = (b, piece) => {
    if (piece.length < 3) return;
    if (piece.length === 3) { emitTri(b, piece[0], piece[1], piece[2]); return; }
    const tri = earcut(piece.flat(), null, 2);
    for (let i = 0; i < tri.length; i += 3) emitTri(b, piece[tri[i]], piece[tri[i + 1]], piece[tri[i + 2]]);
  };

  for (const region of regions) {
    const outer = region.rings[0], holes = region.rings.slice(1).map(flatRing), outerFlat = flatRing(outer);
    const b = bucketFor(region.plate);
    const lons = outer.map((p) => p[0]), lats = outer.map((p) => p[1]);
    const minLon = Math.min(...lons), maxLon = Math.max(...lons), minLat = Math.min(...lats), maxLat = Math.max(...lats);
    // bounding box of every polygon edge: a cell that touches none of them is wholly inside or wholly outside,
    // which one point-in-polygon test settles; only the cells along the boundary need the exact (slow) clipping
    const E = outer.length, ex0 = new Float64Array(E), ex1 = new Float64Array(E), ey0 = new Float64Array(E), ey1 = new Float64Array(E);
    for (let e = 0; e < E; e++) {
      const p = outer[e], q = outer[(e + 1) % E];
      ex0[e] = Math.min(p[0], q[0]); ex1[e] = Math.max(p[0], q[0]); ey0[e] = Math.min(p[1], q[1]); ey1[e] = Math.max(p[1], q[1]);
    }
    for (let j = 0; j + 1 < latLines.length; j++) {
      const y0 = latLines[j], y1 = latLines[j + 1];
      if (y1 <= minLat || y0 >= maxLat) continue;
      for (let i = 0; i + 1 < lonLines.length; i++) {
        const x0 = lonLines[i], x1 = lonLines[i + 1];
        if (x1 <= minLon || x0 >= maxLon) continue;
        const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
        if (holes.some((h) => pointInRing(cx, cy, h))) continue;
        let onBoundary = false;
        for (let e = 0; e < E; e++) if (ex0[e] <= x1 && ex1[e] >= x0 && ey0[e] <= y1 && ey1[e] >= y0) { onBoundary = true; break; }
        if (!onBoundary) {
          if (!pointInRing(cx, cy, outerFlat)) continue;
          emitTri(b, [x0, y0], [x1, y0], [x1, y1]);
          emitTri(b, [x0, y0], [x1, y1], [x0, y1]);
          b.cells++;
          continue;
        }
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

  return [...buckets].map(([plate, g]) => ({
    plate, pos: new Float32Array(g.pos), uv: new Float32Array(g.uv), idx: new Uint32Array(g.idx), cells: g.cells, pieces: g.pieces,
  }));
}
