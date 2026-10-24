# -*- coding: utf-8 -*-
"""Grid Overlay add-on for FreeCAD (legacy Mod-folder layout).

The grid is a single full-screen quad drawn by a GLSL shader: the fragment
shader intersects each pixel's view ray with the z=0 plane and draws
anti-aliased, level-of-detail-blended lines. There is no per-frame Python work
(no camera sensor, no polling timer, no geometry rebuilds).
"""
import os
import math
import importlib

import FreeCAD as App
import FreeCADGui as Gui
from pivy import coin

# FreeCAD's directory-module loader executes this file inside a function. Make
# the imports needed by helper functions visible in the module globals before
# calling those helpers during startup.
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

try:
    ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # FreeCAD evaluates InitGui.py with exec(), without defining __file__.
    ADDON_DIR = os.path.join(App.getUserAppDataDir(), "Mod", "GridOverlay")
SETTINGS = QtCore.QSettings("GridOverlay", "GridOverlay")
MANAGER_VERSION = 29


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

# FreeCAD's directory-module loader executes this file inside a function. In
# that mode, names assigned by exec() are not visible to functions/classes
# created by the exec unless they are explicitly published to its globals.
globals().update({
    "os": os, "math": math, "App": App, "Gui": Gui, "coin": coin,
    "QtCore": QtCore, "QtGui": QtGui, "QtWidgets": QtWidgets,
    "Signal": Signal, "ADDON_DIR": ADDON_DIR, "SETTINGS": SETTINGS,
    "MANAGER_VERSION": MANAGER_VERSION, "QT_HORIZONTAL": QT_HORIZONTAL,
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
    "shadow_enabled": True,
    "shadow_opacity": 0.30,
}
globals()["DEFAULTS"] = DEFAULTS


@_publish
def setting(key):
    value = SETTINGS.value(key, DEFAULTS[key])
    if key in ("enabled", "shadow_enabled"):
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes", "on")
    if key in ("opacity", "shadow_opacity", "base_spacing"):
        try:
            result = float(value)
        except Exception:
            return DEFAULTS[key]
        if key == "base_spacing":
            return max(0.01, min(100.0, result))
        return max(0.0, min(1.0, result))
    return str(value)


@_publish
def save_settings(values):
    for key, value in values.items():
        SETTINGS.setValue(key, value)
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


def _set_mf_floats(field, values):
    """Fill an SoMFFloat from a Python list (setValues, else per element)."""
    try:
        field.setValues(0, len(values), values)
    except Exception:
        for i, v in enumerate(values):
            field.set1Value(i, v)
    field.setNum(len(values))


globals()["_set_mf_floats"] = _set_mf_floats


@_publish
class ShaderGrid:
    """Infinite z=0 grid drawn by a shader on a 4-vertex placeholder quad."""

    # Placeholder corners. The vertex shader only uses their sign, so they can
    # be tiny: that keeps the scene bounding box (near/far clipping, view fit)
    # unaffected by the grid.
    _EPS = 1e-6

    def __init__(self, view):
        self.view = view
        self.sg = view.getSceneGraph()
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
        self.minor_alpha = coin.SoShaderParameter1f()
        self.minor_alpha.name = "minor_alpha"
        self.major_alpha = coin.SoShaderParameter1f()
        self.major_alpha.name = "major_alpha"
        self.shadow_count = coin.SoShaderParameter1f()
        self.shadow_count.name = "shadow_count"
        self.shadow_count.value = 0.0
        self.shadow_opacity = coin.SoShaderParameter1f()
        self.shadow_opacity.name = "shadow_opacity"
        self.shadow_opacity.value = 0.0
        self.shadow_data = None
        self.shadow_visible = False
        self._bounds_cache = {}
        self._last_shadow_names = None
        params = [self.grid_color, self.base_spacing,
                  self.minor_alpha, self.major_alpha,
                  self.shadow_count, self.shadow_opacity]
        try:
            self.shadow_data = coin.SoShaderParameterArray1f()
            self.shadow_data.name = "shadow_data"
            _set_mf_floats(self.shadow_data.value,
                           [0.0] * (self.SHADOW_MAX * self.SHADOW_STRIDE))
            params.append(self.shadow_data)
        except Exception as exc:
            self.shadow_data = None
            App.Console.PrintWarning(
                "Grid Overlay: ground shadows unavailable (%s)\n" % exc)
        fragment.parameter.setValues(0, len(params), params)

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
        self.sg.addChild(self.root)
        self.apply_settings()

    def apply_settings(self):
        """Push settings into shader uniforms. Call on change only."""
        color = QtGui.QColor(setting("color"))
        strength = setting("opacity")
        self.grid_color.value = (color.redF(), color.greenF(), color.blueF())
        self.base_spacing.value = float(setting("base_spacing"))
        self.minor_alpha.value = strength * 0.35
        self.major_alpha.value = strength

    SHADOW_MAX = 8           # must match SHADOW_MAX in grid.frag.glsl
    SHADOW_STRIDE = 4        # packed centre + half extents

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

    def _footprints(self):
        """XY footprint of each visible solid-ish object.

        Returns [(cx, cy, hx, hy, height, name)]. Per-object bounds are cached by
        shape hash, so unchanged objects cost almost nothing on later updates.
        """
        doc = getattr(App, "ActiveDocument", None)
        if not doc:
            return []
        out = []
        seen = set()
        for obj in getattr(doc, "Objects", []):
            try:
                shape = getattr(obj, "Shape", None)
                if shape is None or shape.isNull():
                    continue
                if obj.isDerivedFrom("Part::Datum"):    # datum planes etc.
                    continue
                parent = obj.getParentGeoFeatureGroup()
                if parent is not None and parent.isDerivedFrom("PartDesign::Body"):
                    # Features inside a Body hold local-coordinate shapes; the
                    # Body itself represents them in world coordinates.
                    continue
                if not self._shown(obj):
                    continue
                gp = None               # world placement for objects in a Part
                if parent is not None:
                    gp = _world_placement(obj)
                key = None
                try:
                    key = (shape.hashCode(),
                           None if gp is None else
                           (tuple(gp.Base), tuple(gp.Rotation.Q)))
                except Exception:
                    pass
                seen.add(obj.Name)
                cached = self._bounds_cache.get(obj.Name)
                if key is not None and cached and cached[0] == key:
                    bounds = cached[1]
                else:
                    bounds = None
                    try:
                        has_faces = shape.countElement("Face") > 0
                    except Exception:
                        has_faces = True
                    if has_faces:       # skips sketches, wires, empty shapes
                        if gp is not None:
                            placed = shape.copy()
                            placed.Placement = gp
                            b = placed.BoundBox
                        else:
                            b = shape.BoundBox
                        if b.isValid():
                            vals = (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)
                            if all(math.isfinite(v) and abs(v) < 1e9 for v in vals):
                                bounds = vals
                    if key is not None:
                        self._bounds_cache[obj.Name] = (key, bounds)
                if bounds is None:
                    continue
                x0, y0, z0, x1, y1, z1 = bounds
                if z1 < 0.0:            # entirely below the ground plane
                    continue
                out.append(((x0 + x1) * 0.5, (y0 + y1) * 0.5,
                            (x1 - x0) * 0.5, (y1 - y0) * 0.5, max(z1, 0.0),
                            obj.Name))
            except Exception:
                continue
        for name in list(self._bounds_cache):      # forget deleted objects
            if name not in seen:
                del self._bounds_cache[name]
        return out

    def set_shadow_visible(self, visible):
        self.shadow_visible = bool(visible)
        self.update_shadow()

    def update_shadow(self):
        """Rebuild the shadow slots. Event driven, never polled."""
        if self.shadow_data is None:
            return
        items = self._footprints() if self.shadow_visible else []
        if not items:
            self.shadow_opacity.value = 0.0
            self.shadow_count.value = 0.0
            return
        # Keep the largest footprints if there are more than the shader holds.
        items.sort(key=lambda it: it[2] * it[3], reverse=True)
        items = items[:self.SHADOW_MAX]
        data = []
        for cx, cy, hx, hy, height, _name in items:
            hx = max(hx, 1e-4)
            hy = max(hy, 1e-4)
            # Keep four values per slot so the fragment uniform remains small
            # enough for older OpenGL implementations.  The blur scales with
            # footprint; the geometry height is intentionally not uploaded.
            data.extend((cx, cy, hx, hy))
        data.extend([0.0] * (self.SHADOW_MAX * self.SHADOW_STRIDE - len(data)))
        _set_mf_floats(self.shadow_data.value, data)
        self.shadow_count.value = float(len(items))
        self.shadow_opacity.value = float(setting("shadow_opacity"))
        names = tuple(it[5] for it in items)
        if names != self._last_shadow_names:        # Report view "Log" level
            self._last_shadow_names = names
            App.Console.PrintLog(
                "Grid Overlay: ground shadows for: %s\n" % ", ".join(names))

    def set_visible(self, visible):
        self.visible = bool(visible)
        # Coin3D: SO_SWITCH_ALL == -3, SO_SWITCH_NONE == -1.
        self.content.whichChild = -3 if self.visible else -1

    def belongs_to(self, view):
        """Whether this overlay is still attached to the requested view."""
        if view is None:
            return False
        try:
            return _same_ref(self.sg, view.getSceneGraph())
        except Exception:
            return False

    def remove(self):
        try:
            self.sg.removeChild(self.root)
        except Exception:
            pass


@_publish
class _AppObserver:
    """App-level hook: geometry changed -> refresh the ground shadow."""

    def __init__(self, manager):
        self._manager = manager

    def slotRecomputedDocument(self, doc):
        self._manager.schedule_shadow()


@_publish
class GridManager:
    def __init__(self):
        self._grid_overlay_manager_version = MANAGER_VERSION
        self.items = {}                     # doc name -> ShaderGrid
        main = Gui.getMainWindow()
        self.shadow_timer = QtCore.QTimer(main)
        self.shadow_timer.setSingleShot(True)
        self.shadow_timer.setInterval(150)
        self.shadow_timer.timeout.connect(self.update_shadow)
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
                grid = ShaderGrid(view)
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
            grid = self.items.get(App.ActiveDocument.Name)
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
        name = getattr(doc, "Name", None)
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
        self.remove_grid()


manager = getattr(Gui, "_GridOverlayManager", None)
if manager is None or getattr(manager, "_grid_overlay_manager_version", None) != MANAGER_VERSION:
    if manager is not None:
        try:
            Gui.removeDocumentObserver(manager)
        except Exception:
            pass
        for _fn in ("shutdown", "remove_grid"):      # new / older managers
            try:
                getattr(manager, _fn)()
            except Exception:
                pass
        try:
            manager.timer.stop()                      # older managers polled
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
        self.setMinimumWidth(360)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout(); layout.addLayout(form)
        self.enabled = QtWidgets.QCheckBox("Show custom grid")
        self.enabled.setChecked(setting("enabled")); form.addRow(self.enabled)
        self.shadow_enabled = QtWidgets.QCheckBox("Show ground shadow")
        self.shadow_enabled.setChecked(setting("shadow_enabled")); form.addRow(self.shadow_enabled)
        self.shadow_opacity = QtWidgets.QSlider(QT_HORIZONTAL)
        self.shadow_opacity.setRange(0, 100)
        self.shadow_opacity.setValue(int(setting("shadow_opacity") * 100))
        form.addRow("Ground shadow opacity", self.shadow_opacity)
        self.spacing = QtWidgets.QDoubleSpinBox(); self.spacing.setRange(0.1, 100.0); self.spacing.setDecimals(2); self.spacing.setValue(setting("base_spacing"))
        form.addRow("Base spacing scale", self.spacing)
        self.opacity = QtWidgets.QSlider(QT_HORIZONTAL); self.opacity.setRange(0, 100); self.opacity.setValue(int(setting("opacity")*100))
        form.addRow("Opacity", self.opacity)
        self.color = QtWidgets.QPushButton("Choose color…")
        self.color_value = setting("color"); self._set_color_style()
        form.addRow("Grid color", self.color)
        self.color.clicked.connect(self.choose_color)
        buttons = QtWidgets.QDialogButtonBox(
            _dialog_button("Apply") | _dialog_button("Cancel"))
        layout.addWidget(buttons)
        buttons.button(_dialog_button("Apply")).clicked.connect(self.apply)
        buttons.rejected.connect(self.reject)

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
            "shadow_opacity": self.shadow_opacity.value()/100.0,
            "base_spacing": self.spacing.value(),
            "opacity": self.opacity.value()/100.0,
            "color": self.color_value,
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
