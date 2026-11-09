#version 120
// Infinite anti-aliased grid evaluated per pixel. Zero CPU work per frame:
// spacing/LOD come from screen-space derivatives, and the grid plane is chosen
// here from the camera direction.
//
// Plane selection: the ground (XY) plane is the default. When the camera looks
// dead-on along world Y (front/rear) or world X (left/right) and side planes
// are enabled, the grid switches to the XZ or YZ plane through the origin and
// is drawn as a backdrop behind all geometry. The XY plane is edge-on in those
// views, so it would be invisible anyway.
uniform vec3  grid_color;
uniform float base_spacing;   // millimeters in the finest "decade" unit
uniform float grid_z;         // world-space elevation of the ground plane
uniform float minor_alpha;
uniform float major_alpha;
uniform float side_planes;    // > 0.5: allow XZ/YZ grids in dead-on views
uniform float axis_lines;     // > 0.5: draw the coloured axis lines

// Ground shadow: a blurred top-down footprint mask rendered on the CPU from
// the visible geometry and bound as a single-channel texture on unit 0.
// shadow_rect = (x0, y0, 1/width, 1/height) of the texture in world XY.
uniform sampler2D shadow_tex;
uniform vec4  shadow_rect;
uniform float shadow_opacity;  // 0 = off (no texture fetch)

varying vec3 v_near;
varying vec3 v_camera;
varying vec3 v_view_dir;

const float MIN_PX     = 8.0;    // finest visible line spacing in pixels (approx.)
const float DEPTH_BIAS = 1e-6;   // push grid slightly back so coplanar faces win
const float BACKDROP_DEPTH = 0.999999;
// cos(~0.5 deg): FreeCAD's standard views are exact, so this only has to
// absorb floating-point noise, while orbiting through a side view does not
// flicker the vertical grid on for more than an instant.
const float SNAP_COS   = 0.99996;
// Below this slope the plane intersection becomes numerically unstable: a
// one-pixel change in the view ray can move the hit point many kilometres.
// Fade the grid into the horizon and never replace the ray with a made-up
// slope.
const float MIN_PLANE_SLOPE  = 0.025;
const float FADE_PLANE_SLOPE = 0.10;
const float MAX_RAY_DISTANCE  = 1e8; // 100 km in FreeCAD's millimetres
const vec3  X_AXIS     = vec3(0.80, 0.20, 0.20);
const vec3  Y_AXIS     = vec3(0.40, 0.70, 0.20);
const vec3  Z_AXIS     = vec3(0.25, 0.45, 0.85);

// World <-> plane space. In plane space the grid lies in .xy and .z is the
// plane normal, so one code path handles all three planes.
//   0: XY (u=X, v=Y, n=Z)   1: XZ (u=X, v=Z, n=Y)   2: YZ (u=Y, v=Z, n=X)
vec3 to_plane(vec3 v, int m)
{
    return m == 1 ? v.xzy : (m == 2 ? v.yzx : v);
}

vec3 from_plane(vec3 q, int m)
{
    return m == 1 ? q.xzy : (m == 2 ? q.zxy : q);
}

// Coverage of a ~1px line at integer values of c. d = cells per pixel.
float line_cov(float c, float d)
{
    float dist_px = abs(fract(c - 0.5) - 0.5) / d;
    float cov = 1.0 - clamp(dist_px, 0.0, 1.0);
    // Fade out when cells get too dense to resolve (kills moire).
    return cov * (1.0 - smoothstep(0.25, 0.5, d));
}

// Lines perpendicular to one plane axis, with its own decade LOD.
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
    // Ray through this pixel. Do not derive it from a far-plane point:
    // FreeCAD's far clip plane is sized from the model bounds and can become
    // enormous when an object is dragged away, and the lost precision turns
    // the intersection into NaNs. The near point is sufficient for
    // perspective directions, while orthographic views use the inverse-view
    // direction directly.
    bool persp = gl_ProjectionMatrix[2][3] != 0.0;
    vec3 view_dir = normalize(v_view_dir);

    int plane = 0;
    if (side_planes > 0.5) {
        if (abs(view_dir.y) > SNAP_COS)
            plane = 1;
        else if (abs(view_dir.x) > SNAP_COS)
            plane = 2;
    }
    float plane_h = plane == 0 ? grid_z : 0.0;

    vec3 origin = to_plane(persp ? v_camera : v_near, plane);
    vec3 dir = to_plane(persp ? normalize(v_near - v_camera) : view_dir, plane);
    float plane_delta = plane_h - origin.z;
    // Perspective rays start at the camera, so a ray pointing away from the
    // plane can never reach it (sky above the horizon). Orthographic rays
    // are parallel and conceptually infinite: v_near sits on FreeCAD's near
    // plane, which tracks the scene bounds and can legitimately lie on the
    // far side of the plane. A negative t is valid there because the ortho
    // projection stays linear along the whole ray.
    if (persp && dir.z * plane_delta <= 0.0)
        discard;
    float plane_slope = abs(dir.z);
    if (plane_slope < MIN_PLANE_SLOPE)
        discard;
    float t = plane_delta / dir.z;
    if (abs(t) > MAX_RAY_DISTANCE)
        discard;
    vec3 q = origin + t * dir;          // hit point in plane space
    vec3 p = from_plane(q, plane);      // hit point in world space

    // Grid coordinates. On the side planes the vertical axis is world Z, so
    // measure it from the ground height: the horizontal zero line and the
    // grid rows then line up with the ground grid seen in other views.
    vec2 g = plane == 0 ? q.xy : vec2(q.x, q.y - grid_z);

    // All derivatives first, so discards below cannot corrupt them.
    vec2 w  = g / base_spacing;
    vec2 dw = fwidth(w);
    float gx = axis_grid(w.x, dw.x);
    float gy = axis_grid(w.y, dw.y);
    float show_axes = axis_lines > 0.5 ? 1.0 : 0.0;
    float au = show_axes * axis_line(g.y, fwidth(g.y));   // u axis (v == 0)
    float av = show_axes * axis_line(g.x, fwidth(g.x));   // v axis (u == 0)

    // Fade toward the horizon where the plane goes edge-on. Alpha may be
    // reduced, but the hit point must never be altered to achieve it.
    float grazing = smoothstep(MIN_PLANE_SLOPE, FADE_PLANE_SLOPE,
                               plane_slope);

    vec4 clip = gl_ModelViewProjectionMatrix * vec4(p, 1.0);
    if (clip.w <= 0.0)
        discard;

    vec3 u_color = plane == 2 ? Y_AXIS : X_AXIS;
    vec3 v_color = plane == 0 ? Y_AXIS : Z_AXIS;
    float a   = max(gx, gy);
    vec3  rgb = grid_color;
    rgb = mix(rgb, u_color, au);  a = max(a, au * major_alpha);
    rgb = mix(rgb, v_color, av);  a = max(a, av * major_alpha);
    a *= grazing;

    // Ground shadow (XY plane only), composited under the lines in the same
    // pass and depth test as the grid. The texture has an empty border and
    // linear filtering, so the clamp below only guards the lookup.
    float sa = 0.0;
    if (plane == 0 && shadow_opacity > 0.0) {
        vec2 uv = (p.xy - shadow_rect.xy) * shadow_rect.zw;
        if (uv.x > 0.0 && uv.x < 1.0 && uv.y > 0.0 && uv.y < 1.0)
            sa = texture2D(shadow_tex, uv).r * shadow_opacity * grazing;
    }
    float oa = a + sa * (1.0 - a);
    if (oa < 0.003)
        discard;
    vec3 orgb = (rgb * a + vec3(0.03) * sa * (1.0 - a)) / oa;

    gl_FragColor = vec4(orgb, oa);
    if (plane != 0) {
        // Side-view grids are a backdrop: always behind the model.
        gl_FragDepth = BACKDROP_DEPTH;
    } else {
        // Clamp instead of clip: grid outside the near/far range still draws,
        // pinned to the depth limits so model geometry keeps occluding it.
        float depth = clip.z / clip.w * 0.5 + 0.5 + DEPTH_BIAS;
        gl_FragDepth = clamp(depth, 0.0, BACKDROP_DEPTH);
    }
}
