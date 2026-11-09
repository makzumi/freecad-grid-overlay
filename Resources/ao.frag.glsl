#version 120
// EXPERIMENTAL screen-space ambient occlusion.
//
// gbuffer holds each pixel's linear depth, rendered with the live camera
// into a texture. For each model pixel, nearby visible surface
// points are reconstructed and the pixel is darkened by how much they rise
// above its tangent plane (normal-weighted obscurance). This pass
// renders into a texture (r = occlusion, a = 1 on model pixels); the blur
// pass in ao_blur.frag removes the dither and composites it on screen.
uniform sampler2D gbuffer;    // 24-bit linear depth, see ao_buffer.frag
uniform vec2  texel;          // 1 / buffer texture size in texels
uniform float screen_height;  // viewport height in screen pixels
uniform float radius_px;      // sampling radius, in screen pixels
uniform float strength;       // 0..1 overall darkening

varying vec2 v_uv;

const int   SAMPLES = 8;     // x 16 tile rotations = 128 effective
const float GOLDEN_ANGLE = 2.3999632;
const float ANGLE_BIAS = 0.15;     // ~9 degrees above the tangent plane

vec2 near_far()
{
    float a = gl_ProjectionMatrix[2][2];
    float b = gl_ProjectionMatrix[3][2];
    if (gl_ProjectionMatrix[2][3] != 0.0)
        return vec2(b / (a - 1.0), b / (a + 1.0));
    return vec2((b + 1.0) / a, (b - 1.0) / a);
}

// Packed values must never be interpolated: always read texel centres.
vec2 snap(vec2 uv)
{
    return (floor(uv / texel) + 0.5) * texel;
}

bool empty(vec4 g)
{
    return g.r + g.g + g.b < 0.5 / 255.0;
}

// View-space z of a buffer texel.
float view_z(vec4 g, vec2 nf)
{
    vec3 bytes = floor(g.rgb * 255.0 + 0.5);
    float x = bytes.r * 65536.0 + bytes.g * 256.0 + bytes.b;
    float d = 1.0 - (x - 1.0) / 16777214.0;
    return -(nf.x + d * (nf.y - nf.x));
}

// View-space point on this pixel's ray at view depth z, for both
// projections: interpolate between two points of the ray.
vec3 position_at(vec2 uv, float z)
{
    vec2 ndc = uv * 2.0 - 1.0;
    vec4 a = gl_ProjectionMatrixInverse * vec4(ndc, -1.0, 1.0);
    vec4 b = gl_ProjectionMatrixInverse * vec4(ndc, 0.0, 1.0);
    a.xyz /= a.w;
    b.xyz /= b.w;
    return a.xyz + (b.xyz - a.xyz) * ((z - a.z) / (b.z - a.z));
}

// Reconstructed view-space position of a texel, or z = 0 if empty.
vec3 point_at(vec2 uv, vec2 nf, out bool hit)
{
    uv = snap(uv);
    // Bias -16 pins the lookup to the full-resolution level. The sample
    // coordinates jump between neighbouring pixels (each uses a different
    // rotation), which would otherwise make the GPU pick a smaller mip level
    // and average packed bytes into garbage.
    vec4 g = texture2D(gbuffer, uv, -16.0);
    hit = !empty(g);
    return hit ? position_at(uv, view_z(g, nf)) : vec3(0.0);
}

void main()
{
    vec2 nf = near_far();
    bool hit;
    vec3 P = point_at(v_uv, nf, hit);
    if (!hit)
        discard;                                  // background
    bool persp = gl_ProjectionMatrix[2][3] != 0.0;

    // Normal from neighbouring texels. On each axis use the side whose
    // depth is closer, so silhouettes and creases do not bend the normal.
    bool hr, hl, hu, hd;
    vec3 pr = point_at(v_uv + vec2(texel.x, 0.0), nf, hr);
    vec3 pl = point_at(v_uv - vec2(texel.x, 0.0), nf, hl);
    vec3 pu = point_at(v_uv + vec2(0.0, texel.y), nf, hu);
    vec3 pd = point_at(v_uv - vec2(0.0, texel.y), nf, hd);
    bool use_r = hr && (!hl || abs(pr.z - P.z) < abs(P.z - pl.z));
    bool use_u = hu && (!hd || abs(pu.z - P.z) < abs(P.z - pd.z));
    if (!(use_r || hl) || !(use_u || hd))
        discard;                                  // isolated texel
    vec3 dx = use_r ? pr - P : P - pl;
    vec3 dy = use_u ? pu - P : P - pd;
    vec3 N = normalize(cross(dx, dy));
    vec3 to_eye = persp ? normalize(-P) : vec3(0.0, 0.0, 1.0);
    if (dot(N, to_eye) < 0.0)
        N = -N;

    // World size of one screen pixel. The texture may be larger or smaller
    // than the screen, but the radius is meant in screen pixels.
    float px_world = 2.0 / (screen_height * gl_ProjectionMatrix[1][1]) *
                     (persp ? -P.z : 1.0);
    float r = radius_px * px_world;

    // Rotate the sample pattern over a 4x4 pixel tile (a scrambled 0..15
    // index, 7 is coprime with 16). The blur pass averages exactly one tile,
    // so the 16 rotations combine into 16 x SAMPLES effective samples.
    vec2 cell = mod(floor(gl_FragCoord.xy), 4.0);
    float index = mod((cell.x + 4.0 * cell.y) * 7.0, 16.0);
    float angle = 6.2831853 * (index + 0.5) / 16.0;
    vec3 helper = abs(N.z) < 0.999 ? vec3(0.0, 0.0, 1.0) : vec3(1.0, 0.0, 0.0);
    vec3 t = normalize(cross(helper, N));
    t = t * cos(angle) + cross(N, t) * sin(angle);
    vec3 b = cross(N, t);

    // Normal-weighted obscurance: sample points on a disk in the tangent
    // plane, look up the surface actually visible there, and measure how far
    // that surface rises above the tangent plane (cosine to the normal). A
    // flat face rises 0 by construction, so stored depth/normal precision
    // cannot make it shade itself; ANGLE_BIAS absorbs what error remains.
    // Lookups and reconstruction both use the same texel centre, so the
    // reconstructed point is exactly what the buffer holds.
    float occlusion = 0.0;
    for (int i = 0; i < SAMPLES; i++) {
        float fi = float(i);
        float a = fi * GOLDEN_ANGLE;
        float k = (fi + 0.5) / float(SAMPLES);
        float scale = r * mix(0.15, 1.0, sqrt(k));    // even over the disk
        vec3 S = P + (t * cos(a) + b * sin(a)) * scale;

        vec4 clip = gl_ProjectionMatrix * vec4(S, 1.0);
        vec2 suv = clip.xy / clip.w * 0.5 + 0.5;
        if (suv.x <= 0.0 || suv.x >= 1.0 || suv.y <= 0.0 || suv.y >= 1.0)
            continue;
        bool sh;
        vec3 v = point_at(suv, nf, sh) - P;
        if (!sh)
            continue;
        float d2 = dot(v, v);
        if (d2 < 1e-12)
            continue;
        float rise = dot(v, N) * inversesqrt(d2) - ANGLE_BIAS;
        // Occluders beyond the radius (across a gap, far in front) fade out.
        float falloff = clamp(1.0 - d2 / (4.0 * r * r), 0.0, 1.0);
        occlusion += max(rise, 0.0) * falloff;
    }
    float ao = occlusion / float(SAMPLES) / (1.0 - ANGLE_BIAS);
    ao = clamp(ao * strength * 2.5, 0.0, 1.0);
    gl_FragColor = vec4(ao, 0.0, 0.0, 1.0);
}
