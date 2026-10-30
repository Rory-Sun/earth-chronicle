# 故宫微缩沙盘（Forbidden City diorama）

独立于主项目（地球编年史 / Earth Chronicle）的子项目：用 Blender 5.x 过程化生成一座
45° 俯视的故宫微缩模型（悬浮地层岛屿、琉璃瓦、朱墙、汉白玉台基、景山、筒子河），
Cycles 渲染成图。

## 目录

| 路径 | 内容 |
|---|---|
| `build_forbidden_city.py` | 唯一的脚本：建模、材质、灯光、相机、渲染 |
| `../assets/textures_cc0/` | ambientCG 的 CC0 贴图，各沙盘共用（来源见其中 `README.md`，`_dl/` 下载缓存不入库） |
| `output/forbidden_city/forbidden_city.png` | 正式成图（2048×1792，128 spp） |
| `output/forbidden_city/forbidden_city.blend` | 工程文件（不入库） |

## 运行

在仓库根目录执行：

```bash
npm run blender:palace
```

快速预览（40% 分辨率，16 spp）：

```bash
npm run blender:palace:preview
```

直接调用脚本可用的参数：`--pct`、`--samples`、`--out`、`--save`、
`--sunonly`、`--nosun`、`--border x0 y0 x1 y1`（裁剪渲染，用于 100% 检查局部）。

CPU 渲染一张正式图约 15–17 分钟。
