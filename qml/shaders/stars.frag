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
// Calque étoiles : petits points qui scintillent et dérivent très lentement, ajoutés à la lumière du fond (alpha 0 :
// mélange additif avec l'alpha prémultiplié de Qt), sur deux plans de profondeur
void main() {
    vec3 col = vec3(0.0);
    for (int l = 0; l < 2; l++) {
        float fl = float(l);
        float scale = 46.0 + fl * 34.0;
        vec2 g = (qt_TexCoord0 + vec2(time * (0.002 + fl * 0.0015), time * 0.0007)) * vec2(ratio, 1.0) * scale;
        vec2 id = floor(g);
        float h = hash(id + fl * 31.0);
        if (h > 0.97) {
            vec2 p = fract(g) - 0.5 - (vec2(hash(id + 3.1), hash(id + 7.7)) - 0.5) * 0.6;
            float tw = 0.35 + 0.65 * pow(0.5 + 0.5 * sin(time * (0.5 + h * 2.5) + h * 60.0), 2.0);
            float star = smoothstep(0.14 - fl * 0.04, 0.0, length(p));
            col += mix(vec3(1.0), c1.rgb * 1.6, 0.25) * star * tw * (1.2 - fl * 0.45);
        }
    }
    fragColor = vec4(col, 0.0) * qt_Opacity;
}
