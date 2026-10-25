#version 120
// Infinite anti-aliased grid on the document ground plane, evaluated per pixel.
// Zero CPU work per frame: spacing/LOD come from screen-space derivatives.
uniform vec3  grid_color;
uniform float base_spacing;   // millimeters in the finest "decade" unit
uniform float grid_z;         // world-space elevation of the ground plane
uniform float minor_alpha;
uniform float major_alpha;
// Per-object ground shadows. Slot i occupies SHADOW_STRIDE floats:
//   centre x, centre y, half-width, half-depth (world units)
// The compact layout keeps the shader linkable on OpenGL implementations with
// smaller fragment-uniform limits; the blur is derived from the footprint.
const int SHADOW_MAX    = 8;
const int SHADOW_STRIDE = 4;
uniform float shadow_data[SHADOW_MAX * SHADOW_STRIDE];
uniform float shadow_count;    // number of used slots
uniform float shadow_opacity;  // 0 = off (no cost)

varying vec3 v_near;
varying vec3 v_camera;
varying vec3 v_view_dir;

const float MIN_PX     = 8.0;    // finest visible line spacing in pixels (approx.)
const float DEPTH_BIAS = 1e-6;   // push grid slightly back so coplanar faces win
const float MIN_PLANE_SLOPE = 0.05;
const vec3  X_AXIS     = vec3(0.80, 0.20, 0.20);
const vec3  Y_AXIS     = vec3(0.40, 0.70, 0.20);

// Coverage of a ~1px line at integer values of c. d = cells per pixel.
float line_cov(float c, float d)
{
    float dist_px = abs(fract(c - 0.5) - 0.5) / d;
    float cov = 1.0 - clamp(dist_px, 0.0, 1.0);
    // Fade out when cells get too dense to resolve (kills moire).
    return cov * (1.0 - smoothstep(0.25, 0.5, d));
}

// Lines perpendicular to one world axis, with its own decade LOD.
// w = coordinate in base units, dw = its screen-space derivative.
float axis_grid(float w, float dw)
{
    dw = max(dw, 1e-12);
    float l = log(dw * MIN_PX) * 0.4342944819;   // log10
    float e = floor(l);
    float f = l - e;                              // 0..1 blend between decades
    float s0 = pow(10.0, e + 1.0);
    float s1 = s0 * 10.0;
    float s2 = s1 * 10.0;

    float a0 = (1.0 - f) * minor_alpha * line_cov(w / s0, dw / s0);
    float a1 = mix(major_alpha, minor_alpha, f) * line_cov(w / s1, dw / s1);
    float a2 = f * major_alpha * line_cov(w / s2, dw / s2);
    return max(a0, max(a1, a2));
}

float axis_line(float w, float dw)
{
    float dist_px = abs(w) / max(dw, 1e-12);
    return clamp(1.5 - dist_px, 0.0, 1.0);
}

void main()
{
    // Ray through this pixel. Do not derive it from v_far: FreeCAD's far clip
    // plane is sized from the model bounds and can become enormous when an
    // object is dragged away. Interpolating that distant endpoint loses
    // precision and turns the intersection into NaNs. The near point is
    // sufficient for perspective directions, while orthographic views use
    // the inverse-view direction directly.
    bool persp = gl_ProjectionMatrix[2][3] != 0.0;
    vec3 origin = persp ? v_camera : v_near;
    vec3 dir = persp ? normalize(v_near - v_camera) : normalize(v_view_dir);
    float plane_delta = grid_z - origin.z;
    // Perspective rays start at the camera, so a ray pointing away from the
    // plane can never reach it (sky above the horizon). Orthographic rays
    // are parallel and conceptually infinite: v_near sits on FreeCAD's near
    // plane, which tracks the scene bounds and can legitimately lie on the
    // far side of the ground plane. Discarding those pixels would cut the
    // grid out of part of the viewport; a negative t is valid because the
    // ortho projection stays linear along the whole ray, and the depth test
    // still lets scene geometry occlude the grid correctly.
    if (persp && dir.z * plane_delta <= 0.0)
        discard;
    bool extended = abs(dir.z) < MIN_PLANE_SLOPE;
    if (extended) {
        float toward_plane = plane_delta < 0.0 ? -1.0 : 1.0;
        dir.z = toward_plane * max(abs(dir.z), MIN_PLANE_SLOPE);
        dir = normalize(dir);
    }
    float t = plane_delta / dir.z;
    vec3  p = origin + t * dir;

    // All derivatives first, so discards below cannot corrupt them.
    vec2 w  = p.xy / base_spacing;
    vec2 dw = fwidth(w);
    float gx = axis_grid(w.x, dw.x);
    float gy = axis_grid(w.y, dw.y);
    float ax = axis_line(p.y, fwidth(p.y));   // x axis (y == 0)
    float ay = axis_line(p.x, fwidth(p.x));   // y axis (x == 0)

    // Fade toward the horizon where the plane goes edge-on.
    float grazing = max(0.15, smoothstep(0.0, 0.025, abs(dir.z)));

    vec4 clip = gl_ModelViewProjectionMatrix * vec4(p, 1.0);
    if (clip.w <= 0.0)
        discard;

    float a   = max(gx, gy);
    vec3  rgb = grid_color;
    rgb = mix(rgb, X_AXIS, ax);  a = max(a, ax * major_alpha);
    rgb = mix(rgb, Y_AXIS, ay);  a = max(a, ay * major_alpha);
    a *= grazing;

    // Soft per-object ground shadows: one ellipse per object footprint,
    // composited under the lines in the same pass / depth test as the grid.
    float sa = 0.0;
    if (shadow_opacity > 0.0 && shadow_count > 0.5) {
        for (int i = 0; i < SHADOW_MAX; i++) {
            if (float(i) >= shadow_count)
                break;
            int o = i * SHADOW_STRIDE;
            vec2  c    = vec2(shadow_data[o],     shadow_data[o + 1]);
            vec2  h    = vec2(shadow_data[o + 2], shadow_data[o + 3]);
            float blur = max(0.3 * min(h.x, h.y), 1e-6);
            vec2  q    = p.xy - c;
            // Approximate signed distance to an axis-aligned ellipse.
            float k0   = length(q / h);
            float k1   = length(q / (h * h));
            float sdf  = k0 * (k0 - 1.0) / max(k1, 1e-9);
            if (sdf > blur * 1.6)
                continue;
            float k = max(sdf, 0.0) / blur;     // 0 at/inside the footprint
            sa = max(sa, exp(-3.8 * k * k));
        }
        sa *= shadow_opacity * grazing;
    }
    float oa = a + sa * (1.0 - a);
    if (oa < 0.003)
        discard;
    vec3 orgb = (rgb * a + vec3(0.03) * sa * (1.0 - a)) / oa;

    gl_FragColor = vec4(orgb, oa);
    // Clamp instead of clip: grid outside the near/far range still draws,
    // pinned to the depth limits so model geometry keeps occluding it.
    float depth = extended ? 0.999999 :
        clip.z / clip.w * 0.5 + 0.5 + DEPTH_BIAS;
    gl_FragDepth = clamp(depth, 0.0, 0.999999);
}
