# -*- coding: utf-8 -*-
"""Grid Overlay add-on for FreeCAD's modern namespaced layout.

The grid is a single full-screen quad drawn by a GLSL shader: the fragment
shader intersects each pixel's view ray with the model ground plane and draws
anti-aliased, level-of-detail-blended lines. There is no per-frame Python work;
a low-frequency lifecycle check only repairs attachment after a view rebuild.
"""
import os
import math
import importlib

import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

try:
    import numpy as np
except Exception:       # shadows need numpy; the grid itself does not
    np = None

# FreeCAD supports both exec-style startup modules and normal Python module
# imports. Publish the host modules explicitly so the helper functions behave
# the same way in either loading mode.
globals().update({"App": App, "importlib": importlib})


def _load_qt():
    """Load the Qt binding exposed by FreeCAD, across 26.x and 27.x.

    ``PySide`` is FreeCAD's compatibility module and is intentionally tried
    first.  Some 26.x installations expose PySide2 while newer builds expose
    PySide6, so keep the concrete bindings as fallbacks rather than assuming a
    particular Qt major version.
    """
    errors = []
    for binding in ("PySide", "PySide2", "PySide6"):
        try:
            core = importlib.import_module(binding + ".QtCore")
            gui = importlib.import_module(binding + ".QtGui")
            try:
                widgets = importlib.import_module(binding + ".QtWidgets")
            except Exception:
                # FreeCAD's PySide compatibility module exposes widgets from
                # QtGui, as used by some older builds.
                widgets = gui
            return core, gui, widgets, core.Signal
        except Exception as exc:
            errors.append("%s: %s" % (binding, exc))
    message = "Grid Overlay: Qt import failed (%s)\n" % "; ".join(errors)
    App.Console.PrintError(message)
    raise ImportError(message)


QtCore, QtGui, QtWidgets, Signal = _load_qt()
globals().update({
    "QtCore": QtCore, "QtGui": QtGui, "QtWidgets": QtWidgets,
    "Signal": Signal,
})

def _addon_root():
    """Find the installed addon root without assuming its folder name.

    Modern FreeCAD addons are loaded from
    ``<addon-root>/freecad/<module>/init_gui.py`` and receive ``__file__``.
    Walk upward until the manifest is found so the repository can be copied,
    symlinked, or renamed freely.
    """
    try:
        current = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        raise RuntimeError(
            "Grid Overlay requires FreeCAD's modern namespaced addon layout")
    for _ in range(6):
        if os.path.isfile(os.path.join(current, "package.xml")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    raise RuntimeError("Grid Overlay package.xml was not found above %s" % current)


ADDON_DIR = _addon_root()
SETTINGS = QtCore.QSettings("GridOverlay", "GridOverlay")


def _doc_name(doc):
    """Best-effort document name from an observer argument."""
    name = getattr(doc, "Name", None)
    if name is None and isinstance(doc, str):
        name = doc
    return name


globals()["_doc_name"] = _doc_name


def _freecad_major_version():
    """Return FreeCAD's major release number, or ``None`` if unavailable."""
    try:
        version = App.Version()
        if isinstance(version, (tuple, list)):
            version = version[0]
        return int(str(version).split(".", 1)[0])
    except Exception:
        return None


FREECAD_MAJOR_VERSION = _freecad_major_version()
SUPPORTED_FREECAD_MAJOR_VERSIONS = (26, 27)
if (FREECAD_MAJOR_VERSION is not None and
        FREECAD_MAJOR_VERSION not in SUPPORTED_FREECAD_MAJOR_VERSIONS):
    App.Console.PrintWarning(
        "Grid Overlay: validated for FreeCAD 26.x and 27.x; detected %s.x\n"
        % FREECAD_MAJOR_VERSION)


def _qt_enum(name):
    """Read a Qt enum in both its Qt5 and Qt6 forms."""
    value = getattr(QtCore.Qt, name, None)
    if value is not None:
        return value
    scoped = getattr(QtCore.Qt, "Orientation", None)
    if scoped is not None:
        value = getattr(scoped, name, None)
    if value is None:
        raise AttributeError("Qt enum %s is unavailable" % name)
    return value


def _dialog_button(name):
    """Read QDialogButtonBox flags in both Qt5 and Qt6 forms."""
    box = QtWidgets.QDialogButtonBox
    value = getattr(box, name, None)
    if value is not None:
        return value
    scoped = getattr(box, "StandardButton", None)
    if scoped is not None:
        value = getattr(scoped, name, None)
    if value is None:
        raise AttributeError("QDialogButtonBox button %s is unavailable" % name)
    return value


QT_HORIZONTAL = _qt_enum("Horizontal")

# In exec-style startup loading, names assigned by exec() are not visible to
# functions/classes created by the exec unless they are explicitly published
# to its globals. This is harmless for normal package imports and preserves
# compatibility with FreeCAD's older loader.
globals().update({
    "os": os, "math": math, "np": np,
    "App": App, "Gui": Gui, "coin": coin,
    "QtCore": QtCore, "QtGui": QtGui, "QtWidgets": QtWidgets,
    "Signal": Signal, "ADDON_DIR": ADDON_DIR, "SETTINGS": SETTINGS,
    "QT_HORIZONTAL": QT_HORIZONTAL,
    "_dialog_button": _dialog_button,
})


def _world_placement(obj):
    """Return an object's placement in document coordinates.

    FreeCAD 26.3 introduced ``getPlacementOf`` as the link-aware replacement
    for the deprecated ``getGlobalPlacement`` Python method.  Keep the old
    call as a compatibility fallback for earlier 26.x builds.
    """
    try:
        parents = getattr(obj, "Parents", None) or []
        if parents:
            root, path = parents[0]
            subname = "%s%s" % (path or "", obj.Name)
            return root.getPlacementOf(subname, obj)
        return obj.Placement
    except Exception:
        try:
            return obj.getGlobalPlacement()
        except Exception:
            return getattr(obj, "Placement", None)


globals()["_world_placement"] = _world_placement


def _same_ref(left, right):
    """Compare Pivy wrappers without relying only on Python object identity."""
    if left is right:
        return True
    try:
        return bool(left == right)
    except Exception:
        return False


globals()["_same_ref"] = _same_ref


def _publish(obj):
    """Decorator: make a top-level def/class visible to the exec() globals."""
    globals()[obj.__name__] = obj
    return obj


globals()["_publish"] = _publish

DEFAULTS = {
    "enabled": True,
    "opacity": 0.65,
    "color": "#808080",
    "base_spacing": 1.0,
    "grid_unit": "mm",
    "shadow_enabled": True,
    "shadow_opacity": 0.30,
    "shadow_softness": 0.45,
    "shadow_spread": 0.02,
    "grid_z_offset": 0.0,       # millimeters, independent of the grid unit
    "side_planes": True,
    "axis_lines": True,
}
BOOL_SETTINGS = ("enabled", "shadow_enabled", "side_planes", "axis_lines")
UNIT_SETTINGS = ("opacity", "shadow_opacity", "shadow_softness",
                 "shadow_spread")
_settings_cache = {}
globals().update({
    "DEFAULTS": DEFAULTS, "BOOL_SETTINGS": BOOL_SETTINGS,
    "UNIT_SETTINGS": UNIT_SETTINGS, "_settings_cache": _settings_cache,
})

GRID_UNIT_OPTIONS = (
    ("mm", "Millimeters", 1.0),
    ("cm", "Centimeters", 10.0),
    ("m", "Meters", 1000.0),
    ("in", "Inches", 25.4),
    ("ft", "Feet", 304.8),
)
GRID_UNIT_FACTORS = dict((key, factor)
                         for key, _label, factor in GRID_UNIT_OPTIONS)
globals().update({
    "GRID_UNIT_OPTIONS": GRID_UNIT_OPTIONS,
    "GRID_UNIT_FACTORS": GRID_UNIT_FACTORS,
})


def _parse_setting(key, value):
    """Validate a raw QSettings value (strings on some platforms)."""
    if key in BOOL_SETTINGS:
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes", "on")
    if key == "grid_unit":
        value = str(value).strip().lower()
        return value if value in GRID_UNIT_FACTORS else DEFAULTS[key]
    if isinstance(DEFAULTS[key], float):
        try:
            result = float(value)
        except Exception:
            return DEFAULTS[key]
        if not math.isfinite(result):
            return DEFAULTS[key]
        if key == "base_spacing":
            return max(0.01, min(100.0, result))
        if key == "grid_z_offset":
            return max(-1e7, min(1e7, result))
        return max(0.0, min(1.0, result))
    return str(value)


globals()["_parse_setting"] = _parse_setting


@_publish
def setting(key):
    """Read a validated setting. Values are cached: the lifecycle timer and
    shadow updates call this often, and only save_settings changes them."""
    try:
        return _settings_cache[key]
    except KeyError:
        value = _parse_setting(key, SETTINGS.value(key, DEFAULTS[key]))
        _settings_cache[key] = value
        return value


@_publish
def grid_spacing_mm():
    """Return the selected grid spacing in FreeCAD's internal millimeters."""
    return setting("base_spacing") * GRID_UNIT_FACTORS[setting("grid_unit")]


@_publish
def save_settings(values):
    for key, value in values.items():
        SETTINGS.setValue(key, value)
        _settings_cache.pop(key, None)
    SETTINGS.sync()


def _base_nodes():
    """Pick-proof, unlit state shared by the grid and shadow."""
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    return pick, light


globals()["_base_nodes"] = _base_nodes


def _depth_no_write():
    """SoDepthBuffer with depth *writes* off (testing stays on), or None.

    Set through set(): on a node, .write is SoBase.write(), not the field.
    """
    try:
        node = coin.SoDepthBuffer()
        node.set("write FALSE")
        return node
    except Exception as exc:
        App.Console.PrintWarning(
            "Grid Overlay: SoDepthBuffer unavailable: %s\n" % exc)
        return None


globals()["_depth_no_write"] = _depth_no_write


def _pow2_at_least(value):
    """Smallest power of two >= value (at least 8)."""
    size = 8
    while size < value:
        size *= 2
    return size


def _rasterize_triangles(tris, width, height):
    """Boolean coverage mask of 2-D triangles given in pixel coordinates.

    tris is an (N, 3, 2) array. Vectorised scanline conversion: one entry
    per (triangle, covered pixel row), with each row's span accumulated in a
    difference array, so there is no per-triangle Python loop.
    """
    mask = np.zeros((height, width), dtype=bool)
    if not len(tris):
        return mask
    ys = tris[:, :, 1]
    first = np.maximum(np.ceil(ys.min(axis=1) - 0.5), 0).astype(np.int64)
    last = np.minimum(np.floor(ys.max(axis=1) - 0.5), height - 1).astype(np.int64)
    counts = np.maximum(last - first + 1, 0)
    total = int(counts.sum())
    if total == 0:
        return mask
    tri = np.repeat(np.arange(len(tris)), counts)
    starts = np.cumsum(counts) - counts
    rows = first[tri] + (np.arange(total) - starts[tri])
    yc = rows + 0.5                                  # pixel-centre rows
    left = np.full(total, np.inf)
    right = np.full(total, -np.inf)
    for a, b in ((0, 1), (1, 2), (2, 0)):
        xa, ya = tris[tri, a, 0], tris[tri, a, 1]
        xb, yb = tris[tri, b, 0], tris[tri, b, 1]
        dy = yb - ya
        hit = ((np.minimum(ya, yb) <= yc) & (yc <= np.maximum(ya, yb)) &
               (dy != 0))
        x = xa + (yc - ya) * (xb - xa) / np.where(hit, dy, 1.0)
        left = np.where(hit, np.minimum(left, x), left)
        right = np.where(hit, np.maximum(right, x), right)
    c0 = np.ceil(left - 0.5)
    c1 = np.floor(right - 0.5)
    ok = np.isfinite(c0) & np.isfinite(c1)
    rows = rows[ok]
    c0 = np.maximum(c0[ok], 0).astype(np.int64)
    c1 = np.minimum(c1[ok], width - 1).astype(np.int64)
    keep = c1 >= c0
    rows, c0, c1 = rows[keep], c0[keep], c1[keep]
    diff = np.zeros((height, width + 1), dtype=np.int32)
    np.add.at(diff, (rows, c0), 1)
    np.add.at(diff, (rows, c1 + 1), -1)
    mask[:] = np.cumsum(diff[:, :width], axis=1) > 0
    return mask


def _box_blur(img, radius, axis):
    """Box filter of width 2*radius+1 along one axis (zero padded)."""
    pad = [(0, 0), (0, 0)]
    pad[axis] = (radius + 1, radius)
    summed = np.cumsum(np.pad(img, pad), axis=axis)
    count = img.shape[axis]
    width = 2 * radius + 1
    upper = np.take(summed, np.arange(width, width + count), axis=axis)
    lower = np.take(summed, np.arange(0, count), axis=axis)
    return (upper - lower) / float(width)


def _gaussian_blur(img, sigma):
    """Three box passes per axis approximate a Gaussian of this sigma."""
    out = img.astype(np.float32)
    radius = int(round((math.sqrt(4.0 * sigma * sigma + 1.0) - 1.0) * 0.5))
    if radius < 1:
        return out
    for axis in (0, 1):
        for _ in range(3):
            out = _box_blur(out, radius, axis)
    return out


globals().update({
    "_pow2_at_least": _pow2_at_least,
    "_rasterize_triangles": _rasterize_triangles,
    "_box_blur": _box_blur, "_gaussian_blur": _gaussian_blur,
})


@_publish
class ShaderGrid:
    """Infinite ground grid drawn by a shader on a 4-vertex placeholder quad."""

    # SoRenderManager::Superimposition flags. Keep the existing depth buffer
    # so the grid remains behind model geometry, but do not clear it before
    # rendering the independent grid pass.
    _SUPERIMPOSE_ZBUFFER = 0x0001
    _SUPERIMPOSE_AUTOREDRAW = 0x0004

    # Placeholder corners. The vertex shader only uses their sign, so they can
    # be tiny: that keeps the scene bounding box (near/far clipping, view fit)
    # unaffected by the grid.
    _EPS = 1e-6

    def __init__(self, view, doc_name=None):
        self.view = view
        self.doc_name = doc_name
        self.sg = view.getSceneGraph()
        self.render_manager = None
        self.render_scene_graph = None
        self.superimposition = None
        self.overlay_camera = None
        self._scene_render_culling = None
        self.visible = True

        shader_dir = os.path.join(ADDON_DIR, "Resources")
        vertex = coin.SoVertexShader()
        vertex.sourceProgram.setValue(os.path.join(shader_dir, "grid.vert.glsl"))
        fragment = coin.SoFragmentShader()
        fragment.sourceProgram.setValue(os.path.join(shader_dir, "grid.frag.glsl"))

        self.grid_color = coin.SoShaderParameter3f()
        self.grid_color.name = "grid_color"
        self.base_spacing = coin.SoShaderParameter1f()
        self.base_spacing.name = "base_spacing"
        self.grid_z = coin.SoShaderParameter1f()
        self.grid_z.name = "grid_z"
        self.grid_z.value = 0.0
        self.minor_alpha = coin.SoShaderParameter1f()
        self.minor_alpha.name = "minor_alpha"
        self.major_alpha = coin.SoShaderParameter1f()
        self.major_alpha.name = "major_alpha"
        self.side_planes = coin.SoShaderParameter1f()
        self.side_planes.name = "side_planes"
        self.axis_lines = coin.SoShaderParameter1f()
        self.axis_lines.name = "axis_lines"
        self.shadow_opacity = coin.SoShaderParameter1f()
        self.shadow_opacity.name = "shadow_opacity"
        self.shadow_opacity.value = 0.0
        self.shadow_rect = coin.SoShaderParameter4f()
        self.shadow_rect.name = "shadow_rect"
        self.shadow_rect.value = coin.SbVec4f(0.0, 0.0, 1.0, 1.0)
        shadow_sampler = coin.SoShaderParameter1i()
        shadow_sampler.name = "shadow_tex"
        shadow_sampler.value = 0                    # texture unit 0
        self.shadow_visible = False
        self._triangle_cache = {}       # object name -> (key, XY triangles)
        self._shadow_key = None
        self._has_shadow = False
        self._poll_signature = None
        self.ground_ready = False
        params = [self.grid_color, self.base_spacing, self.grid_z,
                  self.minor_alpha, self.major_alpha,
                  self.side_planes, self.axis_lines,
                  self.shadow_opacity, self.shadow_rect, shadow_sampler]
        fragment.parameter.setValues(0, len(params), params)

        # Footprint mask for the ground shadow. Linear filtering without
        # mipmaps (textureQuality < 0.5) keeps the lookup independent of
        # derivatives, which are undefined after the shader's discards.
        self.shadow_tex = coin.SoTexture2()
        self.shadow_tex.wrapS = coin.SoTexture2.CLAMP
        self.shadow_tex.wrapT = coin.SoTexture2.CLAMP
        self._set_shadow_image(1, 1, b"\0")
        texture_quality = coin.SoComplexity()
        texture_quality.textureQuality = 0.3

        program = coin.SoShaderProgram()
        program.shaderObject.set1Value(0, vertex)
        program.shaderObject.set1Value(1, fragment)

        e = self._EPS
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, 4, [(-e, -e, 0), (e, -e, 0), (e, e, 0), (-e, e, 0)])
        face = coin.SoFaceSet()
        face.numVertices.setValue(4)

        # A transparent material only flags the shape for the blended pass;
        # the shader outputs its own colour and alpha.
        flag = coin.SoMaterial()
        flag.transparency.setValue(0.5)

        sep = coin.SoSeparator()
        # The placeholder sits at the origin; without this Coin would cull the
        # whole grid whenever the origin is off screen.
        sep.renderCulling = coin.SoSeparator.OFF
        depth = _depth_no_write()   # blended grid must not hide the shadow
        if depth is not None:
            sep.addChild(depth)
        sep.addChild(flag)
        sep.addChild(texture_quality)
        sep.addChild(self.shadow_tex)
        sep.addChild(program)
        sep.addChild(coords)
        sep.addChild(face)

        # Keep the switch below an uncullable separator.  A switch does not
        # expose renderCulling itself, and some Coin versions can otherwise
        # cull the whole overlay from the placeholder's tiny world-space box.
        self.root = coin.SoSeparator()
        self.root.renderCulling = coin.SoSeparator.OFF
        for node in _base_nodes():
            self.root.addChild(node)
        self.content = coin.SoSwitch()
        self.content.addChild(sep)
        self.content.whichChild = -3       # SO_SWITCH_ALL
        self.root.addChild(self.content)
        if not self._attach_superimposition(view):
            # Compatibility fallback for older FreeCAD/Coin builds without a
            # render-manager superimposition API. In the normal scene graph,
            # disable culling at its root because the placeholder is tiny and
            # centred at the origin.
            self._disable_scene_culling()
            self.sg.addChild(self.root)
        self.apply_settings()

    def _disable_scene_culling(self):
        try:
            self._scene_render_culling = self.sg.renderCulling.getValue()
            self.sg.renderCulling = coin.SoSeparator.OFF
        except Exception:
            self._scene_render_culling = None

    def _attach_superimposition(self, view):
        """Render outside model culling while retaining the active world camera."""
        camera = None
        camera_added = False
        try:
            viewer = view.getViewer()
            render_manager = viewer.getSoRenderManager()
            # A superimposition normally has HUD-style matrices. Including the
            # live FreeCAD camera makes the shader's inverse matrices describe
            # the same world view as the model, so the grid is not camera-flat.
            camera = render_manager.getCamera()
            if camera is None:
                camera = view.getCameraNode()
            if camera is not None:
                self.root.insertChild(camera, 0)
                camera_added = True
                try:
                    render_manager.setCamera(camera)
                except Exception:
                    pass
            flags = self._SUPERIMPOSE_ZBUFFER | self._SUPERIMPOSE_AUTOREDRAW
            superimposition = render_manager.addSuperimposition(self.root, flags)
            if superimposition is None:
                if camera_added:
                    self.root.removeChild(camera)
                return False
            self.render_manager = render_manager
            self.render_scene_graph = render_manager.getSceneGraph()
            self.superimposition = superimposition
            self.overlay_camera = camera
            return True
        except Exception:
            if camera_added:
                try:
                    self.root.removeChild(camera)
                except Exception:
                    pass
            self.render_manager = None
            self.render_scene_graph = None
            self.superimposition = None
            self.overlay_camera = None
            return False

    def apply_settings(self):
        """Push settings into shader uniforms. Call on change only."""
        color = QtGui.QColor(setting("color"))
        strength = setting("opacity")
        self.grid_color.value = (color.redF(), color.greenF(), color.blueF())
        self.base_spacing.value = float(grid_spacing_mm())
        self.minor_alpha.value = strength * 0.35
        self.major_alpha.value = strength
        self.grid_z.value = float(setting("grid_z_offset"))
        self.side_planes.value = 1.0 if setting("side_planes") else 0.0
        self.axis_lines.value = 1.0 if setting("axis_lines") else 0.0

    # Shadow mask resolution and tessellation. The tolerance is deliberately
    # coarser than FreeCAD's display mesh so tessellate() reuses the existing
    # triangulation instead of re-meshing the shape (seconds on big models).
    SHADOW_TEX_MAX = 1024
    SHADOW_TESS_REL = 0.02
    SHADOW_SOFT_MIN = 0.004     # blur sigma as a fraction of the scene size
    SHADOW_SOFT_RANGE = 0.05
    SHADOW_SPREAD_RANGE = 0.3   # max outward growth, fraction of scene size
    # Blurring with sigma = spread/2 and keeping values above this level grows
    # a straight edge by exactly `spread` (0.5 * erfc(sqrt(2))), with rounded
    # rather than square corners.
    SHADOW_SPREAD_LEVEL = 0.0228

    def _set_shadow_image(self, width, height, data):
        self.shadow_tex.image.setValue(coin.SbVec2s(width, height), 1, data)

    @staticmethod
    def _shown(obj, depth=0):
        """True if FreeCAD actually displays obj (own state and parents)."""
        try:
            vo = obj.ViewObject
        except Exception:
            vo = None
        if vo is None:
            return False
        try:
            if not vo.isVisible():
                return False
        except Exception:
            if not vo.Visibility:
                return False
        if depth < 8:       # a hidden container hides its children too
            for getter in ("getParentGeoFeatureGroup", "getParentGroup"):
                try:
                    parent = getattr(obj, getter)()
                except Exception:
                    parent = None
                if parent is not None and not ShaderGrid._shown(parent, depth + 1):
                    return False
        return True

    def _own_doc(self):
        """This grid's document: never a different active document."""
        if self.doc_name:
            try:
                return App.getDocument(self.doc_name)
            except Exception:
                return None
        return getattr(App, "ActiveDocument", None)

    def _casting_shape(self, obj):
        """obj's Shape if it should cast a ground shadow, else None."""
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            return None
        if obj.isDerivedFrom("Part::Datum"):    # datum planes etc.
            return None
        if getattr(obj, "TypeId", "") in (
                "App::Part", "App::DocumentObjectGroup",
                "App::DocumentObjectGroupPython", "App::LinkGroup",
                "Assembly::AssemblyObject", "Assembly::AssemblyLink"):
            # A container's shape covers all of its children, which already
            # cast their own shadows.
            return None
        try:
            parent = obj.getParentGeoFeatureGroup()
        except Exception:
            parent = None
        if parent is not None and parent.isDerivedFrom("PartDesign::Body"):
            # Features inside a Body hold local-coordinate shapes; the Body
            # itself represents them in world coordinates.
            return None
        try:
            if shape.countElement("Face") == 0:     # sketches and wires
                return None
        except Exception:
            pass
        if not self._shown(obj):
            return None
        return shape

    @classmethod
    def _xy_triangles(cls, shape, placement):
        """Shape triangles projected to world XY, as an (N, 3, 2) array.

        Edge-on (vertical) triangles add nothing to the footprint and are
        dropped, which typically removes a third of the work.
        """
        size = max(shape.BoundBox.DiagonalLength, 1e-6)
        points, triangles = shape.tessellate(
            max(size * cls.SHADOW_TESS_REL, 1e-3))
        if not points or not triangles:
            return None
        pts = np.array([(v.x, v.y, v.z) for v in points], dtype=np.float64)
        if placement is not None:
            # tessellate() already applies the shape's own placement; swap it
            # for the link/container-aware world placement.
            matrix = placement.multiply(shape.Placement.inverse()).toMatrix()
            m = np.array(matrix.A, dtype=np.float64).reshape(4, 4)
            pts = pts @ m[:3, :3].T + m[:3, 3]
        tris = pts[np.asarray(triangles, dtype=np.int64)][:, :, :2]
        e1 = tris[:, 1] - tris[:, 0]
        e2 = tris[:, 2] - tris[:, 0]
        area = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
        keep = (area > 1e-12 * size * size) & np.isfinite(tris).all(axis=(1, 2))
        keep &= (np.abs(tris) < 1e9).all(axis=(1, 2))
        tris = tris[keep]
        return tris if len(tris) else None

    def _shadow_triangles(self):
        """Footprint triangles of every shadow-casting object.

        Returns (list of arrays, signature). Triangles are cached per object
        by shape hash and world placement, so unchanged objects cost only the
        visibility checks on later updates.
        """
        doc = self._own_doc()
        if not doc:
            return [], ()
        parts = []
        signature = []
        seen = set()
        for obj in getattr(doc, "Objects", []):
            try:
                shape = self._casting_shape(obj)
                if shape is None:
                    continue
                gp = _world_placement(obj)
                try:
                    key = (shape.hashCode(),
                           None if gp is None else
                           (tuple(gp.Base), tuple(gp.Rotation.Q)))
                except Exception:
                    key = None
                seen.add(obj.Name)
                cached = self._triangle_cache.get(obj.Name)
                if key is not None and cached is not None and cached[0] == key:
                    tris = cached[1]
                else:
                    tris = self._xy_triangles(shape, gp)
                    if key is not None:
                        self._triangle_cache[obj.Name] = (key, tris)
                if tris is None:
                    continue
                parts.append(tris)
                signature.append((obj.Name, key))
            except Exception:
                continue
        for name in list(self._triangle_cache):     # forget deleted objects
            if name not in seen:
                del self._triangle_cache[name]
        return parts, tuple(signature)

    def _build_shadow_texture(self, parts, softness, spread):
        """Rasterize, blur and upload the footprint mask. True if non-empty."""
        if not parts:
            self._set_shadow_image(1, 1, b"\0")
            return False
        tris = np.concatenate(parts)
        flat = tris.reshape(-1, 2)
        lo = flat.min(axis=0)
        hi = flat.max(axis=0)
        extent = float(max(hi[0] - lo[0], hi[1] - lo[1], 1e-6))
        sigma = extent * (self.SHADOW_SOFT_MIN +
                          self.SHADOW_SOFT_RANGE * softness)
        grow = extent * self.SHADOW_SPREAD_RANGE * spread
        pad = grow + 3.0 * sigma     # room to grow and for the fade to finish
        lo = lo - pad
        hi = hi + pad
        size = hi - lo
        limit = self.SHADOW_TEX_MAX
        pixel = float(max(size[0], size[1])) / (limit - 2)
        width = min(limit, _pow2_at_least(size[0] / pixel + 2))
        height = min(limit, _pow2_at_least(size[1] / pixel + 2))
        origin = (lo + hi) * 0.5 - np.array([width, height]) * pixel * 0.5

        mask = _rasterize_triangles((tris - origin) / pixel, width, height)
        if grow / pixel >= 1.0:
            # Expand the footprint so objects resting on the ground still
            # show a visible rim of shadow around their base.
            mask = (_gaussian_blur(mask, 0.5 * grow / pixel) >
                    self.SHADOW_SPREAD_LEVEL)
        shade = _gaussian_blur(mask, sigma / pixel)
        # The blur leaves 0.5 on the footprint edge; double it so the shadow
        # is solid under the model and fades only outside of it.
        shade = np.clip(shade * 2.0, 0.0, 1.0)
        shade = shade * shade * (3.0 - 2.0 * shade)
        data = (shade * 255.0 + 0.5).astype(np.uint8)
        data[0, :] = data[-1, :] = 0      # empty border: CLAMP stays dark-free
        data[:, 0] = data[:, -1] = 0
        # Row 0 of an SoSFImage is the bottom row, matching increasing Y.
        self._set_shadow_image(width, height, data.tobytes())
        self.shadow_rect.value = coin.SbVec4f(
            float(origin[0]), float(origin[1]),
            1.0 / (width * pixel), 1.0 / (height * pixel))
        App.Console.PrintLog(
            "Grid Overlay: ground shadow from %d objects (%dx%d)\n"
            % (len(parts), width, height))
        return True

    def set_shadow_visible(self, visible):
        self.shadow_visible = bool(visible)
        self.update_shadow()

    def update_shadow(self):
        """Rebuild the shadow mask if its inputs changed."""
        if not self.shadow_visible or np is None:
            self.shadow_opacity.value = 0.0
            return
        parts, signature = self._shadow_triangles()
        self.ground_ready = bool(parts)
        softness = setting("shadow_softness")
        spread = setting("shadow_spread")
        key = (signature, softness, spread)
        if key != self._shadow_key:
            self._shadow_key = key
            self._has_shadow = self._build_shadow_texture(
                parts, softness, spread)
        self.shadow_opacity.value = (
            float(setting("shadow_opacity")) if self._has_shadow else 0.0)

    def needs_shadow_retry(self, doc):
        """Retry an empty shadow only when the document's object list grew
        or shrank; shape changes arrive through the document observer."""
        if self.ground_ready or not self.shadow_visible:
            return False
        signature = len(getattr(doc, "Objects", ()))
        if signature == self._poll_signature:
            return False
        self._poll_signature = signature
        return True

    def set_visible(self, visible):
        self.visible = bool(visible)
        # Coin3D: SO_SWITCH_ALL == -3, SO_SWITCH_NONE == -1.
        self.content.whichChild = -3 if self.visible else -1

    def belongs_to(self, view):
        """Whether this overlay is still attached to the requested view."""
        if view is None:
            return False
        try:
            if self.superimposition is not None:
                viewer = view.getViewer()
                render_manager = viewer.getSoRenderManager()
                if not _same_ref(self.render_scene_graph,
                                 render_manager.getSceneGraph()):
                    return False
                current_camera = render_manager.getCamera()
                return (current_camera is None or
                        _same_ref(self.overlay_camera, current_camera))
            if not _same_ref(self.sg, view.getSceneGraph()):
                return False
            try:
                return self.sg.findChild(self.root) >= 0
            except Exception:
                for index in range(self.sg.getNumChildren()):
                    if _same_ref(self.sg.getChild(index), self.root):
                        return True
                return False
        except Exception:
            return False

    def remove(self):
        if self.superimposition is not None and self.render_manager is not None:
            try:
                self.render_manager.removeSuperimposition(self.superimposition)
            except Exception:
                pass
            if self.overlay_camera is not None:
                try:
                    self.root.removeChild(self.overlay_camera)
                except Exception:
                    pass
            self.superimposition = None
            self.render_manager = None
            self.render_scene_graph = None
            self.overlay_camera = None
            return
        try:
            self.sg.removeChild(self.root)
        except Exception:
            pass
        if self._scene_render_culling is not None:
            try:
                self.sg.renderCulling = self._scene_render_culling
            except Exception:
                pass


@_publish
class _AppObserver:
    """App-level hook: geometry changed -> refresh the ground shadow."""

    def __init__(self, manager):
        self._manager = manager

    def slotRecomputedDocument(self, doc):
        self._manager.schedule_shadow()

    def slotChangedObject(self, obj, prop):
        # Placement edits (e.g. the transform dragger) do not recompute, and
        # some importers fill shapes after the recompute signal has fired.
        if prop in ("Shape", "Placement"):
            self._manager.schedule_shadow()


@_publish
class GridManager:
    def __init__(self):
        self.items = {}                     # doc name -> ShaderGrid
        main = Gui.getMainWindow()
        self.shadow_timer = QtCore.QTimer(main)
        self.shadow_timer.setSingleShot(True)
        self.shadow_timer.setInterval(150)
        self.shadow_timer.timeout.connect(self.update_shadow)
        self.graph_timer = QtCore.QTimer(main)
        self.graph_timer.setInterval(500)
        self.graph_timer.timeout.connect(self.check_grid)
        self.graph_timer.start()
        try:
            Gui.addDocumentObserver(self)
        except Exception:
            pass
        self._app_observer = _AppObserver(self)
        try:
            App.addDocumentObserver(self._app_observer)
        except Exception:
            pass
        # Attach when the user switches to a 3D view (e.g. from a spreadsheet).
        try:
            mdi = main.findChild(QtWidgets.QMdiArea)
            if mdi is not None:
                mdi.subWindowActivated.connect(lambda *_: self.ensure_grid())
        except Exception:
            pass

    # -- views ---------------------------------------------------------
    @staticmethod
    def _view():
        try:
            view = Gui.ActiveDocument.ActiveView
        except Exception:
            view = None
        if view is None:
            try:
                view = Gui.activeDocument().activeView()
            except Exception:
                view = None
        return view if hasattr(view, "getSceneGraph") else None

    # -- grid lifecycle --------------------------------------------------
    def check_grid(self):
        """Repair an overlay removed while FreeCAD rebuilds a view graph."""
        if not setting("enabled"):
            return
        doc = getattr(App, "ActiveDocument", None)
        if doc is None:
            return
        view = self._view()
        grid = self.items.get(doc.Name)
        belongs = grid.belongs_to(view) if grid is not None else None
        if grid is None or not belongs:
            self.ensure_grid()
        elif grid.needs_shadow_retry(doc):
            # Some Assembly/import workflows populate geometry after the
            # document activation/recompute callbacks have already fired.
            grid.update_shadow()

    def ensure_grid(self, _retry=0):
        doc = getattr(App, "ActiveDocument", None)
        if doc is None:
            return
        view = self._view()
        grid = self.items.get(doc.Name)
        if grid is not None and not grid.belongs_to(view):
            # A document can have more than one 3D view, and some workbenches
            # replace the scene graph while keeping the document open.
            self.remove_grid(doc.Name)
            grid = None
        if setting("enabled") and grid is None:
            if view is None:
                if _retry < 10:     # view may not exist yet during startup
                    QtCore.QTimer.singleShot(
                        200, lambda: self.ensure_grid(_retry + 1))
                return
            try:
                grid = ShaderGrid(view, doc.Name)
            except Exception as exc:
                App.Console.PrintWarning(
                    "Grid Overlay: could not attach grid: %s\n" % exc)
                return
            self.items[doc.Name] = grid
        self.apply_settings()

    def apply_settings(self):
        on = setting("enabled")
        shadow_on = on and setting("shadow_enabled")
        for grid in self.items.values():
            grid.apply_settings()
            grid.set_visible(on)
            grid.set_shadow_visible(shadow_on)

    def refresh(self):
        self.ensure_grid()

    def remove_grid(self, name=None):
        names = [name] if name is not None else list(self.items)
        for key in names:
            grid = self.items.pop(key, None)
            if grid:
                grid.remove()

    # -- ground shadow (event driven) -----------------------------------
    def schedule_shadow(self):
        if not self.shadow_timer.isActive():
            self.shadow_timer.start()

    def update_shadow(self):
        try:
            doc = getattr(App, "ActiveDocument", None)
            if doc is None:
                return
            grid = self.items.get(doc.Name)
            if grid:
                grid.update_shadow()
        except Exception as exc:
            App.Console.PrintWarning("Grid Overlay: shadow update failed: %s\n" % exc)

    # -- Gui document observer slots -------------------------------------
    def slotCreatedDocument(self, doc):
        QtCore.QTimer.singleShot(0, self.ensure_grid)

    def slotActivateDocument(self, doc):
        QtCore.QTimer.singleShot(0, self.ensure_grid)
        self.schedule_shadow()

    def slotDeletedDocument(self, doc):
        name = _doc_name(doc)
        if name is None:
            document = getattr(doc, "Document", None)
            name = getattr(document, "Name", None)
        if name is not None:
            self.remove_grid(name)

    def slotChangedObject(self, vp, prop):
        name = prop if isinstance(prop, str) else getattr(prop, "Name", str(prop))
        if name in ("Visibility", "Placement"):
            self.schedule_shadow()

    def slotDeletedObject(self, *args):
        self.schedule_shadow()

    # -- teardown (add-on reload) ---------------------------------------
    def shutdown(self):
        try:
            Gui.removeDocumentObserver(self)
        except Exception:
            pass
        try:
            App.removeDocumentObserver(self._app_observer)
        except Exception:
            pass
        try:
            self.shadow_timer.stop()
        except Exception:
            pass
        try:
            self.graph_timer.stop()
        except Exception:
            pass
        self.remove_grid()


# If the addon is loaded again in the same session (a reload while
# developing), retire the previous manager so its observers, timers and
# overlays do not linger next to the new ones.
_previous = getattr(Gui, "_GridOverlayManager", None)
if _previous is not None:
    try:
        _previous.shutdown()
    except Exception:
        pass
manager = GridManager()
Gui._GridOverlayManager = manager
globals()["manager"] = manager


@_publish
class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(SettingsDialog, self).__init__(parent or Gui.getMainWindow())
        self.setWindowTitle("Grid Overlay Settings")
        self.setMinimumWidth(380)
        layout = QtWidgets.QVBoxLayout(self)

        grid_box = QtWidgets.QGroupBox("Grid")
        form = QtWidgets.QFormLayout(grid_box)
        layout.addWidget(grid_box)
        self.enabled = QtWidgets.QCheckBox("Show custom grid")
        form.addRow(self.enabled)
        self.unit = QtWidgets.QComboBox()
        for key, label, _factor in GRID_UNIT_OPTIONS:
            self.unit.addItem(label, key)
        form.addRow("Grid unit", self.unit)
        self.spacing = QtWidgets.QDoubleSpinBox()
        self.spacing.setRange(0.1, 100.0)
        self.spacing.setDecimals(2)
        form.addRow("Grid spacing", self.spacing)
        self.z_offset = QtWidgets.QDoubleSpinBox()
        self.z_offset.setRange(-1e6, 1e6)
        self.z_offset.setDecimals(3)
        self.z_offset.setToolTip(
            "Elevation (world Z) of the ground grid and its shadow")
        form.addRow("Ground height (Z)", self.z_offset)
        self.opacity = QtWidgets.QSlider(QT_HORIZONTAL)
        self.opacity.setRange(0, 100)
        form.addRow("Opacity", self.opacity)
        self.color = QtWidgets.QPushButton("Choose color…")
        self.color.clicked.connect(self.choose_color)
        form.addRow("Grid color", self.color)
        self.axis_lines = QtWidgets.QCheckBox("Show axis lines")
        form.addRow(self.axis_lines)
        self.side_planes = QtWidgets.QCheckBox(
            "Grid in front / rear / left / right views")
        self.side_planes.setToolTip(
            "When the camera looks straight along X or Y, draw the grid on "
            "the matching vertical plane behind the model")
        form.addRow(self.side_planes)

        shadow_box = QtWidgets.QGroupBox("Ground shadow")
        shadow_form = QtWidgets.QFormLayout(shadow_box)
        layout.addWidget(shadow_box)
        self.shadow_enabled = QtWidgets.QCheckBox("Show ground shadow")
        shadow_form.addRow(self.shadow_enabled)
        self.shadow_opacity = QtWidgets.QSlider(QT_HORIZONTAL)
        self.shadow_opacity.setRange(0, 100)
        shadow_form.addRow("Opacity", self.shadow_opacity)
        self.shadow_softness = QtWidgets.QSlider(QT_HORIZONTAL)
        self.shadow_softness.setRange(0, 100)
        shadow_form.addRow("Softness", self.shadow_softness)
        self.shadow_spread = QtWidgets.QSlider(QT_HORIZONTAL)
        self.shadow_spread.setRange(0, 100)
        self.shadow_spread.setToolTip(
            "How far the shadow extends beyond the model's footprint")
        shadow_form.addRow("Spread", self.shadow_spread)
        if np is None:
            shadow_box.setEnabled(False)
            shadow_box.setToolTip("Ground shadows require numpy")

        buttons = QtWidgets.QDialogButtonBox(
            _dialog_button("RestoreDefaults") | _dialog_button("Apply") |
            _dialog_button("Cancel"))
        layout.addWidget(buttons)
        buttons.button(_dialog_button("Apply")).clicked.connect(self.apply)
        buttons.button(_dialog_button("RestoreDefaults")).clicked.connect(
            lambda: self._load(DEFAULTS.get))
        buttons.rejected.connect(self.reject)

        self._unit_factor = 1.0
        self.unit.currentIndexChanged.connect(self._unit_changed)
        self._load(setting)

    def _load(self, value):
        """Fill the widgets from setting() or from DEFAULTS.get."""
        self.enabled.setChecked(value("enabled"))
        self.shadow_enabled.setChecked(value("shadow_enabled"))
        self.shadow_opacity.setValue(int(round(value("shadow_opacity") * 100)))
        self.shadow_softness.setValue(
            int(round(value("shadow_softness") * 100)))
        self.shadow_spread.setValue(int(round(value("shadow_spread") * 100)))
        self.axis_lines.setChecked(value("axis_lines"))
        self.side_planes.setChecked(value("side_planes"))
        self.opacity.setValue(int(round(value("opacity") * 100)))
        self.color_value = value("color")
        self._set_color_style()
        self.spacing.setValue(value("base_spacing"))
        unit = value("grid_unit")
        index = next((i for i, option in enumerate(GRID_UNIT_OPTIONS)
                      if option[0] == unit), 0)
        self.unit.blockSignals(True)
        self.unit.setCurrentIndex(index)
        self.unit.blockSignals(False)
        self._unit_factor = GRID_UNIT_OPTIONS[index][2]
        self._update_suffixes()
        self.z_offset.setValue(value("grid_z_offset") / self._unit_factor)

    def _unit_changed(self):
        # The ground height is stored in mm; keep the same physical height
        # when the displayed unit changes.
        height_mm = self.z_offset.value() * self._unit_factor
        self._unit_factor = GRID_UNIT_OPTIONS[self.unit.currentIndex()][2]
        self._update_suffixes()
        self.z_offset.setValue(height_mm / self._unit_factor)

    def _update_suffixes(self):
        key = GRID_UNIT_OPTIONS[self.unit.currentIndex()][0]
        self.spacing.setSuffix(" " + key)
        self.z_offset.setSuffix(" " + key)

    def _set_color_style(self):
        self.color.setStyleSheet("background-color: %s;" % self.color_value)

    def choose_color(self):
        chosen = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.color_value), self)
        if chosen.isValid():
            self.color_value = chosen.name(); self._set_color_style()

    def apply(self):
        save_settings({
            "enabled": self.enabled.isChecked(),
            "shadow_enabled": self.shadow_enabled.isChecked(),
            "shadow_opacity": self.shadow_opacity.value() / 100.0,
            "shadow_softness": self.shadow_softness.value() / 100.0,
            "shadow_spread": self.shadow_spread.value() / 100.0,
            "base_spacing": self.spacing.value(),
            "grid_unit": GRID_UNIT_OPTIONS[self.unit.currentIndex()][0],
            "grid_z_offset": self.z_offset.value() * self._unit_factor,
            "opacity": self.opacity.value() / 100.0,
            "color": self.color_value,
            "axis_lines": self.axis_lines.isChecked(),
            "side_planes": self.side_planes.isChecked(),
        })
        manager.refresh()


@_publish
class GridOverlayCommand:
    def GetResources(self):
        return {"MenuText": "Grid Overlay", "ToolTip": "Show or configure the custom viewport grid", "Pixmap": os.path.join(ADDON_DIR, "Resources", "grid.svg")}
    def IsActive(self):
        return True
    def Activated(self):
        if App.ActiveDocument and setting("enabled"):
            manager.ensure_grid()
        dlg = SettingsDialog()
        (getattr(dlg, "exec", None) or dlg.exec_)()


Gui.addCommand("GridOverlay_Settings", GridOverlayCommand())

# Add a toolbar to the main window so the button remains available across workbenches.
try:
    main = Gui.getMainWindow()
    toolbar = main.findChild(QtWidgets.QToolBar, "GridOverlayToolbar")
    if toolbar is None:
        toolbar = QtWidgets.QToolBar("Grid Overlay")
        toolbar.setObjectName("GridOverlayToolbar")
        main.addToolBar(toolbar)
    settings_action = None
    for action in list(toolbar.actions()):
        action_text = str(action.text())
        if action.objectName() == "GridOverlaySettingsAction" or action_text in ("Grid Overlay", "Grid Overlay Settings"):
            if settings_action is None:
                settings_action = action
        elif action.objectName() == "GridOverlayToggleAction" or action_text in ("Show/Hide", "Toggle Grid Overlay"):
            toolbar.removeAction(action)
    if settings_action is None:
        settings_action = toolbar.addAction(QtGui.QIcon(os.path.join(ADDON_DIR, "Resources", "grid.svg")), "Grid Overlay")
        settings_action.triggered.connect(lambda: Gui.runCommand("GridOverlay_Settings"))
    settings_action.setObjectName("GridOverlaySettingsAction")
    settings_action.setToolTip("Grid Overlay Settings")
    toolbar.setVisible(True)
    toolbar.show()
except Exception as exc:
    App.Console.PrintWarning("Grid Overlay: toolbar creation failed: %s\n" % exc)

# Attach on startup when a document is already open; otherwise wait for one.
if setting("enabled") and App.ActiveDocument:
    manager.ensure_grid()
