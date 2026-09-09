// Lunar history for the 月球 mode: eras (info panel + timeline bands), events, landing sites, and the
// time-dependent look of the Moon (magma ocean, mare basalt flooding, crater accumulation).
// Times are years before present. Dates follow the commonly cited lunar chronology (approximate).
const Ma = 1e6;
const NOW = 2026;

export const MOON_ERAS = [
  { id: 'theia', short: '碰撞', eon: '月球 · 形成', name: '忒伊亚大碰撞', start: 4540 * Ma, end: 4510 * Ma, color: '#6b1f0c',
    desc: '太阳系形成约 6000 万年后，一颗火星大小的原行星“忒伊亚”以斜角撞上年轻的地球。撞击把两个天体的地幔物质抛入轨道，形成一个炽热的碎屑盘，几十到几百年内就凝聚成月球。月球的成分与地球地幔高度一致，正是这一起源的证据。',
    facts: ['撞击体质量约为地球的十分之一', '碎屑盘在数十至数百年内聚合成月球', '月球岩石的氧同位素与地球几乎相同', '地球自转被撞得只剩约 5-6 小时一天'],
    stats: { 月距: '尚未形成', 地球日: '≈5-6 小时', 撞击体: '火星大小', 时间: '45.1 亿年前' } },
  { id: 'magma', short: '岩浆洋', eon: '月球 · 前酒海纪', name: '月球的岩浆洋', start: 4510 * Ma, end: 4350 * Ma, color: '#9a3a14',
    desc: '刚凝聚的月球整体熔融，表面是几百公里深的岩浆洋。它离地球只有约 2-3 万公里，在地球天空中比今天大十几倍，潮汐把两颗天体反复揉搓。随着岩浆洋冷却，密度小的斜长石浮到表面，形成月球最古老的浅色高地地壳。',
    facts: ['岩浆洋深度可能超过 500 公里', '斜长岩高地地壳约在 44.5-43.6 亿年前固结', '月球最初的公转周期只有几天', '潮汐作用让月球以极快的速度远离地球'],
    stats: { 月距: '≈2-3 万 km', 表面: '岩浆洋', 地球日: '≈6 小时', 潮汐: '极强' } },
  { id: 'crust', short: '高地', eon: '月球 · 前酒海纪', name: '斜长岩高地与撞击', start: 4350 * Ma, end: 4100 * Ma, color: '#a89f90',
    desc: '浅色的斜长岩地壳覆盖全月，撞击不断在上面凿出坑穴。月球此时已冷却到足以保留撞击坑，最古老的盆地——南极-艾特肯盆地——大约在这一时期形成，直径 2500 公里，是太阳系已知最大的撞击构造之一。',
    facts: ['南极-艾特肯盆地：直径约 2500 公里、深 13 公里', '高地岩石富含斜长石，反射率高，因此呈浅色', '月球背面地壳比正面厚，可能与地球的热辐射有关', '月距增加到约 10 万公里'],
    stats: { 月距: '≈10 万 km', 表面: '斜长岩高地', 撞击坑: '快速累积', 地球日: '≈8 小时' } },
  { id: 'lhb', short: '重轰击', eon: '月球 · 酒海纪', name: '晚期重轰击', start: 4100 * Ma, end: 3800 * Ma, color: '#6b5a4a',
    desc: '巨行星轨道的迁移搅动了小行星带，大量直径几十上百公里的天体砸向内太阳系。月球在短短几亿年间被凿出十几个直径数百公里的巨型盆地：酒海、雨海、澄海、危海、东海……今天月球正面那些大圆盘状的月海，都是这些盆地后来被岩浆填平的结果。',
    facts: ['雨海盆地约 39.2 亿年前形成，直径 1100 公里', '东海盆地（约 38 亿年前）是最后一个大型多环盆地', '同期地球也遭受轰击，但痕迹已被板块运动抹去', '阿波罗采回的样品让科学家推算出这一“撞击高峰”'],
    stats: { 月距: '≈15 万 km', 大型盆地: '十余个', 地球日: '≈10 小时', 时间: '41-38 亿年前' } },
  { id: 'mare', short: '月海', eon: '月球 · 雨海纪', name: '月海喷发：黑色的“海”', start: 3800 * Ma, end: 3100 * Ma, color: '#3d3f48',
    desc: '月球内部放射性元素积累的热量让地幔部分熔融，富含铁钛的玄武岩岩浆沿盆地裂隙涌出，把正面的大型盆地填成平坦的深色平原。古人以为那是海，因此得名“月海”。它们覆盖了正面约 31% 的面积，而背面因地壳更厚，几乎没有月海。',
    facts: ['月海玄武岩主要喷发于 38-31 亿年前，少量持续到约 12 亿年前', '正面月海覆盖率约 31%，背面仅约 2%', '玄武岩含铁钛高，反射率低，因此颜色深', '风暴洋是最大的月海，面积约 400 万平方公里'],
    stats: { 月距: '≈20 万 km', 月海: '正面 31%', 火山活动: '高峰', 地球日: '≈12 小时' } },
  { id: 'eratosthenian', short: '爱拉托逊纪', eon: '月球 · 爱拉托逊纪', name: '宁静，与缓慢的远离', start: 3100 * Ma, end: 800 * Ma, color: '#77787c',
    desc: '火山活动基本停息，撞击频率降到很低，月球进入漫长的宁静期。太阳风与微陨石持续把表面研磨成细腻的月壤；被地球潮汐锁定的月球永远以同一面朝向地球，同时以每年几厘米的速度慢慢远离，地球的一天也随之变长。',
    facts: ['月球以每年约 3.8 厘米的速度远离地球', '地球日从约 18 小时增长到 22 小时', '月壤由数十亿年的微陨石轰击累积而成', '这一时期形成的撞击坑已失去明亮的辐射纹'],
    stats: { 月距: '≈30 万 km', 火山活动: '基本停止', 地球日: '≈18-22 小时', 表面: '月壤累积' } },
  { id: 'copernican', short: '哥白尼纪', eon: '月球 · 哥白尼纪', name: '年轻的撞击坑', start: 800 * Ma, end: 70, color: '#a3a4a8',
    desc: '偶发的撞击留下了月球上最醒目的“新”地貌：哥白尼坑（约 8 亿年前）、第谷坑（约 1.08 亿年前）和阿里斯塔克斯坑。它们周围亮白的辐射纹是新鲜抛射物尚未被太空风化变暗的证据。人类文明史上，月相成为最早的历法，月食与潮汐启发了最早的天文学。',
    facts: ['哥白尼坑：直径 93 公里，约 8 亿年前', '第谷坑：直径 85 公里，约 1.08 亿年前，辐射纹长达 1500 公里', '月球每年被约 100 吨陨石物质击中', '1609 年伽利略用望远镜首次看清月面的山与坑'],
    stats: { 月距: '≈38 万 km', 新撞击坑: '第谷、哥白尼', 地球日: '≈24 小时', 潮汐: '每天两次' } },
  { id: 'space', short: '探月', eon: '月球 · 太空时代', name: '人类的足迹', start: 70, end: 0, color: '#6cb4ff',
    desc: '1959 年苏联“月球 2 号”成为第一个撞上月球的人造物体；1969 年 7 月 20 日，阿波罗 11 号的宇航员在静海踏上月面。六次阿波罗登月共有 12 人行走于月球，带回 382 公斤样品。2019 年嫦娥四号首次在月球背面软着陆，2024 年嫦娥六号首次从背面取回样品。',
    facts: ['1969-1972：阿波罗 11、12、14、15、16、17 号，12 人登月', '1970-1976：苏联“月球”系列无人采样返回', '2013 嫦娥三号、2019 嫦娥四号（背面）、2020 嫦娥五号、2024 嫦娥六号（背面采样）', '阿波罗留下的激光反射镜至今仍用于测量月距'],
    stats: { 月距: '38.44 万 km', 登月人数: '12', 采样: '>380 kg', 远离速度: '3.8 cm/年' } },
];

export const MOON_EVENTS = [
  { t: 4510 * Ma, name: '大碰撞，月球凝聚' },
  { t: 4400 * Ma, name: '岩浆洋固结，高地地壳形成' },
  { t: 4250 * Ma, name: '南极-艾特肯盆地' },
  { t: 3920 * Ma, name: '雨海盆地撞击' },
  { t: 3800 * Ma, name: '东海盆地：最后的大型盆地' },
  { t: 3500 * Ma, name: '月海喷发高峰' },
  { t: 1200 * Ma, name: '最后的月海玄武岩' },
  { t: 800 * Ma, name: '哥白尼撞击坑' },
  { t: 108 * Ma, name: '第谷撞击坑' },
  { t: NOW - 1959, name: '月球 2 号首次撞月' },
  { t: NOW - 1969, name: '阿波罗 11 号登月' },
  { t: NOW - 1972, name: '阿波罗 17 号：最后一次载人登月' },
  { t: NOW - 2013, name: '嫦娥三号着陆' },
  { t: NOW - 2019, name: '嫦娥四号：首次背面着陆' },
  { t: NOW - 2024, name: '嫦娥六号：首次背面采样返回' },
];

// Landing / impact sites (selenographic lon/lat, degrees; east positive). year = CE.
export const MOON_SITES = [
  { name: '月球 2 号 · 1959', lon: 0.0, lat: 29.1, year: 1959, kind: 'probe' },
  { name: '月球 9 号 · 1966', lon: -64.37, lat: 7.08, year: 1966, kind: 'probe' },
  { name: '阿波罗 11 · 1969', lon: 23.47, lat: 0.67, year: 1969, kind: 'crew' },
  { name: '阿波罗 12 · 1969', lon: -23.42, lat: -3.01, year: 1969, kind: 'crew' },
  { name: '月球 16 号 · 1970', lon: 56.30, lat: -0.68, year: 1970, kind: 'probe' },
  { name: '阿波罗 14 · 1971', lon: -17.47, lat: -3.65, year: 1971, kind: 'crew' },
  { name: '阿波罗 15 · 1971', lon: 3.63, lat: 26.13, year: 1971, kind: 'crew' },
  { name: '阿波罗 16 · 1972', lon: 15.50, lat: -8.97, year: 1972, kind: 'crew' },
  { name: '阿波罗 17 · 1972', lon: 30.77, lat: 20.19, year: 1972, kind: 'crew' },
  { name: '嫦娥三号 · 2013', lon: -19.51, lat: 44.12, year: 2013, kind: 'probe' },
  { name: '嫦娥四号 · 2019（背面）', lon: 177.6, lat: -45.5, year: 2019, kind: 'probe' },
  { name: '嫦娥五号 · 2020', lon: -51.92, lat: 43.06, year: 2020, kind: 'probe' },
  { name: '嫦娥六号 · 2024（背面）', lon: -153.99, lat: -41.64, year: 2024, kind: 'probe' },
];

export function moonEraAt(yearsBP) {
  for (const e of MOON_ERAS) if (yearsBP <= e.start && yearsBP > e.end) return e;
  return yearsBP > MOON_ERAS[0].start ? MOON_ERAS[0] : MOON_ERAS[MOON_ERAS.length - 1];
}

const clamp01 = (v) => Math.min(1, Math.max(0, v));
/** Appearance parameters for the Moon at a given time. */
export function moonEnvAt(yearsBP) {
  const t = yearsBP / Ma;
  return {
    exists: t <= 4510,
    magma: clamp01((t - 4350) / (4510 - 4350)),          // 1 right after formation -> 0 once the crust has solidified
    mare: clamp01((3850 - t) / (3850 - 3150)),            // dark basalt plains fill the basins 3.85-3.15 Ga
    crater: 0.25 + 0.95 * clamp01((4450 - t) / (4450 - 3800)), // relief/crater density builds up through the LHB
  };
}

/** Selenographic lon/lat -> position in the Moon group's local frame (+Z faces Earth, +X = east, +Y = north). */
export function moonLonLatToLocal(lon, lat, r) {
  const la = lat * Math.PI / 180, lo = lon * Math.PI / 180;
  return [Math.cos(la) * Math.sin(lo) * r, Math.sin(la) * r, Math.cos(la) * Math.cos(lo) * r];
}
