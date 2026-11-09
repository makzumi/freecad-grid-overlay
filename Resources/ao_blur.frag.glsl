#version 120
// Final ambient-occlusion pass: a 4x4 box average of the raw AO texture.
// The AO pass rotates its sample pattern over a 4x4 pixel tile, so any 4x4
// window contains every rotation exactly once and the dither averages out.
// Only model pixels (alpha 1) contribute, so nothing bleeds onto background.
// Output is black with alpha = occlusion: blending multiplies the existing
// colour by (1 - occlusion).
uniform sampler2D ao_tex;
uniform vec2 texel;
uniform float fade;           // 0..1 fade-in after the view settles

varying vec2 v_uv;

void main()
{
    if (texture2D(ao_tex, v_uv, -16.0).a < 0.5)
        discard;
    float sum = 0.0;
    float count = 0.0;
    for (int y = -2; y < 2; y++) {
        for (int x = -2; x < 2; x++) {
            vec4 s = texture2D(ao_tex, v_uv + vec2(float(x), float(y)) * texel, -16.0);
            if (s.a > 0.5) {
                sum += s.r;
                count += 1.0;
            }
        }
    }
    float ao = sum / max(count, 1.0) * fade;
    if (ao < 0.004)
        discard;
    gl_FragColor = vec4(0.0, 0.0, 0.0, ao);
}
