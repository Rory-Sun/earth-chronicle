// Environment parameters as a function of time (years before present). Piecewise-linear keyframes.

const DEFAULT = {
  sun: 1.0, oceanDeep: [0.010, 0.036, 0.11], oceanShallow: [0.028, 0.13, 0.22],
  atmoColor: [0.30, 0.55, 1.0], hazeColor: [1.0, 0.45, 0.18], atmoStrength: 1.0,
  veg: 1.0, iceLat: 90, iceBoost: 0.0, erosion: 0.0, lava: 0.0, clouds: 0.95, cloudTint: [1, 1, 1],
  lights: 0.0, seaLevel: 0.0, moonDist: 1.0, seaIce: 1.0, barrenTint: [1, 1, 1], impact: 0.0,
};

// keyframes in Ma (millions of years before present); partial objects inherit interpolated defaults
const KEYS_MA = [
  [4540, { sun: 0.70, lava: 1.0, erosion: 1.0, veg: 0, oceanDeep: [0.06, 0.02, 0.01], oceanShallow: [0.10, 0.04, 0.02], atmoColor: [1.0, 0.45, 0.15], hazeColor: [1.0, 0.35, 0.1], atmoStrength: 0.7, clouds: 0.75, cloudTint: [0.85, 0.55, 0.35], moonDist: 0.06, iceLat: 90, seaIce: 0, barrenTint: [0.9, 0.7, 0.6] }],
  [4450, { sun: 0.71, lava: 0.85, erosion: 1.0, veg: 0, oceanDeep: [0.05, 0.02, 0.012], oceanShallow: [0.08, 0.04, 0.02], atmoColor: [1.0, 0.5, 0.2], hazeColor: [1.0, 0.4, 0.12], atmoStrength: 0.8, clouds: 0.9, cloudTint: [0.8, 0.6, 0.45], moonDist: 0.08, seaIce: 0, barrenTint: [0.9, 0.7, 0.6] }],
  [4300, { sun: 0.72, lava: 0.45, erosion: 0.98, veg: 0, oceanDeep: [0.03, 0.03, 0.03], oceanShallow: [0.06, 0.06, 0.05], atmoColor: [0.95, 0.55, 0.25], hazeColor: [1.0, 0.45, 0.15], atmoStrength: 0.85, clouds: 0.85, cloudTint: [0.85, 0.7, 0.55], moonDist: 0.12, seaIce: 0, barrenTint: [0.9, 0.75, 0.65] }],
  [4000, { sun: 0.74, lava: 0.12, erosion: 0.95, veg: 0, oceanDeep: [0.02, 0.05, 0.06], oceanShallow: [0.05, 0.10, 0.09], atmoColor: [0.9, 0.6, 0.3], hazeColor: [1.0, 0.5, 0.2], atmoStrength: 0.85, clouds: 0.8, cloudTint: [0.9, 0.8, 0.7], moonDist: 0.2, seaIce: 0.2, barrenTint: [0.85, 0.75, 0.68] }],
  [3800, { sun: 0.75, lava: 0.03, erosion: 0.92, veg: 0, oceanDeep: [0.02, 0.06, 0.06], oceanShallow: [0.05, 0.12, 0.10], atmoColor: [0.85, 0.6, 0.35], hazeColor: [1.0, 0.5, 0.2], atmoStrength: 0.85, clouds: 0.75, cloudTint: [0.92, 0.85, 0.75], moonDist: 0.25, seaIce: 0.3 }],
  [3200, { sun: 0.78, lava: 0.0, erosion: 0.86, veg: 0, oceanDeep: [0.015, 0.06, 0.07], oceanShallow: [0.04, 0.13, 0.12], atmoColor: [0.8, 0.62, 0.4], hazeColor: [1.0, 0.5, 0.2], atmoStrength: 0.85, clouds: 0.75, cloudTint: [0.95, 0.9, 0.82], moonDist: 0.35, seaIce: 0.4 }],
  [2500, { sun: 0.82, erosion: 0.78, veg: 0, oceanDeep: [0.012, 0.05, 0.09], oceanShallow: [0.035, 0.13, 0.17], atmoColor: [0.7, 0.62, 0.55], hazeColor: [1.0, 0.5, 0.2], atmoStrength: 0.9, clouds: 0.8, cloudTint: [0.97, 0.95, 0.9], moonDist: 0.45, seaIce: 0.6 }],
  [2300, { sun: 0.83, erosion: 0.75, veg: 0, oceanDeep: [0.010, 0.04, 0.10], oceanShallow: [0.03, 0.13, 0.20], atmoColor: [0.45, 0.6, 0.95], hazeColor: [1.0, 0.5, 0.2], atmoStrength: 0.95, clouds: 0.85, cloudTint: [1, 1, 1], moonDist: 0.5, iceLat: 45, iceBoost: 0.35, seaIce: 1 }],
  [2200, { erosion: 0.74, veg: 0, iceLat: 80, iceBoost: 0.0 }],
  [1800, { sun: 0.86, erosion: 0.68, veg: 0, moonDist: 0.6, iceLat: 90 }],
  [1000, { sun: 0.91, erosion: 0.52, veg: 0, moonDist: 0.75, iceLat: 90 }],
  [730, { sun: 0.93, erosion: 0.42, veg: 0, iceLat: 70, moonDist: 0.8 }],
  [715, { erosion: 0.42, veg: 0, iceLat: 3, iceBoost: 0.9, clouds: 0.5, seaLevel: -100 }],
  [665, { erosion: 0.40, veg: 0, iceLat: 3, iceBoost: 0.9, clouds: 0.5, seaLevel: -100 }],
  [655, { erosion: 0.40, veg: 0, iceLat: 70, iceBoost: 0.0, clouds: 0.9, seaLevel: 0 }],
  [648, { erosion: 0.40, veg: 0, iceLat: 3, iceBoost: 0.85, clouds: 0.5, seaLevel: -100 }],
  [636, { erosion: 0.40, veg: 0, iceLat: 3, iceBoost: 0.85, clouds: 0.5, seaLevel: -100 }],
  [628, { erosion: 0.38, veg: 0, iceLat: 75, iceBoost: 0.0, clouds: 0.9, seaLevel: 0 }],
  [580, { erosion: 0.34, veg: 0, iceLat: 60, iceBoost: 0.1 }],
  [560, { erosion: 0.32, veg: 0, iceLat: 90 }],
  [541, { sun: 0.95, erosion: 0.28, veg: 0.0, iceLat: 90, seaLevel: 40, moonDist: 0.85 }],
  [485, { erosion: 0.22, veg: 0.02, iceLat: 90, seaLevel: 100 }],
  [470, { erosion: 0.2, veg: 0.06, seaLevel: 120 }],
  [446, { erosion: 0.19, veg: 0.08, iceLat: 55, iceBoost: 0.15, seaLevel: 20 }],
  [438, { erosion: 0.18, veg: 0.1, iceLat: 90, iceBoost: 0.0, seaLevel: 90 }],
  [419, { erosion: 0.16, veg: 0.18, seaLevel: 90 }],
  [385, { erosion: 0.13, veg: 0.5, seaLevel: 110 }],
  [359, { erosion: 0.1, veg: 0.75, seaLevel: 60, iceLat: 80 }],
  [330, { erosion: 0.08, veg: 0.92, seaLevel: 20, iceLat: 55, iceBoost: 0.12 }],
  [299, { erosion: 0.06, veg: 0.85, seaLevel: -10, iceLat: 52, iceBoost: 0.18 }],
  [270, { erosion: 0.05, veg: 0.7, seaLevel: -20, iceLat: 70, iceBoost: 0.0 }],
  [253, { erosion: 0.05, veg: 0.6, seaLevel: -30, iceLat: 90 }],
  [251, { erosion: 0.05, veg: 0.2, seaLevel: -30, iceLat: 90, atmoColor: [0.75, 0.55, 0.4], hazeColor: [1.0, 0.4, 0.1], clouds: 0.7, cloudTint: [0.9, 0.8, 0.7], barrenTint: [0.9, 0.7, 0.55] }],
  [245, { veg: 0.45, atmoColor: [0.45, 0.58, 0.95], cloudTint: [1, 1, 1], barrenTint: [1, 1, 1] }],
  [230, { veg: 0.75, atmoColor: [0.30, 0.55, 1.0], seaLevel: 0 }],
  [201, { veg: 0.8, seaLevel: 30, iceLat: 90 }],
  [170, { sun: 0.97, veg: 0.9, seaLevel: 80, moonDist: 0.93 }],
  [145, { veg: 0.9, seaLevel: 110 }],
  [100, { veg: 0.95, seaLevel: 150, iceLat: 90 }],
  [70, { veg: 0.95, seaLevel: 120 }],
  [66.05, { veg: 0.95, seaLevel: 120, impact: 0 }],
  [66.0, { veg: 0.9, seaLevel: 120, impact: 1.0 }],
  [65.9, { veg: 0.25, seaLevel: 120, impact: 0.3, atmoColor: [0.6, 0.55, 0.5], clouds: 1.0, cloudTint: [0.6, 0.55, 0.5], sun: 0.8 }],
  [65.5, { veg: 0.5, impact: 0, atmoColor: [0.4, 0.55, 0.95], clouds: 0.95, cloudTint: [0.9, 0.9, 0.9], sun: 0.95 }],
  [62, { veg: 0.9, seaLevel: 100, atmoColor: [0.30, 0.55, 1.0], cloudTint: [1, 1, 1], sun: 0.98 }],
  [56, { veg: 1.0, seaLevel: 90 }],
  [45, { veg: 1.0, seaLevel: 70, iceLat: 90 }],
  [34, { veg: 1.0, seaLevel: 40, iceLat: 82, iceBoost: 0.0 }],
  [23, { veg: 1.0, seaLevel: 30, iceLat: 80 }],
  [14, { veg: 1.0, seaLevel: 20, iceLat: 77 }],
  [5.3, { veg: 1.0, seaLevel: 10, iceLat: 75 }],
  [2.58, { sun: 1.0, veg: 1.0, seaLevel: 0, iceLat: 72, moonDist: 1.0 }],
  [1.0, { seaLevel: -40, iceLat: 64, iceBoost: 0.1 }],
  [0.5, { seaLevel: -60, iceLat: 60, iceBoost: 0.15 }],
  // late Pleistocene detail (ka -> Ma)
  [0.300, { seaLevel: -100, iceLat: 57, iceBoost: 0.25 }],
  [0.243, { seaLevel: -20, iceLat: 68, iceBoost: 0.05 }],
  [0.190, { seaLevel: -90, iceLat: 58, iceBoost: 0.22 }],
  [0.140, { seaLevel: -120, iceLat: 54, iceBoost: 0.32 }],
  [0.125, { seaLevel: 5, iceLat: 70, iceBoost: 0.0 }],
  [0.110, { seaLevel: -30, iceLat: 66, iceBoost: 0.05 }],
  [0.090, { seaLevel: -60, iceLat: 62, iceBoost: 0.12 }],
  [0.070, { seaLevel: -80, iceLat: 60, iceBoost: 0.18 }],
  [0.050, { seaLevel: -70, iceLat: 61, iceBoost: 0.16 }],
  [0.030, { seaLevel: -90, iceLat: 58, iceBoost: 0.24 }],
  [0.021, { seaLevel: -125, iceLat: 52, iceBoost: 0.36 }],
  [0.017, { seaLevel: -115, iceLat: 54, iceBoost: 0.32 }],
  [0.0145, { seaLevel: -95, iceLat: 57, iceBoost: 0.25 }],
  [0.0117, { seaLevel: -60, iceLat: 62, iceBoost: 0.12 }],
  [0.009, { seaLevel: -30, iceLat: 67, iceBoost: 0.04 }],
  [0.006, { seaLevel: -2, iceLat: 75, iceBoost: 0.0 }],
  [0.0002, { seaLevel: 0, iceLat: 75, lights: 0.0 }],
  [0.00014, { lights: 0.02 }],
  [0.00009, { lights: 0.15 }],
  [0.00005, { lights: 0.55 }],
  [0.00002, { lights: 0.9 }],
  [0.0, { lights: 1.0, seaLevel: 0, iceLat: 75.5, iceBoost: 0.0 }],
];

// resolve partial keys: every key gets full values by carrying forward interpolation between explicit values
const PROPS = Object.keys(DEFAULT);
function resolveKeys(keys) {
  const sorted = keys.slice().sort((a, b) => b[0] - a[0]); // descending Ma (old -> recent)
  const out = sorted.map(([t, v]) => ({ t, v: { ...v } }));
  for (const prop of PROPS) {
    // find explicit indices
    const idx = [];
    out.forEach((k, i) => { if (k.v[prop] !== undefined) idx.push(i); });
    if (!idx.length) { out.forEach((k) => (k.v[prop] = DEFAULT[prop])); continue; }
    for (let i = 0; i < out.length; i++) {
      if (out[i].v[prop] !== undefined) continue;
      // find neighbours
      let a = -1, b = -1;
      for (const j of idx) { if (j < i) a = j; if (j > i && b < 0) b = j; }
      if (a < 0) out[i].v[prop] = out[b].v[prop];
      else if (b < 0) out[i].v[prop] = out[a].v[prop];
      else {
        const f = (out[i].t - out[a].t) / (out[b].t - out[a].t);
        out[i].v[prop] = lerpVal(out[a].v[prop], out[b].v[prop], f);
      }
    }
  }
  return out; // descending t
}
function lerpVal(a, b, f) {
  if (Array.isArray(a)) return a.map((x, i) => x + (b[i] - x) * f);
  return a + (b - a) * f;
}
const RESOLVED = resolveKeys(KEYS_MA);

/** Environment at yearsBP (years before present). */
export function environmentAt(yearsBP) {
  const tMa = Math.max(0, yearsBP) / 1e6;
  const keys = RESOLVED; // descending
  let env;
  if (tMa >= keys[0].t) env = { ...keys[0].v };
  else if (tMa <= keys[keys.length - 1].t) env = { ...keys[keys.length - 1].v };
  else {
    let i = 0;
    while (keys[i + 1].t > tMa) i++;
    const a = keys[i], b = keys[i + 1];
    const f = (a.t - tMa) / (a.t - b.t);
    env = {};
    for (const p of PROPS) env[p] = lerpVal(a.v[p], b.v[p], f);
  }
  env.yearsBP = yearsBP;
  return env;
}

export function defaultEnvironment() { return { ...environmentAt(0) }; }
