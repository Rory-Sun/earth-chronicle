// GLSL shaders for the Earth surface, atmosphere shell and cloud layer. (GLSL ES 3.0 via THREE.GLSL3)

export const noiseGLSL = /* glsl */ `
float hash13(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float vnoise(vec3 p) {
  vec3 i = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float n000 = hash13(i), n100 = hash13(i + vec3(1, 0, 0)), n010 = hash13(i + vec3(0, 1, 0)), n110 = hash13(i + vec3(1, 1, 0));
  float n001 = hash13(i + vec3(0, 0, 1)), n101 = hash13(i + vec3(1, 0, 1)), n011 = hash13(i + vec3(0, 1, 1)), n111 = hash13(i + vec3(1, 1, 1));
  return mix(mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y), mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y), f.z);
}
float fbm(vec3 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++) { v += a * vnoise(p); p = p * 2.03 + 11.7; a *= 0.5; }
  return v;
}
float ridged(vec3 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++) { v += a * (1.0 - abs(2.0 * vnoise(p) - 1.0)); p = p * 2.1 + 3.3; a *= 0.5; }
  return v;
}
`;

export const surfaceVertex = /* glsl */ `
uniform sampler2D tHeight;
uniform float uDisplace;
uniform float uSeaLevel;
uniform float uIsBase;
uniform float uRadius;
out vec3 vLocal;
out vec3 vWorldPos;
out vec2 vUv;
out float vHeight;
out vec3 vNormalW;
out vec3 vEastW;
out vec3 vNorthW;
float decodeH(float e) { float s = (e - 0.5) * 2.0; return sign(s) * s * s * 9.0; }
void main() {
  vUv = uv;
  vec3 n = normalize(position);
  vec3 east = normalize(vec3(n.z, 0.0, -n.x));
  vec3 north = cross(n, east);
  mat3 rot = mat3(modelMatrix);
  vNormalW = normalize(rot * n);
  vEastW = normalize(rot * east);
  vNorthW = normalize(rot * north);
  float h = decodeH(texture(tHeight, uv).r);
  vHeight = h;
  float above = max(h - uSeaLevel * 0.001, 0.0);
  float r = uRadius + (uIsBase > 0.5 ? 0.0 : above * uDisplace);
  vLocal = position;
  vec4 wp = modelMatrix * vec4(position * r, 1.0);
  vWorldPos = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}
`;

export const surfaceFragment = /* glsl */ `
precision highp float;
out vec4 fragColor;
#define gl_FragColor fragColor
uniform sampler2D tColor, tNormal, tHeight, tMasksA, tMasksB, tLights, tClouds;
uniform vec3 uSunDir;
uniform float uSeaLevel, uVeg, uIceLat, uIceBoost, uErosion, uLava, uLights, uCloudOffset, uCloudShadow, uTime, uIsBase, uAtmoStrength, uSunIntensity, uNormalStrength, uCloudsOn, uSeaIce;
uniform vec3 uOceanDeep, uOceanShallow, uAtmoColor, uHazeColor, uBarrenTint;
in vec3 vLocal;
in vec3 vWorldPos;
in vec2 vUv;
in float vHeight;
in vec3 vNormalW;
in vec3 vEastW;
in vec3 vNorthW;
${noiseGLSL}
float decodeH(float e) { float s = (e - 0.5) * 2.0; return sign(s) * s * s * 9.0; }
void main() {
  vec3 nLocal = normalize(vLocal);
  vec2 uv = vUv;
  vec4 mA = texture(tMasksA, uv);   // land, vegetation, aridity
  vec4 mB = texture(tMasksB, uv);   // ice, shelf, roughness
  vec3 albedo = texture(tColor, uv).rgb;
  float h = decodeH(texture(tHeight, uv).r);
  float land = uIsBase > 0.5 ? 0.0 : mA.r;
  vec3 nWorld = normalize(vNormalW);
  float lat = degrees(asin(clamp(nWorld.y, -1.0, 1.0)));
  float absLat = abs(lat);

  float n1 = fbm(nLocal * 60.0);
  float n2 = fbm(nLocal * 9.0);
  float n3 = fbm(nLocal * 25.0 + 4.0);

  // --- continental "erosion" for the Precambrian: shrink land from the coasts inward
  if (uErosion > 0.001) {
    float interior = textureLod(tMasksA, uv, 5.0).r;
    float keep = smoothstep(uErosion, uErosion + 0.18, interior * 0.85 + (n2 - 0.5) * 0.35 + 0.15);
    land *= keep;
  }

  // --- water line by height vs. current sea level
  float sl = uSeaLevel * 0.001;
  float aa = fwidth(h) * 1.5 + 0.0015;
  float above = smoothstep(sl - aa, sl + aa, h);
  if (uIsBase > 0.5) above = 0.0;
  float isLand = land * above;
  float exposed = (1.0 - land) * above * (1.0 - uIsBase);
  float flooded = land * (1.0 - above);

  // --- land colour with era adjustments
  // close-range detail: fine albedo grain, dune ridges on deserts, mottling on vegetation
  float camDist = length(cameraPosition);
  float detailAmt = smoothstep(3.2, 1.3, camDist);
  if (detailAmt > 0.001) {
    float grain = fbm(nLocal * 700.0) - 0.5;
    float dunes = ridged(nLocal * 420.0) - 0.5;
    float mottle = fbm(nLocal * 160.0 + 3.0) - 0.5;
    float detail = grain * 0.10 + dunes * 0.14 * mA.b + mottle * 0.16 * mA.g;
    albedo *= 1.0 + detail * detailAmt * mA.r;
  }
  float gray = dot(albedo, vec3(0.333));
  vec3 barren = mix(vec3(0.30, 0.24, 0.17), vec3(0.50, 0.42, 0.31), n2) * (0.65 + 0.9 * gray) * uBarrenTint;
  float iceGate = smoothstep(90.0, 80.0, uIceLat);
  vec3 tundraRock = mix(vec3(0.30, 0.27, 0.22), vec3(0.46, 0.43, 0.37), n2) * (0.75 + 0.5 * n1);
  vec3 albedoLand = mix(albedo, tundraRock, mB.r * (1.0 - iceGate));
  vec3 landCol = mix(albedoLand, barren, clamp(mA.g * 1.4, 0.0, 1.0) * (1.0 - uVeg));
  landCol = mix(landCol, barren, (1.0 - uVeg) * 0.35 * (1.0 - mB.r));
  vec3 seabed = mix(vec3(0.30, 0.27, 0.19), vec3(0.42, 0.38, 0.28), n3) * (0.8 + 0.4 * n1);

  // --- ice
  float capEdge = uIceLat + (n2 - 0.5) * 12.0 + (n3 - 0.5) * 4.0;
  float cap = smoothstep(capEdge - 7.0, capEdge + 1.0, absLat);
  float bakedIce = mB.r * smoothstep(90.0, 80.0, uIceLat);
  // glacial boost: extra ice sheets on high-latitude land and glaciated mountains (never tropical lowlands)
  float boostLat = smoothstep(uIceLat - 26.0, uIceLat - 8.0, absLat + (n2 - 0.5) * 16.0);
  float boostMtn = smoothstep(2.2, 3.4, h) * smoothstep(20.0, 45.0, absLat);
  float boostIce = uIceBoost * max(boostLat, boostMtn * 0.8);
  float landIce = max(max(bakedIce, cap), boostIce);
  float seaIce = cap * (1.0 - above) * uSeaIce;
  seaIce = max(seaIce, mB.r * (1.0 - land) * (1.0 - above) * uSeaIce * smoothstep(88.0, 78.0, uIceLat));
  vec3 iceCol = mix(vec3(0.78, 0.82, 0.88), vec3(0.94, 0.96, 1.0), n1) ;

  // --- compose surface
  float shelfT = pow(mB.g, 2.2) * 0.75 * (1.0 - uIsBase);
  // plate meshes only draw land, flooded land, exposed seabed and shelf water; deep ocean comes from the base sphere
  if (uIsBase < 0.5 && land < 0.01 && above < 0.01 && shelfT < 0.02) discard;
  float oceanVar = 0.86 + 0.28 * fbm(nWorld * 5.0 + 11.0);
  vec3 ocean = mix(uOceanDeep * oceanVar, uOceanShallow, shelfT);
  vec3 surf = ocean;
  surf = mix(surf, mix(ocean, uOceanShallow * 1.25, 0.8), flooded);
  surf = mix(surf, seabed, exposed);
  surf = mix(surf, landCol, isLand);
  float iceAmt = max(landIce * above, seaIce);
  surf = mix(surf, iceCol, iceAmt);
  float waterness = (1.0 - above) * (1.0 - seaIce);

  // --- lava (Hadean)
  float cracks = smoothstep(0.66, 0.74, ridged(nLocal * 14.0 + uTime * 0.015)) * 0.7 + smoothstep(0.7, 0.78, ridged(nLocal * 45.0)) * 0.5;
  float lavaSea = smoothstep(0.52, 0.7, fbm(nLocal * 3.0 + 7.0));
  float lavaGlowMask = smoothstep(0.35, 0.8, fbm(nLocal * 6.0 + uTime * 0.01));
  vec3 lavaRock = mix(vec3(0.025, 0.015, 0.012), vec3(0.08, 0.045, 0.035), n1) * (1.0 - lavaSea * 0.5);
  float glowAmt = clamp(cracks * (0.35 + 0.65 * lavaGlowMask) + lavaSea * (0.6 + 0.4 * n3), 0.0, 1.0);
  vec3 lavaGlow = mix(vec3(0.9, 0.12, 0.02), vec3(1.0, 0.55, 0.12), glowAmt) * glowAmt * 0.85;
  surf = mix(surf, lavaRock, uLava);

  // --- normals
  vec3 nm = texture(tNormal, uv).xyz * 2.0 - 1.0;
  if (detailAmt > 0.001) {
    // micro normal perturbation from the ridged/noise fields so relief keeps reading when zoomed in
    float e = 0.0015;
    float h0 = fbm(nLocal * 520.0);
    float hx = fbm((nLocal + vec3(e, 0.0, 0.0)) * 520.0);
    float hy = fbm((nLocal + vec3(0.0, e, 0.0)) * 520.0);
    nm.xy += vec2(h0 - hx, h0 - hy) * 6.0 * detailAmt * (0.3 + 0.7 * smoothstep(0.3, 2.0, h));
  }
  nm.xy *= uNormalStrength * (isLand + exposed * 0.5) * (1.0 - iceAmt * 0.5);
  vec3 N0 = normalize(vNormalW);
  vec3 N = normalize(normalize(vEastW) * nm.x + normalize(vNorthW) * nm.y + N0 * nm.z);
  vec3 L = normalize(uSunDir);
  vec3 V = normalize(cameraPosition - vWorldPos);
  float NdL0 = dot(N0, L);
  float diff = max(dot(N, L), 0.0);
  diff = mix(diff, max(NdL0, 0.0), 0.15);

  // --- cloud shadows
  vec2 cuv = vec2(uv.x + uCloudOffset, uv.y);
  float cloud = texture(tClouds, cuv).r * uCloudsOn;
  vec2 cuvS = cuv + vec2(0.004, 0.0);
  float cloudS = texture(tClouds, cuvS).r * uCloudsOn;
  float shadow = 1.0 - uCloudShadow * cloudS * 0.5;

  vec3 sunColor = vec3(1.0, 0.97, 0.93) * uSunIntensity * 1.15;
  vec3 color = surf * diff * sunColor * shadow;

  // --- water specular & fresnel
  vec3 H = normalize(L + V);
  float specPow = mix(500.0, 120.0, shelfT);
  float ripple = (vnoise(nLocal * 900.0 + uTime * 0.3) - 0.5) * 0.02;
  float spec = pow(max(dot(N, H) + ripple, 0.0), specPow);
  float fres = pow(1.0 - max(dot(N0, V), 0.0), 4.0);
  color += sunColor * spec * (0.3 + 0.9 * fres) * 0.7 * waterness * smoothstep(0.0, 0.08, NdL0) * shadow;
  color += ocean * fres * 0.25 * waterness * max(NdL0, 0.0);

  // --- ambient / night
  color += surf * vec3(0.010, 0.014, 0.024);
  float night = 1.0 - smoothstep(-0.25, 0.02, NdL0);
  float lightsTex = texture(tLights, uv).r;
  color += vec3(1.0, 0.72, 0.40) * lightsTex * uLights * isLand * night * 1.8 * (1.0 - cloud * 0.55);
  // moonlit hint on the night ocean
  color += vec3(0.02, 0.03, 0.05) * night * waterness * fres;

  // --- lava emission
  color += lavaGlow * uLava * (1.0 - cloud * 0.3);

  // --- atmosphere on the surface
  float rim = pow(1.0 - max(dot(N0, V), 0.0), 3.0);
  float day = smoothstep(-0.15, 0.3, NdL0);
  float term = smoothstep(-0.3, 0.0, NdL0) * (1.0 - smoothstep(0.0, 0.35, NdL0));
  vec3 atmo = uAtmoColor * rim * (0.05 + 0.95 * day) * uAtmoStrength;
  color += atmo * 0.55 + uHazeColor * term * rim * 0.35 * uAtmoStrength;
  color = mix(color, uAtmoColor * (0.1 + 0.9 * day) * 0.7 * uSunIntensity, rim * 0.18 * uAtmoStrength);

  gl_FragColor = vec4(color, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;

export const atmosphereVertex = /* glsl */ `
out vec3 vNormalW;
out vec3 vWorldPos;
void main() {
  vNormalW = normalize(mat3(modelMatrix) * normal);
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorldPos = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}
`;

export const atmosphereFragment = /* glsl */ `
precision highp float;
out vec4 fragColor;
#define gl_FragColor fragColor
uniform vec3 uSunDir;
uniform vec3 uAtmoColor;
uniform vec3 uHazeColor;
uniform float uStrength;
uniform float uLimb;
in vec3 vNormalW;
in vec3 vWorldPos;
void main() {
  vec3 N = normalize(vNormalW);
  vec3 V = normalize(cameraPosition - vWorldPos);
  vec3 L = normalize(uSunDir);
  float x = max(dot(N, V), 0.0);
  float outer = pow(smoothstep(0.0, uLimb, x), 2.6) * 1.35;
  float inner = pow(1.0 - smoothstep(uLimb, 0.75, x), 3.0) * 0.16;
  float density = x < uLimb ? outer : inner;
  float sun = dot(N, L);
  float lit = smoothstep(-0.35, 0.3, sun);
  vec3 col = mix(uHazeColor, uAtmoColor, smoothstep(-0.2, 0.35, sun));
  float termGlow = exp(-abs(sun) * 7.0) * 0.35 * (x < uLimb ? 1.0 : 0.3);
  vec3 color = (col * density * lit + uHazeColor * termGlow * density) * uStrength;
  gl_FragColor = vec4(color, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;

export const cloudsVertex = /* glsl */ `
out vec3 vNormalW;
out vec3 vWorldPos;
out vec2 vUv;
out vec3 vLocal;
void main() {
  vUv = uv;
  vLocal = position;
  vNormalW = normalize(mat3(modelMatrix) * normal);
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorldPos = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}
`;

export const cloudsFragment = /* glsl */ `
precision highp float;
out vec4 fragColor;
#define gl_FragColor fragColor
uniform sampler2D tClouds;
uniform vec3 uSunDir;
uniform float uOffset;
uniform float uOpacity;
uniform float uSunIntensity;
uniform vec3 uTint;
uniform float uTime;
in vec3 vNormalW;
in vec3 vWorldPos;
in vec2 vUv;
in vec3 vLocal;
${noiseGLSL}
void main() {
  vec2 uv = vec2(vUv.x + uOffset, vUv.y);
  float c = texture(tClouds, uv).r;
  float camDist = length(cameraPosition);
  float near = smoothstep(3.5, 1.4, camDist);
  float detail = fbm(normalize(vLocal) * 90.0 + uTime * 0.02);
  float fine = fbm(normalize(vLocal) * 320.0 - uTime * 0.01);
  c = clamp(c * (0.75 + 0.5 * detail) * (1.0 + near * (fine - 0.5) * 0.9), 0.0, 1.0);
  c = mix(c, smoothstep(0.08, 0.75, c), near * 0.6);
  vec3 N = normalize(vNormalW);
  vec3 V = normalize(cameraPosition - vWorldPos);
  vec3 L = normalize(uSunDir);
  float NdL = dot(N, L);
  float lit = smoothstep(-0.2, 0.35, NdL);
  // fake thickness shading: brighter tops, shaded bottoms via texture gradient toward sun
  vec2 duv = vec2(0.002, 0.0);
  float cS = texture(tClouds, uv + duv).r;
  float shade = clamp(1.0 - (cS - c) * 2.5, 0.55, 1.15);
  vec3 sunColor = vec3(1.0, 0.96, 0.9) * uSunIntensity;
  vec3 color = uTint * sunColor * (max(NdL, 0.0) * 0.9 + 0.1) * shade;
  color += uTint * vec3(0.9, 0.55, 0.3) * exp(-abs(NdL) * 9.0) * 0.35 * uSunIntensity;
  color += vec3(0.01, 0.012, 0.02);
  float fres = pow(1.0 - max(dot(N, V), 0.0), 2.0);
  float alpha = c * uOpacity * (1.0 - fres * 0.6);
  alpha *= mix(0.25, 1.0, lit);
  gl_FragColor = vec4(color, alpha);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;

export const starsVertex = /* glsl */ `
attribute float size;
attribute vec3 tint;
out vec3 vTint;
out float vTw;
uniform float uTime;
uniform float uScale;
void main() {
  vTint = tint;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  float tw = 0.75 + 0.25 * sin(uTime * (1.5 + fract(position.x * 0.37) * 3.0) + position.y);
  vTw = tw;
  gl_PointSize = size * uScale * tw / max(-mv.z * 0.002, 1.0);
  gl_Position = projectionMatrix * mv;
}
`;

export const starsFragment = /* glsl */ `
precision highp float;
out vec4 fragColor;
#define gl_FragColor fragColor
in vec3 vTint;
in float vTw;
uniform float uBrightness;
void main() {
  vec2 d = gl_PointCoord - 0.5;
  float r = length(d) * 2.0;
  float a = smoothstep(1.0, 0.0, r);
  a = a * a * (0.6 + 0.4 * vTw);
  gl_FragColor = vec4(vTint * a * uBrightness, a);
}
`;
