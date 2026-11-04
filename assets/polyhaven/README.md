# Poly Haven 素材（CC0）

本目录的模型与 HDRI 均来自 https://polyhaven.com ，授权 CC0 1.0（公有领域，可自由使用）。
文件体积大（约 300 MB），不入 git；按下面的方式重新下载即可。

## 清单

| 用途 | 素材 ID | 类型 | 本脚本使用的物体 |
| --- | --- | --- | --- |
| 阔叶树 | island_tree_01 / island_tree_02 / island_tree_03 | models | `<id>_LOD1` |
| 垂柳、桃树（叶片染色） | tree_small_02 | models | `tree_small_02_LOD1` |
| 山上针叶林 | fir_sapling_medium | models | `fir_sapling_medium_{a,b,c}_LOD1` |
| 灌木 | shrub_01 / shrub_03 | models | `shrub_01_{a,b}_LOD1`、`shrub_03_{a,b}_LOD1` |
| 日出天空 | kloppenheim_06_puresky | hdris | 2k `.hdr` |

目录结构：`models/<id>/<id>.blend` + `models/<id>/textures/...`（1k 贴图），`hdris/kloppenheim_06_puresky_2k.hdr`。

## 下载

Poly Haven 的公开接口（需要浏览器 User-Agent）：

- 文件清单：`https://api.polyhaven.com/files/<id>`，取 `blend.1k.blend.url` 及其 `include` 里的贴图；HDRI 取 `hdri.2k.hdr.url`。

PowerShell 示例（在仓库根目录执行）：

```powershell
[Net.ServicePointManager]::SecurityProtocol = 'Tls12'
$h = @{ 'User-Agent' = 'Mozilla/5.0' }
foreach ($id in 'island_tree_01','island_tree_02','island_tree_03','tree_small_02','fir_sapling_medium','shrub_01','shrub_03') {
  $b = (Invoke-RestMethod "https://api.polyhaven.com/files/$id" -Headers $h).blend.'1k'.blend
  $dir = "assets/polyhaven/models/$id"; New-Item -ItemType Directory -Force $dir | Out-Null
  Invoke-WebRequest $b.url -Headers $h -OutFile "$dir/$id.blend"
  foreach ($p in $b.include.PSObject.Properties) { $dst = Join-Path $dir $p.Name; New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null; Invoke-WebRequest $p.Value.url -Headers $h -OutFile $dst }
}
$u = (Invoke-RestMethod 'https://api.polyhaven.com/files/kloppenheim_06_puresky' -Headers $h).hdri.'2k'.hdr.url
New-Item -ItemType Directory -Force assets/polyhaven/hdris | Out-Null
Invoke-WebRequest $u -Headers $h -OutFile assets/polyhaven/hdris/kloppenheim_06_puresky_2k.hdr
```

注意：`pine_tree_01`（557 MB）和 `jacaranda_tree`（176 MB）过大，未采用。