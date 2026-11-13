# -*- coding: utf-8 -*-
"""扫描渲染图里的黑块：两个面完全共面时会互相遮光，渲染成一小块纯黑。出成图后跑一遍，再人工看标出的位置
（树干、石缝、屋檐下的深影也会被标出，那些是正常的）。用法：python tools/black_scan.py <png> [...]"""
import sys
import numpy as np
from PIL import Image

for path in sys.argv[1:]:
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int32)
    dark = a.max(axis=2) <= 32
    h, w = dark.shape
    cell = 10
    hits = []
    for y in range(0, h - cell, cell):
        row = dark[y:y + cell]
        for x in range(0, w - cell, cell):
            n = int(row[:, x:x + cell].sum())
            if n >= cell * cell * 0.7:
                hits.append((x, y, n))
    print(f"{path}: size {w}x{h}, dark pixels {int(dark.sum())}, suspicious cells {len(hits)}")
    for (x, y, n) in hits[:25]:
        print(f"   cell at ({x},{y})  black {n}/{cell * cell}")
