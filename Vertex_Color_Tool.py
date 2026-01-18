bl_info = {
    "name": "Vertex Color Tools",
    "author": "James arndt",
    "version": (0, 3, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Vertex Colors",
    "description": "Edit-mode Color Attribute tools: faces, vertex masking, palette (add/remove/move), viewport display wiring, and color picking from selection.",
    "category": "Mesh",
}

import bpy
import bmesh
from bpy.props import (
    FloatVectorProperty,
    StringProperty,
    BoolProperty,
    EnumProperty,
    IntProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup


# ------------------------------
# Color space helpers (sRGB UI <-> Linear mesh data)
# ------------------------------

def _srgb_to_linear(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * (c ** (1.0 / 2.4)) - 0.055


def _color_srgb_to_linear_rgba(col):
    return (
        _srgb_to_linear(float(col[0])),
        _srgb_to_linear(float(col[1])),
        _srgb_to_linear(float(col[2])),
        float(col[3]),
    )


def _color_linear_to_srgb_rgba(col):
    return (
        _linear_to_srgb(float(col[0])),
        _linear_to_srgb(float(col[1])),
        _linear_to_srgb(float(col[2])),
        float(col[3]),
    )


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ------------------------------
# Mesh helpers
# ------------------------------

def _active_mesh_object(context):
    ob = context.active_object
    if not ob or ob.type != "MESH":
        return None
    return ob


def _ensure_color_attribute(me, name="Col", domain="CORNER", data_type="BYTE_COLOR", set_active=True):
    """
    Ensure a Color Attribute exists. We target CORNER domain (loop colors).
    """
    ca = me.color_attributes.get(name)
    if ca is None:
        ca = me.color_attributes.new(name=name, domain=domain, type=data_type)
    if set_active:
        me.color_attributes.active = ca
        me.color_attributes.active_color = ca
    return ca


def _get_bmesh_and_color_layer(context, ensure=True, name="Col"):
    ob = _active_mesh_object(context)
    if ob is None:
        return None, None

    me = ob.data
    if ensure:
        _ensure_color_attribute(me, name=name, domain="CORNER", data_type="BYTE_COLOR", set_active=True)

    bm = bmesh.from_edit_mesh(me)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    layer = bm.loops.layers.color.get(name)
    if layer is None and ensure:
        layer = bm.loops.layers.color.new(name)

    return bm, layer


def _iter_target_loops(bm, mode, prefer_faces_if_any=True):
    """
    Target loops by selection mode:
    - FACES: all loops on selected faces
    - VERTS: loops whose vert is selected (vertex masking)
    - AUTO: faces if any selected faces exist, else verts
    """
    if mode == "AUTO":
        if prefer_faces_if_any and any(f.select for f in bm.faces):
            mode = "FACES"
        else:
            mode = "VERTS"

    if mode == "FACES":
        for f in bm.faces:
            if f.select:
                for loop in f.loops:
                    yield loop
        return

    # VERTS
    for f in bm.faces:
        for loop in f.loops:
            if loop.vert.select:
                yield loop


def _update_edit_mesh(context):
    ob = context.active_object
    if ob and ob.type == "MESH":
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)


def _set_viewport_show_attribute(context, attribute_name, force_solid=False):
    """
    Blender 5.0: Viewport Shading -> Color: "Attribute" maps to shading.color_type == 'VERTEX'
    and shows the mesh's active color attribute.
    """
    screen = context.window.screen
    if not screen:
        return 0

    changed = 0
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        for space in area.spaces:
            if space.type != "VIEW_3D":
                continue

            shading = space.shading
            if force_solid:
                try:
                    shading.type = "SOLID"
                except Exception:
                    pass

            try:
                shading.color_type = "VERTEX"
            except Exception:
                pass

            changed += 1

    return changed


def _sample_selection_linear_rgba(context, layer_name: str, selection_mode: str):
    """
    Sample the average color of the current selection from the mesh color layer.
    Returns a linear RGBA tuple, or None if nothing sampled.
    """
    bm, layer = _get_bmesh_and_color_layer(context, ensure=False, name=layer_name)
    if bm is None or layer is None:
        return None

    total = [0.0, 0.0, 0.0, 0.0]
    count = 0

    for loop in _iter_target_loops(bm, selection_mode, prefer_faces_if_any=True):
        c = loop[layer]  # linear RGBA
        total[0] += float(c[0])
        total[1] += float(c[1])
        total[2] += float(c[2])
        total[3] += float(c[3])
        count += 1

    if count == 0:
        return None

    inv = 1.0 / float(count)
    return (total[0] * inv, total[1] * inv, total[2] * inv, total[3] * inv)


# ------------------------------
# Palette data
# ------------------------------

class VC_PaletteItem(PropertyGroup):
    color: FloatVectorProperty(
        name="Color",
        subtype="COLOR",
        size=4,
        min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
        description="Palette colors are stored in sRGB (UI space).",
    )
    label: StringProperty(name="Label", default="Color")


# ------------------------------
# Operators
# ------------------------------

class VC_OT_set_active(bpy.types.Operator):
    bl_idname = "vc_tools.set_active"
    bl_label = "Set Active Color Attribute"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Name", default="Col")
    create_if_missing: BoolProperty(name="Create if Missing", default=True)

    @classmethod
    def poll(cls, context):
        return _active_mesh_object(context) is not None

    def execute(self, context):
        ob = context.active_object
        me = ob.data
        ca = me.color_attributes.get(self.name)
        if ca is None:
            if not self.create_if_missing:
                self.report({"ERROR"}, f"Color attribute '{self.name}' not found.")
                return {"CANCELLED"}
            _ensure_color_attribute(me, name=self.name, set_active=True)
        else:
            me.color_attributes.active = ca
            me.color_attributes.active_color = ca
        return {"FINISHED"}


class VC_OT_show_in_edit(bpy.types.Operator):
    bl_idname = "vc_tools.show_in_edit"
    bl_label = "Show Vertex Colors in Edit Mode"
    bl_options = {"REGISTER", "UNDO"}

    layer_name: StringProperty(name="Layer", default="Col")
    force_solid: BoolProperty(name="Force Solid Shading", default=False)

    @classmethod
    def poll(cls, context):
        return _active_mesh_object(context) is not None

    def execute(self, context):
        ob = context.active_object
        me = ob.data

        _ensure_color_attribute(me, name=self.layer_name, set_active=True)
        ca = me.color_attributes.get(self.layer_name)
        if ca:
            me.color_attributes.active = ca
            me.color_attributes.active_color = ca

        _set_viewport_show_attribute(context, self.layer_name, force_solid=self.force_solid)
        return {"FINISHED"}


class VC_OT_apply_color(bpy.types.Operator):
    bl_idname = "vc_tools.apply_color"
    bl_label = "Apply Color"
    bl_options = {"REGISTER", "UNDO"}

    color: FloatVectorProperty(
        name="Color",
        subtype="COLOR",
        size=4,
        min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
        description="UI color (sRGB) will be converted to linear for storage.",
    )
    layer_name: StringProperty(name="Layer", default="Col")

    selection_mode: EnumProperty(
        name="Target",
        items=[
            ("AUTO", "Auto", "Use selected faces if any are selected, otherwise selected vertices"),
            ("FACES", "Faces", "Apply to selected faces only"),
            ("VERTS", "Vertices", "Apply to selected vertices (vertex masking)"),
        ],
        default="AUTO",
    )

    @classmethod
    def poll(cls, context):
        return _active_mesh_object(context) is not None and context.mode == "EDIT_MESH"

    def execute(self, context):
        bm, layer = _get_bmesh_and_color_layer(context, ensure=True, name=self.layer_name)
        if bm is None or layer is None:
            self.report({"ERROR"}, "Could not access edit mesh or color layer.")
            return {"CANCELLED"}

        r, g, b, a = _color_srgb_to_linear_rgba(self.color)

        any_loop = False
        for loop in _iter_target_loops(bm, self.selection_mode, prefer_faces_if_any=True):
            loop[layer] = (r, g, b, a)
            any_loop = True

        if not any_loop:
            self.report({"WARNING"}, "Nothing selected (no selected faces or verts matched your target mode).")
            return {"CANCELLED"}

        _update_edit_mesh(context)
        return {"FINISHED"}


class VC_OT_multiply(bpy.types.Operator):
    bl_idname = "vc_tools.multiply"
    bl_label = "Multiply"
    bl_options = {"REGISTER", "UNDO"}

    tint: FloatVectorProperty(
        name="Tint",
        subtype="COLOR",
        size=4,
        min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
        description="UI color (sRGB) converted to linear for multiplication.",
    )
    layer_name: StringProperty(name="Layer", default="Col")

    selection_mode: EnumProperty(
        name="Target",
        items=[
            ("AUTO", "Auto", "Use selected faces if any are selected, otherwise selected vertices"),
            ("FACES", "Faces", "Affect selected faces only"),
            ("VERTS", "Vertices", "Affect selected vertices (vertex masking)"),
        ],
        default="AUTO",
    )

    @classmethod
    def poll(cls, context):
        return _active_mesh_object(context) is not None and context.mode == "EDIT_MESH"

    def execute(self, context):
        bm, layer = _get_bmesh_and_color_layer(context, ensure=False, name=self.layer_name)
        if bm is None or layer is None:
            self.report({"ERROR"}, f"Color layer '{self.layer_name}' not found. Use Set Active / Apply first.")
            return {"CANCELLED"}

        tr, tg, tb, ta = _color_srgb_to_linear_rgba(self.tint)

        any_loop = False
        for loop in _iter_target_loops(bm, self.selection_mode, prefer_faces_if_any=True):
            cr, cg, cb, ca = loop[layer]
            loop[layer] = (
                _clamp01(float(cr) * tr),
                _clamp01(float(cg) * tg),
                _clamp01(float(cb) * tb),
                _clamp01(float(ca) * ta),
            )
            any_loop = True

        if not any_loop:
            self.report({"WARNING"}, "Nothing selected (no selected faces or verts matched your target mode).")
            return {"CANCELLED"}

        _update_edit_mesh(context)
        return {"FINISHED"}


class VC_OT_invert(bpy.types.Operator):
    bl_idname = "vc_tools.invert"
    bl_label = "Invert"
    bl_options = {"REGISTER", "UNDO"}

    layer_name: StringProperty(name="Layer", default="Col")

    selection_mode: EnumProperty(
        name="Target",
        items=[
            ("AUTO", "Auto", "Use selected faces if any are selected, otherwise selected vertices"),
            ("FACES", "Faces", "Affect selected faces only"),
            ("VERTS", "Vertices", "Affect selected vertices (vertex masking)"),
        ],
        default="AUTO",
    )

    @classmethod
    def poll(cls, context):
        return _active_mesh_object(context) is not None and context.mode == "EDIT_MESH"

    def execute(self, context):
        bm, layer = _get_bmesh_and_color_layer(context, ensure=False, name=self.layer_name)
        if bm is None or layer is None:
            self.report({"ERROR"}, f"Color layer '{self.layer_name}' not found. Use Set Active / Apply first.")
            return {"CANCELLED"}

        any_loop = False
        for loop in _iter_target_loops(bm, self.selection_mode, prefer_faces_if_any=True):
            cr, cg, cb, ca = loop[layer]
            loop[layer] = (1.0 - float(cr), 1.0 - float(cg), 1.0 - float(cb), float(ca))
            any_loop = True

        if not any_loop:
            self.report({"WARNING"}, "Nothing selected (no selected faces or verts matched your target mode).")
            return {"CANCELLED"}

        _update_edit_mesh(context)
        return {"FINISHED"}


# ------------------------------
# Palette operators
# ------------------------------

class VC_OT_palette_add(bpy.types.Operator):
    bl_idname = "vc_tools.palette_add"
    bl_label = "Add Palette Color"
    bl_options = {"REGISTER", "UNDO"}

    from_fill: BoolProperty(name="From Fill Color", default=True)

    def execute(self, context):
        scn = context.scene
        item = scn.vc_palette.add()
        item.label = f"Color {len(scn.vc_palette)}"
        item.color = scn.vc_fill_color if self.from_fill else (1.0, 1.0, 1.0, 1.0)
        scn.vc_palette_index = len(scn.vc_palette) - 1
        return {"FINISHED"}


class VC_OT_palette_remove(bpy.types.Operator):
    bl_idname = "vc_tools.palette_remove"
    bl_label = "Remove Palette Color"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(context.scene.vc_palette) > 0

    def execute(self, context):
        scn = context.scene
        idx = scn.vc_palette_index
        scn.vc_palette.remove(idx)
        scn.vc_palette_index = max(0, min(idx, len(scn.vc_palette) - 1))
        return {"FINISHED"}


class VC_OT_palette_move(bpy.types.Operator):
    bl_idname = "vc_tools.palette_move"
    bl_label = "Move Palette Color"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction",
        items=[("UP", "Up", ""), ("DOWN", "Down", "")],
        default="UP",
    )

    @classmethod
    def poll(cls, context):
        return len(context.scene.vc_palette) > 1

    def execute(self, context):
        scn = context.scene
        idx = scn.vc_palette_index
        new_idx = idx - 1 if self.direction == "UP" else idx + 1
        if new_idx < 0 or new_idx >= len(scn.vc_palette):
            return {"CANCELLED"}
        scn.vc_palette.move(idx, new_idx)
        scn.vc_palette_index = new_idx
        return {"FINISHED"}


class VC_OT_palette_apply(bpy.types.Operator):
    bl_idname = "vc_tools.palette_apply"
    bl_label = "Apply Palette Color"
    bl_options = {"REGISTER", "UNDO"}

    palette_index: IntProperty(name="Palette Index", default=-1)

    @classmethod
    def poll(cls, context):
        return _active_mesh_object(context) is not None and context.mode == "EDIT_MESH" and len(context.scene.vc_palette) > 0

    def execute(self, context):
        scn = context.scene
        idx = self.palette_index if self.palette_index >= 0 else scn.vc_palette_index
        if idx < 0 or idx >= len(scn.vc_palette):
            self.report({"ERROR"}, "Invalid palette index.")
            return {"CANCELLED"}

        # IMPORTANT: vc_tools.apply_color expects UI (sRGB) and converts internally.
        col_srgb = scn.vc_palette[idx].color

        bpy.ops.vc_tools.apply_color(
            "EXEC_DEFAULT",
            color=col_srgb,
            layer_name=scn.vc_layer_name,
            selection_mode=scn.vc_selection_mode,
        )
        return {"FINISHED"}


class VC_OT_palette_to_fill(bpy.types.Operator):
    bl_idname = "vc_tools.palette_to_fill"
    bl_label = "Set Fill From Palette"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(context.scene.vc_palette) > 0

    def execute(self, context):
        scn = context.scene
        idx = scn.vc_palette_index
        if idx < 0 or idx >= len(scn.vc_palette):
            return {"CANCELLED"}
        scn.vc_fill_color = scn.vc_palette[idx].color
        return {"FINISHED"}


# ------------------------------
# Color picking operators (sample mesh -> UI)
# ------------------------------

class VC_OT_pick_from_selection_to_fill(bpy.types.Operator):
    bl_idname = "vc_tools.pick_to_fill"
    bl_label = "Pick From Selection To Fill"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh_object(context) is not None and context.mode == "EDIT_MESH"

    def execute(self, context):
        scn = context.scene
        linear = _sample_selection_linear_rgba(context, scn.vc_layer_name, scn.vc_selection_mode)
        if linear is None:
            self.report({"WARNING"}, "Nothing to sample (no matching selection or missing color layer).")
            return {"CANCELLED"}

        scn.vc_fill_color = _color_linear_to_srgb_rgba(linear)
        return {"FINISHED"}


class VC_OT_pick_from_selection_to_palette(bpy.types.Operator):
    bl_idname = "vc_tools.pick_to_palette"
    bl_label = "Pick From Selection To Palette"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh_object(context) is not None and context.mode == "EDIT_MESH"

    def execute(self, context):
        scn = context.scene
        linear = _sample_selection_linear_rgba(context, scn.vc_layer_name, scn.vc_selection_mode)
        if linear is None:
            self.report({"WARNING"}, "Nothing to sample (no matching selection or missing color layer).")
            return {"CANCELLED"}

        srgb = _color_linear_to_srgb_rgba(linear)

        item = scn.vc_palette.add()
        item.label = f"Picked {len(scn.vc_palette)}"
        item.color = srgb
        scn.vc_palette_index = len(scn.vc_palette) - 1
        return {"FINISHED"}


# ------------------------------
# UI
# ------------------------------

class VC_UL_palette(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "color", text="")
        row.prop(item, "label", text="", emboss=False)


class VC_PT_tools(bpy.types.Panel):
    bl_label = "Vertex Colors"
    bl_idname = "VC_PT_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Vertex Colors"

    def draw(self, context):
        layout = self.layout
        scn = context.scene

        # Attribute / viewport
        box = layout.box()
        box.label(text="Color Attribute")
        row = box.row(align=True)
        row.prop(scn, "vc_layer_name", text="")
        op = row.operator("vc_tools.set_active", text="Set")
        op.name = scn.vc_layer_name
        op.create_if_missing = True

        row = box.row(align=True)
        op = row.operator("vc_tools.show_in_edit", text="Show in Edit Mode")
        op.layer_name = scn.vc_layer_name
        op.force_solid = False
        op = row.operator("vc_tools.show_in_edit", text="Show + Solid")
        op.layer_name = scn.vc_layer_name
        op.force_solid = True

        # Targeting + apply
        box = layout.box()
        box.label(text="Apply / Modify")
        box.prop(scn, "vc_selection_mode", text="Target")

        row = box.row(align=True)
        row.prop(scn, "vc_fill_color", text="Color")
        row.operator("vc_tools.pick_to_fill", text="", icon="EYEDROPPER")

        row = box.row(align=True)
        op = row.operator("vc_tools.apply_color", text="Apply")
        op.color = scn.vc_fill_color
        op.layer_name = scn.vc_layer_name
        op.selection_mode = scn.vc_selection_mode

        row = box.row(align=True)
        row.prop(scn, "vc_tint", text="Multiply")
        op = row.operator("vc_tools.multiply", text="Multiply")
        op.tint = scn.vc_tint
        op.layer_name = scn.vc_layer_name
        op.selection_mode = scn.vc_selection_mode

        row = box.row(align=True)
        op = row.operator("vc_tools.invert", text="Invert")
        op.layer_name = scn.vc_layer_name
        op.selection_mode = scn.vc_selection_mode

        # Palette
        box = layout.box()
        box.label(text="Palette")

        row = box.row()
        row.template_list("VC_UL_palette", "", scn, "vc_palette", scn, "vc_palette_index", rows=6)

        col = row.column(align=True)
        col.operator("vc_tools.palette_add", text="", icon="ADD").from_fill = True
        col.operator("vc_tools.palette_remove", text="", icon="REMOVE")
        col.separator()
        op = col.operator("vc_tools.palette_move", text="", icon="TRIA_UP")
        op.direction = "UP"
        op = col.operator("vc_tools.palette_move", text="", icon="TRIA_DOWN")
        op.direction = "DOWN"

        row2 = box.row(align=True)
        row2.operator("vc_tools.palette_apply", text="Apply Palette")
        row2.operator("vc_tools.palette_to_fill", text="To Fill")

        row3 = box.row(align=True)
        row3.operator("vc_tools.pick_to_palette", text="Pick From Selection → Add", icon="EYEDROPPER")


# ------------------------------
# Registration
# ------------------------------

classes = (
    VC_PaletteItem,
    VC_OT_set_active,
    VC_OT_show_in_edit,
    VC_OT_apply_color,
    VC_OT_multiply,
    VC_OT_invert,
    VC_OT_palette_add,
    VC_OT_palette_remove,
    VC_OT_palette_move,
    VC_OT_palette_apply,
    VC_OT_palette_to_fill,
    VC_OT_pick_from_selection_to_fill,
    VC_OT_pick_from_selection_to_palette,
    VC_UL_palette,
    VC_PT_tools,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.Scene.vc_layer_name = StringProperty(
        name="Layer Name",
        default="Col",
        description="Color Attribute / Vertex Color layer name",
    )

    bpy.types.Scene.vc_selection_mode = EnumProperty(
        name="Selection Target",
        items=[
            ("AUTO", "Auto", "Use selected faces if any are selected, otherwise selected vertices"),
            ("FACES", "Faces", "Apply to selected faces only"),
            ("VERTS", "Vertices", "Apply to selected vertices (vertex masking across connected faces)"),
        ],
        default="AUTO",
    )

    bpy.types.Scene.vc_fill_color = FloatVectorProperty(
        name="Fill Color",
        subtype="COLOR",
        size=4,
        min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )

    bpy.types.Scene.vc_tint = FloatVectorProperty(
        name="Tint",
        subtype="COLOR",
        size=4,
        min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )

    bpy.types.Scene.vc_palette = CollectionProperty(type=VC_PaletteItem)
    bpy.types.Scene.vc_palette_index = IntProperty(name="Palette Index", default=0)


def unregister():
    del bpy.types.Scene.vc_palette_index
    del bpy.types.Scene.vc_palette
    del bpy.types.Scene.vc_tint
    del bpy.types.Scene.vc_fill_color
    del bpy.types.Scene.vc_selection_mode
    del bpy.types.Scene.vc_layer_name

    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
