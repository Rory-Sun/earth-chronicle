# 杭州西湖微缩立体景观（West Lake diorama）

独立于主项目（地球编年史 / Earth Chronicle）和故宫沙盘的子项目：用 Blender 5.x 过程化生成
一座 45° 俯视的西湖微缩模型，Cycles 渲染成图。

内容：悬浮地层岛屿上的湖泊高度场（湖床随离岸距离变深）、透射湖水与多层波纹、
苏堤六桥与白堤（锦带桥、断桥）、西泠桥、孤山（楼外楼、平湖秋月、西泠印社）、
小瀛洲（三潭印月、九曲桥）、湖心亭、阮公墩、雷峰塔（夕照山）、保俶塔（宝石山）、
净慈寺（黄墙）、岳王庙（红墙）、曲院风荷荷叶、集贤亭、柳浪闻莺、湖滨步道与城里的粉墙黛瓦、
画舫与小船、堤岸桃柳相间、层叠青绿群山上的实例化针叶林，以及贴水薄雾与远景空气透视。
树木与灌木是 Poly Haven 的扫描模型（叶片材质在脚本里重建并染色），天光与倒影来自 HDRI。

## 目录

| 路径 | 内容 |
|---|---|
| `build_west_lake.py` | 唯一的脚本：地形、建模、材质、灯光、相机、雾、渲染 |
| `../assets/textures_cc0/` | ambientCG 的 CC0 贴图，与故宫沙盘共用（来源见其中 `README.md`） |
| `../assets/polyhaven/` | Poly Haven 的 CC0 树木/灌木模型与日出 HDRI（不入库，下载方法见其中 `README.md`） |
| `output/west_lake/west_lake.png` | 正式成图（2048×1792，128 spp） |
| `output/west_lake/west_lake.blend` | 工程文件（不入库） |

## 运行

在仓库根目录执行：

```bash
npm run blender:westlake
```

快速预览（40% 分辨率，16 spp）：

```bash
npm run blender:westlake:preview
```

直接调用脚本可用的参数：`--pct`、`--samples`、`--out`、`--save`、`--nomist`（关闭雾）、`--nohdri`、
`--sunonly`、`--border x0 y0 x1 y1`（裁剪渲染，用于 100% 检查局部）。

坐标：1 个 Blender 单位 ≈ 25 米，y 轴正方向为北，湖面 z = 0。