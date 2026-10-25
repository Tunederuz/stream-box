#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;      // secondes
    float ratio;     // largeur / hauteur
    vec4 c1;
    vec4 c2;
    vec4 c3;
    vec4 bg;
};

float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p = p * 2.03 + vec2(1.7, 9.2);
        a *= 0.5;
    }
    return v;
}
float vignette(vec2 uv) {
    vec2 d = uv - 0.5;
    return clamp(1.0 - dot(d, d) * 1.3, 0.0, 1.0);
}
// Fluide : bruit replié sur lui-même (domain warping), des nappes de couleur qui coulent lentement
void main() {
    vec2 uv = qt_TexCoord0 * vec2(ratio, 1.0) * 1.4;
    float t = time * 0.025;
    vec2 q = vec2(fbm(uv + vec2(0.0, t)), fbm(uv + vec2(5.2, 1.3) - t));
    vec2 r = vec2(fbm(uv + 3.0 * q + vec2(1.7, 9.2) + t * 1.4), fbm(uv + 3.0 * q + vec2(8.3, 2.8) - t * 1.1));
    float f = fbm(uv + 3.0 * r);
    vec3 col = mix(bg.rgb, c1.rgb, smoothstep(0.25, 0.85, f));
    col = mix(col, c2.rgb, smoothstep(0.35, 1.1, length(q)) * 0.75);
    col = mix(col, c3.rgb, smoothstep(0.55, 1.0, r.x) * 0.6);
    col *= (0.25 + 0.75 * f * f) * vignette(qt_TexCoord0);
    fragColor = vec4(mix(bg.rgb, col, 0.9), 1.0) * qt_Opacity;
}
