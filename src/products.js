// 产品数据：新增一个项目只需在这里加一条记录，页面会自动生成展示区块。
// 字段说明：
//   id        锚点 id（可用 #id 直达）
//   kicker    小标题（分类/系列）
//   title / subtitle / desc
//   tags      标签数组
//   poster    海报图路径（可为空：将显示以 accent 为主色的占位海报）
//   accent    占位海报与高光颜色
//   url       完整版链接（新标签页打开）
//   embed     可选：页内嵌入地址（为空则不提供“页内演示”按钮）
//   features  亮点列表 [{ icon, title, text }]
//   status    'live' | 'soon'（soon 显示为小卡片）
export const PRODUCTS = [
  {
    id: 'earth-chronicle',
    kicker: '交互式三维地球',
    title: '地球纪元 · Earth Chronicle',
    subtitle: '46 亿年的行星演化 · 30 万年的人类迁徙',
    desc: '一个完全离线的交互式三维地球平台：拖动旋转，拖动时间轴，看大陆漂移、雪球地球、恐龙灭绝，直到人类的灯光点亮夜空。现代地球使用 NASA Blue Marble 与 Black Marble 卫星影像，远古时代的地形、云层与夜灯由 Blender 程序化生成并烘焙。',
    tags: ['三维交互', '时间轴叙事', 'Blender 烘焙', '零 API', '离线运行'],
    poster: '/site/earth_preview.png',
    accent: '#3d8ee6',
    url: '/earth/',
    embed: '/earth/?embed=1',
    features: [
      { icon: '🌍', title: '地球演化', text: '冥古宙岩浆海、大氧化事件、两次雪球地球、盘古大陆聚合与裂解、白垩纪高海平面、希克苏鲁伯撞击、第四纪冰期——全部由时间轴驱动，并附古地理小地图。' },
      { icon: '🧭', title: '人类迁徙', text: '30 万年间 50 余条迁徙路线逐步绘出，40 个考古遗址随时间点亮，人口、海平面与冰盖边缘实时统计。' },
      { icon: '✨', title: '逼真地球', text: '4K/8K 程序化地形、法线与生物群系贴图，大气散射、云影、海面高光与城市夜灯；月球同样在 Blender 中程序化建模。' },
    ],
    status: 'live',
  },
  {
    id: 'autumn-creek',
    kicker: '交互式三维风景',
    title: '溪畔秋日',
    subtitle: 'A place to slow down',
    desc: '走进溪畔秋日。自由环绕一座三维山村，点击石桥、稻田与小狗，听见溪水与鸟鸣——一个为放慢节奏而做的沉浸式场景。',
    tags: ['三维场景', '环境音效', '点击互动', '氛围叙事'],
    poster: null,
    accent: '#3f7a4a',
    emoji: '🍂',
    url: 'http://127.0.0.1:8765/?v=3d-final',
    embed: 'http://127.0.0.1:8765/?v=3d-final',
    features: [
      { icon: '🏞️', title: '自由环绕', text: '拖动镜头在山村间环绕，秋色随视角变化，溪水在脚下流过。' },
      { icon: '🐕', title: '可点击的世界', text: '石桥、稻田与小狗都能触发互动与声音，细节里藏着惊喜。' },
      { icon: '🎧', title: '声音景观', text: '溪水与鸟鸣随位置变化，营造缓慢、安静的沉浸感。' },
    ],
    status: 'live',
  },
  {
    id: 'moon-chronicle',
    kicker: '研发中',
    title: '月球纪元',
    desc: '把同一套程序化管线搬到月球：大碰撞、月海玄武岩喷发、陨击历史与阿波罗着陆点。',
    emoji: '🌙',
    accent: '#7a86a8',
    status: 'soon',
  },
  {
    id: 'tree-of-life',
    kicker: '研发中',
    title: '生命之树',
    desc: '可缩放的演化树，与地球纪元的时间轴联动：拖到任何年代，看看那时的世界里住着谁。',
    emoji: '🧬',
    accent: '#8a5aa8',
    status: 'soon',
  },
];
