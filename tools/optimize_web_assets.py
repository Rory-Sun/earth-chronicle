# -*- coding: utf-8 -*-
"""压缩沙盘网页版的静态资源（GitHub Pages 在国内只有每秒几十 KB，体积就是加载时间）。

  贴图  public/dioramas/textures/*.jpg  → .webp（有损，缩到 512 px：最近视角下一块贴图也只占几十个屏幕像素）
  卡片树 public/dioramas/trees/*.png     → .webp（有损 + 透明通道，缩到一半：正视 256×512、俯视 256×256）
  天空图 public/dioramas/env/*_1k.hdr    → *_512.hdr（2×2 平均缩小，Radiance RGBE）

转换后删除原文件（原图可由 ambientCG / Poly Haven 重新下载，卡片树可由 tools/diorama_impostors.py 重新渲染）。
用法：python tools/optimize_web_assets.py [--keep]     # --keep 保留原文件
"""
import glob
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "dioramas"))
KEEP = "--keep" in sys.argv


def kb(p):
    return os.path.getsize(p) / 1024


def to_webp(src, size=None, **opts):
    dst = os.path.splitext(src)[0] + ".webp"
    im = Image.open(src)
    if size and im.size != size:
        if im.mode == "RGBA":                                  # 预乘透明度再缩放，避免透明边缘发黑
            im = im.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
        else:
            im = im.resize(size, Image.LANCZOS)
    im.save(dst, "WEBP", method=6, **opts)
    a, b = kb(src), kb(dst)
    if not KEEP:
        os.remove(src)
    return a, b


def read_hdr(path):
    """读 Radiance .hdr（-Y H +X W，新式 RLE 或平铺），返回 float32 (H, W, 3)。"""
    data = open(path, "rb").read()
    pos = data.index(b"\n\n") + 2
    end = data.index(b"\n", pos)
    parts = data[pos:end].split()
    assert parts[0] == b"-Y" and parts[2] == b"+X", parts
    h, w = int(parts[1]), int(parts[3])
    pos = end + 1
    rgbe = np.zeros((h, w, 4), np.uint8)
    buf = memoryview(data)
    if 8 <= w <= 0x7FFF and data[pos] == 2 and data[pos + 1] == 2 and not (data[pos + 2] & 0x80):
        for y in range(h):
            assert data[pos] == 2 and data[pos + 1] == 2 and ((data[pos + 2] << 8) | data[pos + 3]) == w
            pos += 4
            for c in range(4):
                x = 0
                row = rgbe[y, :, c]
                while x < w:
                    n = data[pos]; pos += 1
                    if n > 128:
                        n -= 128
                        row[x:x + n] = data[pos]; pos += 1
                    else:
                        row[x:x + n] = np.frombuffer(buf[pos:pos + n], np.uint8); pos += n
                    x += n
    else:
        rgbe = np.frombuffer(buf[pos:pos + h * w * 4], np.uint8).reshape(h, w, 4).copy()
    e = rgbe[..., 3].astype(np.int32)
    scale = np.where(e > 0, np.ldexp(1.0, e - 136), 0.0).astype(np.float32)
    return rgbe[..., :3].astype(np.float32) * scale[..., None]


def write_hdr(path, img):
    """写平铺（不做 RLE）的 Radiance .hdr；three.js 的 HDRLoader / RGBELoader 能读。"""
    h, w, _ = img.shape
    m = np.maximum(img.max(axis=2), 1e-32)
    e = np.ceil(np.log2(m)).astype(np.int32)
    e = np.where(np.ldexp(1.0, e) <= m, e + 1, e)              # 保证 尾数 < 256
    scale = np.ldexp(1.0, 8 - e).astype(np.float32)
    rgb = np.clip(np.floor(img * scale[..., None]), 0, 255).astype(np.uint8)
    out = np.dstack([rgb, np.clip(e + 128, 0, 255).astype(np.uint8)])
    out[img.max(axis=2) < 1e-30] = 0
    for y in range(h):                                          # 行首 (2,2,<128) 会被误判成 RLE：把首像素的 R 挪一档
        if out[y, 0, 0] == 2 and out[y, 0, 1] == 2 and out[y, 0, 2] < 128:
            out[y, 0, 0] = 3
    with open(path, "wb") as f:
        f.write(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n" + f"-Y {h} +X {w}\n".encode())
        f.write(out.tobytes())


tot_a = tot_b = 0.0
for src in sorted(glob.glob(os.path.join(ROOT, "textures", "*.jpg"))):
    name = os.path.basename(src)
    q = 84 if "NormalGL" in name else (72 if "Roughness" in name else 80)
    a, b = to_webp(src, size=(512, 512), quality=q)
    tot_a += a; tot_b += b
    print(f"{name:34s} {a:7.0f} KB -> {b:6.0f} KB")
for src in sorted(glob.glob(os.path.join(ROOT, "trees", "*.png"))):
    w0, h0 = Image.open(src).size
    if src.endswith("_bb.png"):          # 多角度公告牌图集：小图已按用途定好尺寸，不再缩小
        a, b = to_webp(src, quality=80, alpha_quality=88, exact=True)
    else:
        a, b = to_webp(src, size=(w0 // 2, h0 // 2), quality=84, alpha_quality=92, exact=True)
    tot_a += a; tot_b += b
    print(f"{os.path.basename(src):34s} {a:7.0f} KB -> {b:6.0f} KB")
for src in sorted(glob.glob(os.path.join(ROOT, "env", "*_1k.hdr"))):
    img = read_hdr(src)
    h, w, _ = img.shape
    small = img.reshape(h // 2, 2, w // 2, 2, 3).mean(axis=(1, 3))
    dst = src.replace("_1k.hdr", "_512.hdr")
    write_hdr(dst, small)
    back = read_hdr(dst)
    assert back.shape == small.shape and float(np.abs(back - small).max() / max(small.max(), 1e-6)) < 0.01
    a, b = kb(src), kb(dst)
    tot_a += a; tot_b += b
    if not KEEP:
        os.remove(src)
    print(f"{os.path.basename(src):34s} {a:7.0f} KB -> {b:6.0f} KB   max {small.max():.1f}")
print(f"total {tot_a / 1024:.1f} MB -> {tot_b / 1024:.1f} MB")
