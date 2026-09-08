// Minimal dependency-free PNG encoder (8-bit or 16-bit, gray/gray+alpha/rgb/rgba).
import zlib from 'node:zlib';

const CRC_TABLE = new Int32Array(256);
for (let n = 0; n < 256; n++) {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  CRC_TABLE[n] = c;
}
function crc32(buf) {
  let c = -1;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, 'ascii');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([len, typeBuf, data, crc]);
}

/**
 * Encode a PNG.
 * @param {number} width
 * @param {number} height
 * @param {number} channels 1 (gray), 2 (gray+alpha), 3 (rgb), 4 (rgba)
 * @param {Uint8Array|Uint16Array} data interleaved samples, row-major
 * @param {number} bitDepth 8 or 16
 */
export function encodePNG(width, height, channels, data, bitDepth = 8) {
  const colorType = { 1: 0, 2: 4, 3: 2, 4: 6 }[channels];
  if (colorType === undefined) throw new Error('bad channels');
  const bytesPerSample = bitDepth / 8;
  const rowBytes = width * channels * bytesPerSample;
  const raw = Buffer.alloc((rowBytes + 1) * height);
  let src = 0;
  for (let y = 0; y < height; y++) {
    let o = y * (rowBytes + 1);
    raw[o++] = 0; // filter: none
    if (bitDepth === 8) {
      raw.set(data.subarray(src, src + width * channels), o);
      src += width * channels;
    } else {
      for (let i = 0; i < width * channels; i++) {
        const v = data[src++];
        raw[o++] = v >> 8;
        raw[o++] = v & 0xff;
      }
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = bitDepth;
  ihdr[9] = colorType;
  ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const idat = zlib.deflateSync(raw, { level: 6 });
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', idat),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

/** Float field (0..1) -> 8-bit gray PNG */
export function floatToGray8(field) {
  const out = new Uint8Array(field.length);
  for (let i = 0; i < field.length; i++) {
    const v = field[i];
    out[i] = v <= 0 ? 0 : v >= 1 ? 255 : Math.round(v * 255);
  }
  return out;
}
