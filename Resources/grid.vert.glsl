#version 120
// Full-screen quad. The geometry in the scene graph is only a 4-vertex
// placeholder (tiny, centred on the origin, so it does not disturb the scene
// bounding box). Its corner sign picks the screen corner; positions are
// ignored. We output one stable point on each view ray, plus the camera
// vectors. The fragment shader must not use the far clip endpoint: FreeCAD
// expands that distance when an object is moved far away, and the resulting
// world-space endpoint can lose enough floating-point precision to make the
// grid disappear.
varying vec3 v_near;
varying vec3 v_camera;
varying vec3 v_view_dir;

vec3 unproject(vec2 ndc, float z)
{
    vec4 e = gl_ProjectionMatrixInverse * vec4(ndc, z, 1.0);
    e /= e.w;
    return (gl_ModelViewMatrixInverse * e).xyz;
}

void main()
{
    vec2 ndc = sign(gl_Vertex.xy);
    v_near = unproject(ndc, -1.0);
    v_camera = (gl_ModelViewMatrixInverse * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
    v_view_dir = normalize(
        (gl_ModelViewMatrixInverse * vec4(0.0, 0.0, -1.0, 0.0)).xyz);
    gl_Position = vec4(ndc, 0.0, 1.0);
}
