// Approximate plate motion model (Ma). Each plate has a present-day reference point and keyframes giving the
// destination of that point (lon, lat) plus a twist about it (degrees, CCW seen from above).
// Small plates are *attached* to a parent plate before their rifting time, so supercontinents assemble seamlessly.
// This is a visual reconstruction inspired by standard paleogeographic maps, not a scientific dataset.
import * as THREE from 'three';

export const PLATE_INFO = {
  AFR: { name: '非洲板块', ref: [20, 5] },
  NAM: { name: '北美板块', ref: [-100, 45], attach: { parent: 'AFR', until: 180, offset: [53, -5, -20] } },
  SAM: { name: '南美板块', ref: [-60, -15], attach: { parent: 'AFR', until: 125, offset: [38, 18, -15] } },
  EUR: { name: '欧亚板块', ref: [80, 55], attach: { parent: 'NAM', until: 55, offset: [-24, 2, 0] } },
  ANT: { name: '南极板块', ref: [0, -80] },
  AUS: { name: '澳大利亚板块', ref: [135, -25], attach: { parent: 'ANT', until: 45, offset: [-2, -29, 4] } },
  IND: { name: '印度板块', ref: [78, 22], attach: { parent: 'ANT', until: 130, offset: [-22, -64, 35] } },
  MAD: { name: '马达加斯加', ref: [47, -19], attach: { parent: 'AFR', until: 160, offset: [-5, 7, -8] } },
  ARA: { name: '阿拉伯板块', ref: [45, 23], attach: { parent: 'AFR', until: 30, offset: [-3.5, -1, 3] } },
};

// Own keyframes (used for t < attach.until, and for frame plates AFR / ANT everywhere). time (Ma) -> [lon, lat, twist]
export const KEYFRAMES = {
  AFR: [[0, [20, 5, 0]], [30, [19, 3, 1]], [66, [17, -2, 3]], [120, [13, -9, 8]], [180, [8, -16, 12]], [250, [4, -18, 16]], [300, [2, -26, 18]], [360, [0, -35, 22]], [420, [-5, -45, 25]], [480, [-8, -50, 28]], [540, [-10, -50, 30]], [900, [20, -40, 40]], [1600, [60, -25, 55]], [2500, [120, -10, 70]], [4600, [-150, 5, 100]]],
  ANT: [[0, [0, -80, 0]], [66, [5, -80, 0]], [120, [15, -78, 0]], [180, [25, -76, 0]], [250, [35, -74, 0]], [300, [40, -72, 0]], [360, [50, -68, 0]], [420, [60, -62, 0]], [480, [70, -55, 0]], [540, [80, -50, 0]], [900, [90, -35, 0]], [1600, [110, -20, 0]], [2500, [140, -5, 0]], [4600, [-120, 10, 0]]],
  NAM: [[0, [-100, 45, 0]], [20, [-96, 46, 2]], [50, [-90, 46, 4]], [66, [-86, 46, 5]], [90, [-78, 45, 7]], [120, [-70, 42, 10]], [150, [-62, 38, 14]]],
  SAM: [[0, [-60, -15, 0]], [20, [-57, -15, 1]], [50, [-51, -17, 3]], [66, [-46, -19, 4]], [90, [-38, -22, 6]]],
  EUR: [[0, [80, 55, 0]], [20, [80, 55, 0]], [40, [79, 53, -1]]],
  AUS: [[0, [135, -25, 0]], [20, [132, -32, 2]], [35, [130, -42, 4]]],
  IND: [[0, [78, 22, 0]], [20, [77, 17, 3]], [50, [72, 3, 10]], [66, [68, -10, 15]], [90, [62, -27, 22]], [120, [55, -40, 28]]],
  MAD: [[0, [47, -19, 0]], [66, [47, -22, 0]], [120, [45, -26, 3]]],
  ARA: [[0, [45, 23, 0]], [15, [44, 21, 2]]],
};

export function lonLatToVec3(lon, lat, target = new THREE.Vector3()) {
  const phi = (90 - lat) * Math.PI / 180, theta = (lon + 180) * Math.PI / 180;
  return target.set(-Math.cos(theta) * Math.sin(phi), Math.cos(phi), Math.sin(theta) * Math.sin(phi));
}

const _v0 = new THREE.Vector3(), _v1 = new THREE.Vector3();

/** Quaternion moving `ref` to (lon,lat) then twisting about the new position. */
function keyQuaternion(ref, lon, lat, twist) {
  lonLatToVec3(ref[0], ref[1], _v0);
  lonLatToVec3(lon, lat, _v1);
  const q = new THREE.Quaternion().setFromUnitVectors(_v0, _v1);
  const qt = new THREE.Quaternion().setFromAxisAngle(_v1, twist * Math.PI / 180);
  return qt.multiply(q);
}

// precompute own keyframe quaternions & attach offsets
const KEYQ = {};
const OFFSETQ = {};
for (const [plate, info] of Object.entries(PLATE_INFO)) {
  KEYQ[plate] = KEYFRAMES[plate].map(([t, k]) => ({ t, q: keyQuaternion(info.ref, k[0], k[1], k[2]) }));
  if (info.attach) {
    const [dlon, dlat, tw] = info.attach.offset;
    OFFSETQ[plate] = keyQuaternion(info.ref, info.ref[0] + dlon, info.ref[1] + dlat, tw);
  }
}

const _qa = new THREE.Quaternion(), _qb = new THREE.Quaternion(), _qp = new THREE.Quaternion();

function ease(f) { return f * f * (3 - 2 * f); }

/** Fill target quaternion for plate at time tMa. */
export function plateQuaternion(plate, tMa, target) {
  const info = PLATE_INFO[plate];
  const keys = KEYQ[plate];
  if (info.attach && tMa >= info.attach.until) {
    // ride with the parent, offset by the pre-rift position
    plateQuaternion(info.attach.parent, tMa, _qp);
    return target.copy(_qp).multiply(OFFSETQ[plate]);
  }
  if (tMa <= keys[0].t) return target.copy(keys[0].q);
  const last = keys[keys.length - 1];
  if (!info.attach && tMa >= last.t) return target.copy(last.q);
  if (info.attach && tMa >= last.t) {
    // interpolate between last own key and the attached pose at `until`
    plateQuaternion(info.attach.parent, info.attach.until, _qp);
    _qb.copy(_qp).multiply(OFFSETQ[plate]);
    const f = (tMa - last.t) / (info.attach.until - last.t);
    return target.copy(last.q).slerp(_qb, ease(f));
  }
  let i = 0;
  while (keys[i + 1].t < tMa) i++;
  const a = keys[i], b = keys[i + 1];
  const f = (tMa - a.t) / (b.t - a.t);
  return target.copy(a.q).slerp(b.q, ease(f));
}
