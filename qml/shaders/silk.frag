#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;      // seconds
    float ratio;     // width / height
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
// Silk layer: bundle of glowing threads waving together, like floating fabric; added to the light of the
// base (alpha 0: additive blending with Qt's premultiplied alpha)
void main() {
    vec2 uv = qt_TexCoord0;
    float x = uv.x * ratio;
    float t = time * 0.12;
    vec3 col = vec3(0.0);
    for (int i = 0; i < 18; i++) {
        float fi = float(i) / 18.0;
        float y = 0.5 + 0.22 * sin(x * 1.1 + t + fi * 2.2) * sin(x * 0.7 - t * 0.6 + fi * 1.4)
                + (fi - 0.5) * 0.18 * (1.0 + 0.5 * sin(x * 0.9 + t * 0.8));
        float d = abs(uv.y - y);
        vec3 c = mix(c1.rgb, fi < 0.5 ? c2.rgb : c3.rgb, abs(fi - 0.5) * 2.0);
        col += c * (0.0016 / (d + 0.0025)) * 0.55;
    }
    float yc = 0.5 + 0.22 * sin(x * 1.1 + t + 1.1) * sin(x * 0.7 - t * 0.6 + 0.7);
    col += c1.rgb * exp(-pow((uv.y - yc) * 5.0, 2.0)) * 0.18;
    fragColor = vec4(min(col, vec3(1.0)) * vignette(uv), 0.0) * qt_Opacity;
}
