#version 120
// Geometry pass for ambient occlusion. Writes linear depth between the near
// and far planes as a 24-bit integer split over r (high), g, b (low); this
// Coin build clamps its float scene-texture formats to [0, 1]. Normals are
// rebuilt from this depth in ao.frag. The background is cleared to zero;
// encoded depth is never zero.
varying float v_depth;

// Near/far planes from the projection matrix, for either projection.
vec2 near_far()
{
    float a = gl_ProjectionMatrix[2][2];
    float b = gl_ProjectionMatrix[3][2];
    if (gl_ProjectionMatrix[2][3] != 0.0)
        return vec2(b / (a - 1.0), b / (a + 1.0));
    return vec2((b + 1.0) / a, (b - 1.0) / a);
}

void main()
{
    vec2 nf = near_far();
    float d = clamp((-v_depth - nf.x) / (nf.y - nf.x), 0.0, 1.0);
    float x = floor((1.0 - d) * 16777214.0 + 1.5);   // 1 .. 2^24-1, never 0
    float hi = floor(x / 65536.0);
    x -= hi * 65536.0;
    float mid = floor(x / 256.0);
    float lo = x - mid * 256.0;
    gl_FragColor = vec4(hi, mid, lo, 255.0) / 255.0;
}
