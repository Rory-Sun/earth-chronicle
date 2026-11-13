// 湖面（西湖）：按成图里的湖水原理做实时版本。
//   水体色：不随波纹明暗的散射色（湖心深、岸边浅、大尺度色斑），只接收阳光阴影；
//   镜面倒影：平面反射（山、树、建筑、船）+ 天空（按反射方向查 HDRI），波纹只扰动倒影；
//   条带风痕：沿风向拉长的噪波决定哪里平静如镜、哪里被吹皱（波纹强度、倒影模糊、闪点都跟着它变）；
//   近岸：水浅处半透明透出湖床，岸线有细碎白沫。
// 平面反射的相机与斜裁剪面做法沿用 three.js 的 Water.js。
import {
  Color, HalfFloatType, LinearFilter, LinearMipmapLinearFilter, Matrix4, Mesh, PerspectiveCamera, Plane,
  ShaderMaterial, UniformsLib, UniformsUtils, Vector3, Vector4, WebGLRenderTarget,
} from 'three';

const VERT = /* glsl */`
  uniform mat4 textureMatrix;
  attribute vec2 shore;
  varying vec4 mirrorCoord;
  varying vec4 worldPosition;
  varying vec2 vShore;
  #include <common>
  #include <fog_pars_vertex>
  #include <shadowmap_pars_vertex>
  #include <logdepthbuf_pars_vertex>
  void main() {
    worldPosition = modelMatrix * vec4( position, 1.0 );
    mirrorCoord = textureMatrix * worldPosition;
    vShore = shore;
    vec4 mvPosition = modelViewMatrix * vec4( position, 1.0 );
    gl_Position = projectionMatrix * mvPosition;
    #include <beginnormal_vertex>
    #include <defaultnormal_vertex>
    #include <logdepthbuf_vertex>
    #include <fog_vertex>
    #include <shadowmap_vertex>
  }`;

const FRAG = /* glsl */`
  uniform sampler2D mirrorSampler;
  uniform sampler2D normalSampler;
  uniform sampler2D skySampler;
  uniform float hasSky;
  uniform float skyRot;
  uniform float skyGain;
  uniform float skyMax;
  uniform float sunSpec;
  uniform float shadowMin;
  uniform vec3 skyHorizon;
  uniform vec3 skyZenith;
  uniform float time;
  uniform vec3 sunColor;
  uniform vec3 sunDirection;
  uniform float sunGain;
  uniform vec3 ambient;
  uniform vec3 colDeep;
  uniform vec3 colNear;
  uniform vec3 colShore;
  uniform vec2 reflRange;
  uniform float distortion;
  uniform float ripple;
  uniform float glitter;
  uniform float pscale;
  uniform float clear;
  varying vec4 mirrorCoord;
  varying vec4 worldPosition;
  varying vec2 vShore;

  #include <common>
  #include <packing>
  #include <bsdfs>
  #include <fog_pars_fragment>
  #include <logdepthbuf_pars_fragment>
  #include <lights_pars_begin>
  #include <shadowmap_pars_fragment>
  #include <shadowmask_pars_fragment>

  float hash21( vec2 p ) { p = fract( p * vec2( 123.34, 456.21 ) ); p += dot( p, p + 45.32 ); return fract( p.x * p.y ); }
  float vnoise( vec2 p ) {
    vec2 i = floor( p ), f = fract( p ); f = f * f * ( 3.0 - 2.0 * f );
    return mix( mix( hash21( i ), hash21( i + vec2( 1.0, 0.0 ) ), f.x ), mix( hash21( i + vec2( 0.0, 1.0 ) ), hash21( i + vec2( 1.0, 1.0 ) ), f.x ), f.y );
  }
  float fbm3( vec2 p ) { return ( 0.5 * vnoise( p ) + 0.25 * vnoise( p * 2.03 + 17.1 ) + 0.125 * vnoise( p * 4.01 + 43.7 ) ) / 0.875; }
  vec2 rot2( vec2 p, float a ) { float c = cos( a ), s = sin( a ); return vec2( c * p.x - s * p.y, s * p.x + c * p.y ); }

  float sparkle( vec2 p, float f ) {
    return vnoise( p * f + time * vec2( 0.55, 0.31 ) ) * vnoise( rot2( p, 1.1 ) * f * 1.37 - time * vec2( 0.42, 0.63 ) );
  }

  void main() {
    #include <logdepthbuf_fragment>
    vec2 P = vec2( worldPosition.x, - worldPosition.z ) * pscale;   // 沙盘平面坐标（与 Blender 的 XY 一致）；小水面放大图案比例
    float sh = vShore.x, deep = vShore.y;

    // 风痕：沿风向拉长的条带，calm = 1 处平静如镜；随时间缓慢漂移
    vec2 wq = rot2( vec2( P.x * 0.022, P.y * 0.075 ), 0.42 ) + time * vec2( 0.0030, 0.0011 );
    wq += 0.8 * ( vec2( vnoise( wq * 1.3 + 3.1 ), vnoise( wq * 1.3 + 9.7 ) ) - 0.5 );
    float calm = smoothstep( 0.42, 0.58, fbm3( wq ) );
    float ruf = 1.0 - calm;

    // 波纹：大涌动（到处都有，很弱）+ 风吹细波（只在吹皱处）
    vec2 nB = texture2D( normalSampler, rot2( P, 0.9 ) / 23.0 - time * vec2( 0.0035, 0.0060 ) ).xy * 2.0 - 1.0;
    vec2 nA = texture2D( normalSampler, rot2( P, 0.23 ) / 11.3 + time * vec2( 0.008, 0.005 ) ).xy * 2.0 - 1.0;
    vec2 nC = texture2D( normalSampler, rot2( P, - 0.61 ) / 6.1 + time * vec2( 0.011, - 0.008 ) ).xy * 2.0 - 1.0;
    vec2 nxy = ( nB * 0.30 + ( nA * 0.85 + nC * 0.55 ) * mix( 0.10, 1.0, ruf ) ) * ripple;
    vec3 N = normalize( vec3( nxy.x, 1.0, - nxy.y ) );

    vec3 toEye = cameraPosition - worldPosition.xyz;
    float dist = length( toEye );
    vec3 E = toEye / dist;

    // 水体色：湖心深、岸边浅，大尺度色斑，岸线白沫；只受阳光阴影影响，不随波纹明暗
    vec3 bodyc = mix( colNear, colDeep, deep );
    bodyc = mix( bodyc, colShore, 0.7 * sh );
    bodyc *= mix( 0.80, 1.18, fbm3( P * 0.09 + 5.0 ) );
    float foam = clamp( ( vnoise( P * 9.0 ) - 0.60 ) / 0.40, 0.0, 1.0 ) * clamp( ( sh - 0.65 ) / 0.35, 0.0, 1.0 ) * 0.8;
    bodyc = mix( bodyc, vec3( 0.84, 0.87, 0.86 ), foam );
    float shadow = getShadowMask();
    vec3 body = bodyc * ( ambient + sunColor * sunGain * mix( shadowMin, 1.0, shadow ) );

    // 镜面倒影：平面反射（吹皱处更模糊、更碎）+ 天空
    vec2 off = vec2( nxy.x, nxy.y * 1.8 ) * distortion * clamp( 120.0 / dist, 0.35, 3.0 );
    vec4 mir = texture2D( mirrorSampler, mirrorCoord.xy / mirrorCoord.w + off, ruf * 1.6 );
    vec3 R = reflect( - E, N ); R.y = abs( R.y );
    vec3 sky;
    if ( hasSky > 0.5 ) {
      vec3 Rs = vec3( rot2( R.xz, skyRot ), R.y ).xzy;
      sky = min( texture2D( skySampler, equirectUv( Rs ) ).rgb, vec3( skyMax ) ) * skyGain;
    } else {
      sky = mix( skyHorizon, skyZenith, pow( R.y, 0.6 ) ) * skyGain;
    }
    sky = mix( vec3( dot( sky, vec3( 0.2126, 0.7152, 0.0722 ) ) ), sky, 0.72 );   // 薄雾天的天光偏灰
    vec3 refl = mix( sky, mir.rgb, mir.a );
    // 太阳在水面上的高光（朝太阳方向看时出现）
    float sp = pow( max( dot( reflect( - sunDirection, N ), E ), 0.0 ), 420.0 );
    refl += sunColor * sp * sunSpec * shadow * mix( 0.35, 1.0, ruf );

    float F = 0.02 + 0.98 * pow( 1.0 - max( dot( E, N ), 0.0 ), 5.0 );
    float reflW = mix( reflRange.x, reflRange.y, clamp( ( F - 0.02 ) / 0.28, 0.0, 1.0 ) );
    vec3 col = mix( body, refl, reflW );

    // 粼粼闪点：只在吹皱处，朝太阳一侧（东北偏东）渐强，随时间闪烁
    // 闪点大小跟着屏幕像素走（约 2~3 像素一个），远近都不糊成团、也不闪烁成噪点
    float spkL = clamp( log2( 0.55 / max( length( fwidth( P ) ), 1e-4 ) ), 0.0, 6.0 );
    float spkF = exp2( floor( spkL ) );
    float g = mix( sparkle( P, spkF ), sparkle( P, spkF * 2.0 ), fract( spkL ) );
    float gl = smoothstep( 0.60, 0.74, g ) * mix( 0.25, 1.2, vnoise( P * 0.45 + 2.0 ) );
    float dirf = clamp( ( 0.88 * P.x + 0.47 * P.y ) / 62.0, 0.0, 1.0 );
    col += vec3( 1.0, 0.96, 0.88 ) * gl * dirf * smoothstep( 0.2, 0.9, ruf ) * shadow * glitter;

    // 近岸水浅：略透出湖床
    float alpha = 1.0 - max( clear, clamp( ( sh - 0.45 ) / 0.55, 0.0, 1.0 ) * 0.55 );
    gl_FragColor = vec4( col, alpha );
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
    #include <fog_fragment>
  }`;

export class LakeSurface extends Mesh {
  /**
   * @param geometry 世界坐标（Y 轴向上）下的水面网格；可带 shore 属性（x：0 开阔 → 1 岸线，y：0 岸边 → 1 湖心）
   * @param options  { level, size, waterNormals, sunDirection, sunColor, sky, skySunU, fog, params }
   */
  constructor(geometry, options = {}) {
    super(geometry);
    this.isLakeSurface = true;
    const scope = this;
    const level = options.level || 0;
    const size = options.size || 512;
    const sunDirection = (options.sunDirection || new Vector3(0.5, 0.5, 0.5)).clone().normalize();
    // HDRI 里太阳所在的经度 → 把查表方向绕 Y 轴转到与场景太阳方位一致
    const skySunAng = ((options.skySunU ?? 0.6128) - 0.5) * 2 * Math.PI;
    const skyRot = skySunAng - Math.atan2(sunDirection.z, sunDirection.x);

    const renderTarget = new WebGLRenderTarget(size, size, { type: HalfFloatType, generateMipmaps: true, minFilter: LinearMipmapLinearFilter, magFilter: LinearFilter });
    const textureMatrix = new Matrix4();
    const material = new ShaderMaterial({
      name: 'LakeSurface',
      uniforms: UniformsUtils.merge([UniformsLib.fog, UniformsLib.lights, {
        mirrorSampler: { value: null }, normalSampler: { value: null }, skySampler: { value: null },
        hasSky: { value: 0 }, skyRot: { value: skyRot }, skyGain: { value: 0.62 }, skyMax: { value: 1.0 }, sunSpec: { value: 2.5 }, shadowMin: { value: 0.3 },
        skyHorizon: { value: new Color(0.80, 0.86, 0.92) }, skyZenith: { value: new Color(0.30, 0.48, 0.78) },
        time: { value: 0 }, textureMatrix: { value: null },
        sunColor: { value: new Color(1, 1, 1) }, sunDirection: { value: new Vector3() }, sunGain: { value: 0.75 },
        ambient: { value: new Color(0.66, 0.62, 0.56) },
        colDeep: { value: new Color(0.070, 0.130, 0.155) }, colNear: { value: new Color(0.135, 0.195, 0.190) }, colShore: { value: new Color(0.250, 0.290, 0.235) },
        reflRange: { value: [0.21, 0.75] }, distortion: { value: 0.022 }, ripple: { value: 0.30 }, glitter: { value: 0.9 },
        pscale: { value: 1.0 }, clear: { value: 0.0 },
      }]),
      vertexShader: VERT, fragmentShader: FRAG, lights: true, fog: options.fog !== false, transparent: true,
    });
    const u = material.uniforms;
    u.mirrorSampler.value = renderTarget.texture;
    u.textureMatrix.value = textureMatrix;
    u.normalSampler.value = options.waterNormals || null;
    u.sunDirection.value.copy(sunDirection);
    if (options.sunColor) u.sunColor.value.copy(options.sunColor);
    if (options.sky) { u.skySampler.value = options.sky; u.hasSky.value = 1; }
    // 逐场景的参数覆盖（scene.json 的 lake 字段）：数值、[a, b] 或颜色 [r, g, b]
    for (const [k, v] of Object.entries(options.params || {})) {
      if (!u[k]) continue;
      if (Array.isArray(v) && v.length === 3 && u[k].value && u[k].value.isColor) u[k].value.setRGB(v[0], v[1], v[2]);
      else u[k].value = v;
    }
    this.material = material;
    this.renderTarget = renderTarget;

    const mirrorPlane = new Plane(), normal = new Vector3(0, 1, 0), planePoint = new Vector3(0, level, 0);
    const cameraWorldPosition = new Vector3(), rotationMatrix = new Matrix4(), lookAtPosition = new Vector3();
    const clipPlane = new Vector4(), view = new Vector3(), target = new Vector3(), q = new Vector4();
    const mirrorCamera = new PerspectiveCamera();
    const clearColor = new Color();

    this.onBeforeRender = function (renderer, scene, camera) {
      cameraWorldPosition.setFromMatrixPosition(camera.matrixWorld);
      view.subVectors(planePoint, cameraWorldPosition);
      if (view.dot(normal) > 0) return;                         // 相机在水面以下：不画倒影
      view.reflect(normal).negate(); view.add(planePoint);
      rotationMatrix.extractRotation(camera.matrixWorld);
      lookAtPosition.set(0, 0, -1).applyMatrix4(rotationMatrix).add(cameraWorldPosition);
      target.subVectors(planePoint, lookAtPosition); target.reflect(normal).negate(); target.add(planePoint);
      mirrorCamera.position.copy(view);
      mirrorCamera.up.set(0, 1, 0).applyMatrix4(rotationMatrix).reflect(normal);
      mirrorCamera.lookAt(target);
      mirrorCamera.far = camera.far;
      mirrorCamera.updateMatrixWorld();
      mirrorCamera.projectionMatrix.copy(camera.projectionMatrix);
      textureMatrix.set(0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 0.5, 0.5, 0, 0, 0, 1);
      textureMatrix.multiply(mirrorCamera.projectionMatrix).multiply(mirrorCamera.matrixWorldInverse);
      // 斜裁剪面：只画水面以上的东西
      mirrorPlane.setFromNormalAndCoplanarPoint(normal, planePoint).applyMatrix4(mirrorCamera.matrixWorldInverse);
      clipPlane.set(mirrorPlane.normal.x, mirrorPlane.normal.y, mirrorPlane.normal.z, mirrorPlane.constant);
      const pm = mirrorCamera.projectionMatrix;
      q.x = (Math.sign(clipPlane.x) + pm.elements[8]) / pm.elements[0];
      q.y = (Math.sign(clipPlane.y) + pm.elements[9]) / pm.elements[5];
      q.z = -1.0;
      q.w = (1.0 + pm.elements[10]) / pm.elements[14];
      clipPlane.multiplyScalar(2.0 / clipPlane.dot(q));
      pm.elements[2] = clipPlane.x; pm.elements[6] = clipPlane.y; pm.elements[10] = clipPlane.z + 1.0; pm.elements[14] = clipPlane.w;

      // 倒影只画场景物体：背景留空（透明度 0），天空在着色器里按反射方向另查
      const rt = renderer.getRenderTarget(), xr = renderer.xr.enabled, sau = renderer.shadowMap.autoUpdate;
      const bg = scene.background, ca = renderer.getClearAlpha(); renderer.getClearColor(clearColor);
      scope.visible = false; scene.background = null;
      renderer.xr.enabled = false; renderer.shadowMap.autoUpdate = false;
      renderer.setClearColor(0x000000, 0);
      renderer.setRenderTarget(renderTarget);
      renderer.state.buffers.depth.setMask(true);
      if (renderer.autoClear === false) renderer.clear();
      renderer.render(scene, mirrorCamera);
      scope.visible = true; scene.background = bg;
      renderer.xr.enabled = xr; renderer.shadowMap.autoUpdate = sau;
      renderer.setClearColor(clearColor, ca);
      renderer.setRenderTarget(rt);
      const viewport = camera.viewport;
      if (viewport !== undefined) renderer.state.viewport(viewport);
    };
  }

  setSize(size) { this.renderTarget.setSize(size, size); }
}
