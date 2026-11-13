# -*- coding: utf-8 -*-
"""压缩「地球纪元」主应用的贴图（public/textures）。GitHub Pages 在国内只有每秒几十 KB，体积就是加载时间。

做两件事：

1. 数据贴图 PNG → 无损 WebP（像素逐一相同，体积约一半）
     earth_height.png / earth_masks_a.png / earth_masks_b.png → 同名 .webp
     earth_masks_b 的蓝色通道（粗糙度）着色器没有用到，置零后又省三分之一。
     高度和遮罩是「数据」不是「图片」：有损压缩会让三个通道互相串色、让海岸线挪位置，所以只用无损。

2. 生成「首屏版」小图。应用先下这一套就出画面，原尺寸在后台补上（见 src/earth/textures.js）。
   开场镜头里地球直径约 600 像素，4K 贴图本来就被显卡缩到 2K 那一级 mipmap 去采样，
   所以首屏版就是原图的下一级 mipmap（2×2 平均，颜色图在线性光下平均），整体观感不变。
     earth_color_2k / earth_normal_2k / earth_clouds_2k           有损
     earth_height_2k                                              无损
     earth_masks_a_1k / earth_masks_b_1k                          无损
     nasa_color_2k / nasa_lights_2k / nasa_clouds_2k              有损（卫星影像，近 3000 万年才用到）
     moon_color_512 / moon_normal_1k                              有损（默认视角里月球只有几个像素）

转换后删除 PNG 原文件（可由 npm run blender 重新烘焙，git 历史里也有）。
重新烘焙或重新处理 NASA 影像之后要再跑一遍：npm run web:optimize
用法：python tools/optimize_earth_textures.py [--keep] [--only 名字片段]
"""
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
TEX = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "textures"))
KEEP = "--keep" in sys.argv
ONLY = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
LOSSLESS = dict(lossless=True, quality=100, method=6)


def kb(p):
    return os.path.getsize(p) / 1024


def load(name):
    return np.asarray(Image.open(os.path.join(TEX, name)))


def save(name, arr, **opts):
    path = os.path.join(TEX, name)
    Image.fromarray(arr).save(path, "WEBP", **opts)
    return kb(path)


def box2(a):
    """2×2 平均 = 显卡生成的下一级 mipmap。"""
    h, w = a.shape[:2]
    s = a.astype(np.uint16).reshape(h // 2, 2, w // 2, 2, -1).sum(axis=(1, 3))
    return ((s + 2) // 4).astype(np.uint8).reshape(h // 2, w // 2, *a.shape[2:])


def box2_srgb(a):
    """颜色图在线性光下平均（sRGB 贴图的 mipmap 也是这样生成的），否则亮点会变暗。"""
    x = a.astype(np.float32) / 255.0
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    h, w = lin.shape[:2]
    lin = lin.reshape(h // 2, 2, w // 2, 2, -1).mean(axis=(1, 3))
    out = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8).reshape(h // 2, w // 2, *a.shape[2:])


def shrink(a, times, srgb=False):
    for _ in range(times):
        a = box2_srgb(a) if srgb else box2(a)
    return a


def gray(a):
    return a[..., 0] if a.ndim == 3 else a


def want(name):
    return ONLY is None or ONLY in name


def report(name, size, note=""):
    print(f"  {name:28s} {size:7.0f} KB  {note}")


def main():
    print("1) 数据贴图 → 无损 WebP")
    for stem, zero_blue in (("earth_height", False), ("earth_masks_a", False), ("earth_masks_b", True)):
        png = os.path.join(TEX, stem + ".png")
        if not os.path.exists(png) or not want(stem):
            continue
        a = np.asarray(Image.open(png)).copy()
        if zero_blue:
            a[..., 2] = 0          # 粗糙度通道：着色器不采样
        before = kb(png)
        size = save(stem + ".webp", a, **LOSSLESS)
        back = load(stem + ".webp")
        back = back[..., 0] if a.ndim == 2 else back
        assert np.array_equal(back, a), stem + ": 无损校验失败"
        report(stem + ".webp", size, f"（PNG {before:.0f} KB，解码后逐像素相同）")
        if not KEEP:
            os.remove(png)

    print("2) 首屏版")
    # (输出名, 原图, 缩小几次, 处理, 编码参数)
    jobs = [
        ("earth_color_2k.webp", "earth_color.webp", 1, "srgb", dict(quality=90, method=6)),
        ("earth_normal_2k.webp", "earth_normal.webp", 1, "data", dict(quality=90, method=6)),
        ("earth_clouds_2k.webp", "earth_clouds.webp", 1, "gray", dict(quality=82, method=6)),
        ("earth_height_2k.webp", "earth_height.webp", 1, "gray", LOSSLESS),
        ("earth_masks_a_1k.webp", "earth_masks_a.webp", 2, "data", LOSSLESS),
        ("earth_masks_b_1k.webp", "earth_masks_b.webp", 2, "data", LOSSLESS),
        ("nasa_color_2k.webp", "nasa_color_4k.webp", 1, "srgb", dict(quality=88, method=6)),
        ("nasa_lights_2k.webp", "nasa_lights_4k.webp", 1, "srgb", dict(quality=85, method=6)),
        ("nasa_clouds_2k.webp", "nasa_clouds_4k.webp", 1, "gray", dict(quality=80, method=6)),
        ("moon_color_512.webp", "moon_color.webp", 2, "srgb", dict(quality=90, method=6)),
        ("moon_normal_1k.webp", "moon_normal.webp", 1, "data", dict(quality=88, method=6)),
    ]
    total = 0
    for out, src, times, kind, opts in jobs:
        if not want(out):
            continue
        if not os.path.exists(os.path.join(TEX, src)):
            print(f"  跳过 {out}：缺少 {src}")
            continue
        a = load(src)
        if kind == "gray":
            a = gray(a)
        a = shrink(a, times, srgb=(kind == "srgb"))
        size = save(out, a, **opts)
        total += size
        report(out, size, f"← {src} {kb(os.path.join(TEX, src)):.0f} KB，{a.shape[1]}×{a.shape[0]}")
    print(f"  首屏版合计 {total:.0f} KB")


if __name__ == "__main__":
    main()
