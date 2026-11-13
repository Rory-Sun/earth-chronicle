# 地球纪元 · Earth Chronicle

## 线上地址

| 站点 | 地址 |
|---|---|
| 地球纪元 | https://rory-sun.github.io/earth-chronicle/ |
| 资料来源与科学说明 | https://rory-sun.github.io/earth-chronicle/sources/ |
| 故宫微缩沙盘（3D 可旋转） | https://rory-sun.github.io/earth-chronicle/dioramas/forbidden-city/ |
| 西湖微缩沙盘（3D 可旋转） | https://rory-sun.github.io/earth-chronicle/dioramas/west-lake/ |
| 黄鹤楼微缩沙盘（3D 可旋转） | https://rory-sun.github.io/earth-chronicle/dioramas/yellow-crane/ |
| 苏州园林微缩沙盘（3D 可旋转） | https://rory-sun.github.io/earth-chronicle/dioramas/suzhou-garden/ |
| 个人主页（独立仓库 `Rory-Sun/Rory-Sun.github.io`） | https://rory-sun.github.io/ |

推送到 `main` 后由 GitHub Actions 自动构建并发布到 GitHub Pages（项目站点，子路径 `/earth-chronicle/`）。

一个完全离线运行的交互式三维地球平台：46 亿年的行星演化（大陆漂移、雪球地球、大氧化事件、恐龙灭绝……）与 30 万年的人类迁徙，全部在一个可自由旋转、缩放的逼真地球上呈现。

- **零 API**：没有任何在线服务、地图瓦片或外部字体。海岸线来自随包附带的 Natural Earth（`world-atlas`）数据，其余一切程序化生成。
- **Blender 建模与烘焙**：地球/月球的高模、地形、生物群系、云层、城市夜灯全部由 Blender（Cycles 节点材质）程序化生成并烘焙成贴图，导出 `.glb` 与 `.blend`，可直接在 Blender 中打开旋转查看。
- **Three.js 实时渲染**：自定义着色器实现海平面升降、冰盖进退、植被出现、岩浆地表、大气散射、云影、海面高光、夜灯，以及按板块拆分的大陆漂移。

## 数据与影像来源

- 现代地球（约 800 万年内）使用 NASA Visible Earth 公有领域影像：Blue Marble Next Generation（2004 年 8 月，含地形与海底）、Black Marble 2016 夜间灯光、Blue Marble 云图。原始文件在 `blender/nasa_src/`（不随网页发布）（21600×10800 原图与 8K 云图 TIFF 体积过大未入库，可从 NASA Visible Earth 重新下载），`blender/process_nasa.py` 将其转换为 4K/8K WebP。
- 更早时代的地表、云层与夜灯由 Blender 程序化生成并烘焙；海岸线来自 Natural Earth（world-atlas）。
- 所有资源随包附带，运行时不访问任何在线服务。

## 导览模式

加载完成后会出现欢迎卡片：「开始导览」进入 21 个章节的自动导览（三幕：行星的诞生 / 大陆的舞蹈 / 人类的旅程），每章自动飞行镜头、扫描时间轴并推进；`←` `→` 切换章节，空格暂停，`Esc` 退出，「沉浸模式」隐藏全部界面。章节数据在 `src/data/tour.js`（模式、时间区间、镜头经纬度与距离、文案），控制器在 `src/app/Tour.js`。URL 参数：`?tour=N` 直接从第 N 章开始，`?notour` 跳过欢迎卡片。

## 月球模式

顶栏第四个模式「月球」把轨道中心切到月球：同一条时间轴驱动月球的岩浆洋（45.1 亿年前）、撞击坑累积、月海玄武岩填充（38–31 亿年前）与真实经纬度的着陆点（阿波罗、月球号、嫦娥）。导览第四幕「月球的故事」共 4 章。数据与文案在 `src/data/moon.js`，月球着色器的时间参数通过 `onBeforeCompile` 注入（`src/earth/Sky.js`）。`?mode=moon` 可直接进入。

## 生命之树

顶栏第五个模式「生命之树」在地球上方展开一棵可缩放、可拖动的演化树（SVG），横轴与底部时间轴共用同一套非线性刻度：拖动时间，谱系随之生长；内部谱系的小字标在起源点，末端谱系带图标跟随时间光标；灭绝支系虚线并标 †。点击任一谱系弹出简介（起源/灭绝年代、所属支系链）并可一键跳到其起源或灭绝时刻。约 90 个谱系的数据在 `src/data/life.js`，组件在 `src/ui/LifeTree.js`。`?mode=life` 可直接进入。

## 地月尺度

月球大小与地月距离默认为真实比例（月球半径 0.2727 地球半径；今天距离 60.3 个地球半径），远景时两颗天体带有标注与距离。在应用「显示设置」中取消「真实地月距离」可切换到压缩模式（今天约 9 个地球半径）以便同框观看。

## 页面

- `/`（构建后为 `/earth-chronicle/`）地球纪元应用本体（`index.html` + `src/`）。
- `/sources/` 资料来源与科学说明。
- 个人主页已拆分到独立仓库 `Rory-Sun/Rory-Sun.github.io`，通过 iframe 嵌入本应用（`?embed=1`）。

## 目录结构

```
tools/            Node 数据流水线：海岸线栅格化、地形/气候提示图、板块区域多边形
  build-data.mjs  → blender/input/*.png, src/data/regions.json
  optimize_earth_textures.py  贴图转无损 WebP、生成首屏用的小图（npm run web:optimize）
  geo/features.mjs 手工编码的山脉、沙漠、雨林、冰盖、湖泊、城市、陆架、板块划分
blender/
  build_earth.py  Blender 无头脚本：程序化材质 → 烘焙贴图 → 月球 → 场景 → glb/blend/渲染
  input/          由 tools 生成的提示图
  output/         earth_chronicle.blend、高度图、预览 PNG
  renders/        Cycles 预览渲染
public/
  textures/       烘焙贴图（颜色、法线、高度、遮罩、夜灯、云层、月球），每张有原尺寸和首屏用的小图
  models/         Blender 导出的 earth.glb / moon.glb（网页不加载：月球在网页里就是一个代码生成的球体）
src/
  app/            App.js（渲染循环、模式、UI 绑定）、Environment.js（时间 → 环境参数关键帧）
  earth/          Earth.js（地球装配）、shaders.js（GLSL）、Plates.js（板块运动模型）、Sky.js、Migration.js、
                  textures.js（贴图分级加载）、regionMesh.js（启动时由多边形生成板块网格）
  data/           eras.js（地质年代与事件文案）、migration.js（迁徙路线、遗址、人口）、regions.json（板块多边形）
  ui/             Timeline、InfoPanel、Labels、MiniMap（古地理小地图）
```

## 运行

```bash
npm install
npm run dev        # http://127.0.0.1:5173
npm run build      # 产物在 dist/，任何静态服务器即可托管
```

## 重新生成资产（可选）

需要本机安装 Blender（脚本默认路径 `D:/install/blender/blender.exe`，可在 `package.json` 中修改）。

```bash
npm run data                      # 生成提示图与板块多边形（约 30 秒）
npm run blender -- --res 4096     # 烘焙 4K 贴图 + 导出 glb/blend + 预览渲染（CPU 约 10-25 分钟）
npm run blender -- --res 8192 --skip-render   # 8K 版本
npm run blender -- --res 2048 --only albedo,clouds  # 快速预览单张贴图
npm run web:optimize              # 烘焙或处理 NASA 影像之后必跑：数据贴图转无损 WebP，生成首屏小图
```

## 加载：先出画面，再补清晰度

网页资源体积就是加载时间（国内访问 GitHub Pages 只有每秒几十 KB），所以首屏只下载开场画面用得到的东西，约 1.2 MB：

- 每张贴图分两级。**首屏小图**（2K，遮罩 1K）由 `tools/optimize_earth_textures.py` 从原图生成：开场镜头里地球直径约 600 像素，
  4K 贴图本来就是从 2K 那一级 mipmap 采样的，画面看不出差别。**原尺寸**（4K）在画面出来之后后台下载、逐张替换。
- 卫星影像（NASA，近 3000 万年才用到）和月球的起伏贴图不在首屏里；用户切到「人类 / 现在 / 月球」或拉近镜头时，
  对应的贴图会插队先下。直接用 `?mode=now`、`?mode=moon` 打开时，它们才算进首屏。
- 高度和遮罩是数据不是图片，只用无损 WebP（比 PNG 小一半，解码后逐像素相同）。
- 板块网格由 `src/data/regions.json` 里的多边形在启动时生成（约 0.3 秒），不再下载 2.6 MB 的二进制文件。
- 着色器在下载贴图的同时编译，不再等贴图下完才卡住页面去编译。
- 地表着色器的噪声函数是按编译时间写的（8 个角点的哈希合并成两个 vec4、四个倍频直接写开）：Windows 上 Chrome 把着色器交给
  D3D 编译器，原来的写法首次访问要编译 9–17 秒，现在约 2 秒，帧率不变。改噪声函数前先看 `src/earth/shaders.js` 开头的说明。

地址参数：`?lq` 只用首屏小图；`?hq=1` 见下；嵌入模式（`?embed=1`）只在拉近或进入月球模式时才下载原尺寸贴图。

## 8K 贴图

运行过 `--res 8192` 烘焙后会生成 `earth_color_8k.webp` 与 `earth_normal_8k.webp`，在地址后加 `?hq=1` 即可加载 8K 版本（需显卡支持 8192 纹理）。默认使用 4K，以兼顾集成显卡。
NASA 的 8K 卫星底图（3 MB）在桌面浏览器上自动使用，但只在画面切到卫星影像之后才开始下载。

## 操作

- 拖动旋转、滚轮缩放、双击聚焦；空格播放/暂停时间轴，←/→ 微调。
- 三种模式：**地球演化**（含古地理小地图）、**人类迁徙**（路线动画、遗址标注、人口统计）、**今日地球**。
- 右上角设置可开关云层、大气、夜灯、泛光、自动旋转与标注。

## 说明

板块运动、古气候与迁徙时间均为面向可视化的近似复原，参考了通行的古地理图与考古/遗传学共识，不作为科学数据使用。

## 部署

### GitHub Pages（当前线上方式）

推送到 `main` 后 `.github/workflows/deploy.yml` 自动执行 `npm run build` 并发布 `dist/` 到 https://rory-sun.github.io/earth-chronicle/ 。`vite.config.js` 的 `base` 默认即为 `/earth-chronicle/`。

### 自有服务器

这是纯静态前端项目，没有后端和数据库。`npm run build` 生成的 `dist/`（约 40 MB）上传到任意静态服务器即可：

```bash
npm run build
scp -r dist/* root@你的服务器IP:/var/www/earth-chronicle/
```

- Nginx 配置样例见 `deploy/nginx.conf`（含缓存、gzip 与 glb/webp 的 MIME 类型）。腾讯云 COS 的「静态网站托管」+ CDN 也可以直接使用，把 `dist/` 上传到存储桶根目录即可。
- 构建时通过环境变量指定部署路径：部署到域名根目录用 `VITE_BASE=/ npm run build`（PowerShell：`$env:VITE_BASE='/'; npm run build`），默认为 GitHub Pages 的 `/earth-chronicle/`。
- 不需要 HTTPS 也能运行（未使用任何需要安全上下文的浏览器 API），但建议配置证书；腾讯云可用免费的 TrustAsia 证书。

## 微缩沙盘（故宫 / 西湖 / 黄鹤楼 / 苏州园林）

四座用 Blender 过程化生成的微缩沙盘，各有一张 Cycles 成品图（`forbidden-city/`、`west-lake/`、`yellow-crane/`、`suzhou-garden/`）和一个可自由旋转、缩放的
Three.js 网页版（`dioramas/`）。网页版由同一套 Blender 脚本以 `--export-glb` 导出（`tools/diorama_export.py`：盒式 UV、
按高度烘焙顶点色、材质清理、Draco 压缩），贴图按材质名在网页里映射回 CC0 素材；西湖的八千多棵树在网页里是预渲染的
"卡片树"（`tools/diorama_impostors.py`），湖面为实时反射，天光来自 HDRI，并按帧率自动调节画质。

```bash
npm run blender:trees:web      # 渲染卡片树贴图 → public/dioramas/trees/（需 assets/polyhaven 素材）
npm run blender:palace:web     # 导出故宫 → public/dioramas/forbidden-city/
npm run blender:westlake:web   # 导出西湖 → public/dioramas/west-lake/
npm run blender:crane:web      # 导出黄鹤楼 → public/dioramas/yellow-crane/
npm run blender:suzhou:web     # 导出苏州园林 → public/dioramas/suzhou-garden/
npm run web:optimize           # 压缩共用资源：贴图与卡片树转 WebP 并缩小，天空图缩到 512 px
```

沙盘共用的贴图、卡片树、天空图由 `tools/optimize_web_assets.py` 压缩，合计约 2 MB；重新下载贴图或重新渲染卡片树后要再跑一次
（`npm run web:optimize` 会连同地球贴图一起处理）。
网页导出（`--export-glb`）会把地形网格放粗一档、把花和山岩的小球降到最低面数，`scene.json` 紧凑输出。
