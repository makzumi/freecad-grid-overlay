#version 120
// Geometry pass for ambient occlusion: applied to the whole scene graph while
// it renders into a texture, writing linear view depth (see ao_buffer.frag).
varying float v_depth;

void main()
{
    v_depth = (gl_ModelViewMatrix * gl_Vertex).z;
    gl_Position = ftransform();
}
