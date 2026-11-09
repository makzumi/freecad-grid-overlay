#version 120
// Full-screen quad for the ambient-occlusion passes. As with the grid, the
// scene-graph geometry is a tiny placeholder; only the corner signs are used.
varying vec2 v_uv;

void main()
{
    vec2 ndc = sign(gl_Vertex.xy);
    v_uv = ndc * 0.5 + 0.5;
    gl_Position = vec4(ndc, 0.0, 1.0);
}
