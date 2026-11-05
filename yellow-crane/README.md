# 武汉黄鹤楼微缩立体模型（Yellow Crane Tower diorama）

第三座沙盘子项目，与故宫、西湖同一套管线（`west-lake/` 的脚本派生）：Blender 5.x 过程化生成，Cycles 渲染成图，
并以 `--export-glb` 导出 Three.js 网页版（`dioramas/yellow-crane/`）。

内容：蛇山台地上的黄鹤楼（三层石台、五层平座朱栏、每面三翘角的黄色琉璃瓦飞檐、攒尖宝顶）、
公园的牌坊、碑廊、亭台、白云阁、鹅池与山径，斜贯沙盘的长江与江滩滨江路，武汉长江大桥（双层钢桁架、石墩、
桥头堡与引桥），对岸龟山、电视塔与晴川阁，两岸粉墙黛瓦的老城，江上货驳、游轮与小船，
Poly Haven 扫描树木实例化的松林与垂柳，日落纯天空 HDRI 的金色低角度阳光与贴水薄雾。

## 目录

| 路径 | 内容 |
|---|---|
| `build_yellow_crane.py` | 唯一的脚本：地形、建模、材质、灯光、相机、雾、渲染、网页导出 |
| `../assets/textures_cc0/`、`../assets/polyhaven/` | CC0 贴图、树木模型与 HDRI（后者不入库，见其 README） |
| `output/yellow_crane/yellow_crane.png` | 正式成图（2048×1792，64 spp） |
| `output/yellow_crane/yellow_crane.blend` | 工程文件（不入库） |

## 运行

```bash
npm run blender:crane            # 正式渲染（约 20 分钟）
npm run blender:crane:preview    # 快速预览（40%，16 spp）
npm run blender:crane:web        # 导出网页版 glb + scene.json
```

直接调用脚本的参数：`--pct`、`--samples`、`--out`、`--save`、`--nomist`、`--nohdri`、`--sunonly`、
`--border x0 y0 x1 y1`、`--export-glb <dir>`。坐标：1 个 Blender 单位 ≈ 12 米，y 轴正方向为北，江面 z = 0。
