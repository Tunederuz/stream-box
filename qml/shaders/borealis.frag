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
// Aurore boréale : rideaux de lumière qui ondulent, stries verticales, quelques étoiles qui scintillent
void main() {
    vec2 uv = qt_TexCoord0;
    float t = time * 0.06;
    vec3 col = bg.rgb * (1.2 - uv.y * 0.4);
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float x = uv.x * ratio;
        float y = 0.30 + 0.13 * fi + 0.07 * sin(x * 1.7 + t * (1.0 + fi * 0.35) + fi * 2.1)
                + 0.04 * sin(x * 4.3 - t * 1.6 + fi * 1.3) + 0.03 * (noise(vec2(x * 2.0, t + fi)) - 0.5);
        float d = uv.y - y;
        // Rideau : bord net en bas, s'estompe vers le haut
        float curtain = d < 0.0 ? exp(d * 7.0) : exp(-d * 55.0);
        float rays = 0.45 + 0.55 * noise(vec2(x * 38.0 + fi * 17.0, t * 1.5 + fi));
        vec3 c = i == 0 ? c1.rgb : (i == 1 ? c2.rgb : c3.rgb);
        col += c * curtain * rays * (0.55 - fi * 0.1);
    }
    // Étoiles : une par case au plus, qui scintillent
    vec2 g = qt_TexCoord0 * vec2(ratio, 1.0) * 90.0;
    vec2 id = floor(g);
    float h = hash(id);
    if (h > 0.985) {
        vec2 p = fract(g) - 0.5 - (vec2(hash(id + 3.1), hash(id + 7.7)) - 0.5) * 0.6;
        float tw = 0.5 + 0.5 * sin(time * (0.6 + h * 2.0) + h * 40.0);
        col += vec3(0.9, 0.9, 1.0) * smoothstep(0.08, 0.0, length(p)) * tw * (1.0 - uv.y) * 0.8;
    }
    fragColor = vec4(col * vignette(qt_TexCoord0), 1.0) * qt_Opacity;
}
