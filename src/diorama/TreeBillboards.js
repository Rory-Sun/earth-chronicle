// 多角度公告牌树：每棵树是一张始终正对镜头的面片，贴图取自预先渲染的 8 方位 × 2 俯仰角图集
// （tools/diorama_billboards.py），按镜头相对这棵树的方位和俯仰选图，并在相邻角度之间过渡。
// 比两张交叉的卡片好在：转动视角时树形连续变化，不会露出"十字板"，俯视时也不是一个叉。
// 光照自己算：按面片上的位置造一个近似球面的法线，受太阳、天光和阴影影响；投影时面片正对太阳。
import {
  Color, InstancedBufferAttribute, InstancedMesh, Matrix4, PlaneGeometry, ShaderMaterial, UniformsLib, UniformsUtils, Vector2, Vector3,
} from 'three';

const BILLBOARD_VERT = /* glsl */`
  attribute float aRot;
  uniform float bbSize;
  uniform float bbCz;
  uniform vec3 sunDirection;
  varying vec2 vUv;
  varying float vAz;
  varying float vEl;
  varying vec3 vRight;
  varying vec3 vToCam;
  #include <common>
  #include <fog_pars_vertex>
  #include <shadowmap_pars_vertex>
  void main() {
    vec4 ip = modelMatrix * instanceMatrix * vec4( 0.0, 0.0, 0.0, 1.0 );
    float h = length( ( instanceMatrix * vec4( 0.0, 1.0, 0.0, 0.0 ) ).xyz );
    vec3 centre = ip.xyz + vec3( 0.0, bbCz * h, 0.0 );
    vec3 back = vec3( viewMatrix[0][2], viewMatrix[1][2], viewMatrix[2][2] );       // 相机背向（从景物指向相机）
    vec3 toCam = isOrthographic ? back : normalize( cameraPosition - centre );
    vec3 right = vec3( viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0] );
    vec3 up = vec3( viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1] );
    vec3 wp = centre + ( right * position.x + up * position.y ) * bbSize * h;
    vAz = atan( toCam.x, toCam.z ) - aRot;
    vEl = asin( clamp( toCam.y, - 1.0, 1.0 ) );
    vUv = uv; vRight = right; vToCam = toCam;
    vec4 mvPosition = viewMatrix * vec4( wp, 1.0 );
    gl_Position = projectionMatrix * mvPosition;
    // 接收阴影时把取样点朝太阳挪一点：面片在阴影图里是正对太阳的另一张面片，原地取样会自己遮自己
    vec4 worldPosition = vec4( wp + sunDirection * 0.35 * bbSize * h, 1.0 );
    vec3 transformedNormal = ( viewMatrix * vec4( toCam, 0.0 ) ).xyz;
    #include <shadowmap_vertex>
    #include <fog_vertex>
  }`;

const TILE_FN = /* glsl */`
  uniform sampler2D map;
  uniform vec2 ringEl;
  varying vec2 vUv;
  varying float vAz;
  varying float vEl;
  vec4 bbTile( float k, float ring ) {
    float t = ring * 8.0 + k;
    vec2 cell = vec2( mod( t, 4.0 ), floor( t / 4.0 ) );
    return texture2D( map, ( cell + clamp( vUv, 0.012, 0.988 ) ) / 4.0 );
  }
  // 四张相邻视图按透明度加权混合（不加权的话，一张透明、一张不透明处会混出黑边）
  vec4 bbSample() {
    float a = mod( vAz / 6.28318530718 * 8.0, 8.0 );
    float k0 = floor( a ), k1 = mod( k0 + 1.0, 8.0 );
    float fa = smoothstep( 0.25, 0.75, a - k0 );
    float fe = clamp( ( vEl - ringEl.x ) / ( ringEl.y - ringEl.x ), 0.0, 1.0 );
    vec4 c00 = bbTile( k0, 0.0 ), c10 = bbTile( k1, 0.0 ), c01 = bbTile( k0, 1.0 ), c11 = bbTile( k1, 1.0 );
    float w00 = ( 1.0 - fa ) * ( 1.0 - fe ), w10 = fa * ( 1.0 - fe ), w01 = ( 1.0 - fa ) * fe, w11 = fa * fe;
    float alpha = w00 * c00.a + w10 * c10.a + w01 * c01.a + w11 * c11.a;
    vec3 rgb = ( w00 * c00.a * c00.rgb + w10 * c10.a * c10.rgb + w01 * c01.a * c01.rgb + w11 * c11.a * c11.rgb ) / max( alpha, 1e-4 );
    return vec4( rgb, alpha );
  }`;

const BILLBOARD_FRAG = /* glsl */`
  uniform vec3 sunColor;
  uniform vec3 sunDirection;
  uniform float sunGain;
  uniform vec3 ambSky;
  uniform vec3 ambGround;
  uniform float bbSat;
  uniform float bbAO;
  varying vec3 vRight;
  varying vec3 vToCam;
  ${TILE_FN}
  #include <common>
  #include <packing>
  #include <fog_pars_fragment>
  #include <lights_pars_begin>
  #include <shadowmap_pars_fragment>
  #include <shadowmask_pars_fragment>
  void main() {
    vec4 c = bbSample();
    if ( c.a < 0.45 ) discard;
    // 近似球面的法线：面片左右两侧朝两边、上部朝天、中间朝镜头
    vec3 n = normalize( vRight * ( vUv.x * 2.0 - 1.0 ) * 0.85 + vec3( 0.0, 1.0, 0.0 ) * ( vUv.y * 2.0 - 0.7 ) * 0.8 + vToCam * 0.55 );
    float ndl = clamp( dot( n, sunDirection ) * 0.6 + 0.4, 0.0, 1.0 );
    vec3 amb = mix( ambGround, ambSky, n.y * 0.5 + 0.5 );
    vec3 base = mix( vec3( dot( c.rgb, vec3( 0.299, 0.587, 0.114 ) ) ), c.rgb, bbSat );
    base *= mix( 1.0 - bbAO, 1.0, smoothstep( 0.08, 0.62, vUv.y ) );       // 树冠下部压暗：成片的林子才有层次
    vec3 col = base * ( amb + sunColor * sunGain * ndl * getShadowMask() );
    gl_FragColor = vec4( col, 1.0 );
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
    #include <fog_fragment>
  }`;

const DEPTH_FRAG = /* glsl */`
  ${TILE_FN}
  #include <common>
  #include <packing>
  void main() {
    if ( bbSample().a < 0.45 ) discard;
    gl_FragColor = packDepthToRGBA( gl_FragCoord.z );
  }`;

const DEPTH_VERT = /* glsl */`
  attribute float aRot;
  uniform float bbSize;
  uniform float bbCz;
  varying vec2 vUv;
  varying float vAz;
  varying float vEl;
  void main() {
    vec4 ip = modelMatrix * instanceMatrix * vec4( 0.0, 0.0, 0.0, 1.0 );
    float h = length( ( instanceMatrix * vec4( 0.0, 1.0, 0.0, 0.0 ) ).xyz );
    vec3 centre = ip.xyz + vec3( 0.0, bbCz * h, 0.0 );
    vec3 back = vec3( viewMatrix[0][2], viewMatrix[1][2], viewMatrix[2][2] );
    vec3 toCam = isOrthographic ? back : normalize( cameraPosition - centre );
    vec3 right = vec3( viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0] );
    vec3 up = vec3( viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1] );
    vec3 wp = centre + ( right * position.x + up * position.y ) * bbSize * h;
    vAz = atan( toCam.x, toCam.z ) - aRot;
    vEl = asin( clamp( toCam.y, - 1.0, 1.0 ) );
    vUv = uv;
    gl_Position = projectionMatrix * viewMatrix * vec4( wp, 1.0 );
  }`;

/**
 * @param tex   图集贴图（4×4 小图）
 * @param bb    trees.json 里这个变体的 bb 字段 { size, cz, rings: [低角, 高角] }
 * @param list  [[x, y, z, h, rot], ...]（Blender 坐标，Z 向上）
 * @param opts  { sunDirection: Vector3, sunColor: Color, light?: scene.json 的 plant_light }
 */
export function makeBillboardTrees(tex, bb, list, opts) {
  const geo = new PlaneGeometry(1, 1);
  const rot = new Float32Array(list.length);
  const rad = Math.PI / 180;
  const shared = {
    map: { value: tex }, bbSize: { value: bb.size }, bbCz: { value: bb.cz ?? 0.5 },
    ringEl: { value: new Vector2(bb.rings[0] * rad, bb.rings[1] * rad) },
  };
  const mat = new ShaderMaterial({
    name: 'TreeBillboard',
    uniforms: UniformsUtils.merge([UniformsLib.fog, UniformsLib.lights, {
      sunColor: { value: new Color(1, 1, 1) }, sunDirection: { value: new Vector3(0, 1, 0) }, sunGain: { value: 0.80 },
      ambSky: { value: new Color(0.40, 0.45, 0.48) }, ambGround: { value: new Color(0.19, 0.21, 0.16) },
      bbSat: { value: 1.0 }, bbAO: { value: 0.0 },
    }]),
    vertexShader: BILLBOARD_VERT, fragmentShader: BILLBOARD_FRAG, lights: true, fog: true,
  });
  Object.assign(mat.uniforms, shared);
  mat.uniforms.sunDirection.value.copy(opts.sunDirection).normalize();
  if (opts.sunColor) mat.uniforms.sunColor.value.copy(opts.sunColor);
  // 各沙盘的光照差别很大（晨雾、夕照、晴天），scene.json 的 plant_light 可覆盖：{ sunGain, ambSky, ambGround, sat, ao }
  const L = opts.light || {};
  if (L.sunGain != null) mat.uniforms.sunGain.value = L.sunGain;
  if (L.ambSky) mat.uniforms.ambSky.value.setRGB(...L.ambSky);
  if (L.ambGround) mat.uniforms.ambGround.value.setRGB(...L.ambGround);
  if (L.sat != null) mat.uniforms.bbSat.value = L.sat;
  if (L.ao != null) mat.uniforms.bbAO.value = L.ao;
  const mesh = new InstancedMesh(geo, mat, list.length);
  const m4 = new Matrix4();
  list.forEach(([x, y, z, h, r], i) => {
    m4.makeScale(h, h, h).setPosition(x, z, -y);
    mesh.setMatrixAt(i, m4);
    rot[i] = r;
  });
  geo.setAttribute('aRot', new InstancedBufferAttribute(rot, 1));
  mesh.instanceMatrix.needsUpdate = true;
  mesh.customDepthMaterial = new ShaderMaterial({ name: 'TreeBillboardDepth', uniforms: shared, vertexShader: DEPTH_VERT, fragmentShader: DEPTH_FRAG });
  mesh.castShadow = true; mesh.receiveShadow = true; mesh.frustumCulled = false;
  return mesh;
}
