bl_info = {
    "name": "Vertex Color Toolbox",
    "author": "James Arndt",
    "version": (2, 5, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar > VColor",
    "description": "Compact Edit Mode vertex-color workflow inspired by 3ds Max VertexPaint",
    "category": "Mesh",
}

import bpy
import bmesh
import colorsys
from array import array

from bpy.app.handlers import persistent
from mathutils import Color

from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)


# ------------------------------------------------------------------------
# Transient preview lifecycle: no mutations on install, load, or selection.
# ------------------------------------------------------------------------

_VCT_PREVIOUS_LIGHTING = {}
_VCT_PREVIOUS_SHADING_TYPE = {}
_VCT_MATERIAL_PREVIEW_MATERIAL_NAME = "__VCT_VertexColorPreview__"


def _cleanup_all_previews():
    """Rollback temporary changes in all scenes before saving/disabling."""
    from types import SimpleNamespace

    for scene in bpy.data.scenes:
        if not hasattr(scene, "vct_settings"):
            continue
        settings = scene.vct_settings
        context = (bpy.context if bpy.context.scene == scene else
                   SimpleNamespace(scene=scene, area=None, space_data=None))

        # Restore original material slots before removing a temporary layer.
        if settings.material_preview_active:
            ok, message = _restore_material_preview(context)
            if not ok:
                print("Vertex Color Toolbox: restore materials:", message)
        if settings.preview_active:
            ok, message = _remove_preview_attribute(settings)
            if not ok:
                print("Vertex Color Toolbox: cancel preview:", message)


def _deferred_preview_cleanup():
    _cleanup_all_previews()
    return None


def _schedule_preview_cleanup():
    if not bpy.app.timers.is_registered(_deferred_preview_cleanup):
        bpy.app.timers.register(_deferred_preview_cleanup, first_interval=0.0)


@persistent
def _vct_load_post(_dummy):
    # Recover previews persisted by an older version or an interrupted session.
    _schedule_preview_cleanup()


@persistent
def _vct_save_pre(_dummy):
    # Temporary preview data should never be written into the project file.
    _cleanup_all_previews()


@persistent
def _vct_undo_post(_dummy):
    # Wait until undo/redo has restored Blender's RNA state.
    _schedule_preview_cleanup()


@persistent
def _vct_redo_post(_dummy):
    _schedule_preview_cleanup()


# ------------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------------

def get_safe_active_color_attribute(mesh):
    """Safely retrieve the active color attribute, bypassing dangling RNA pointers."""
    if not mesh:
        return None
    try:
        active = mesh.color_attributes.active_color
        if active and active.name:
            return active
    except ReferenceError:
        return None
    return None


def _preview_material_target_object(settings):
    # Pointer survives renaming; the name supports previews from older files.
    try:
        if settings.material_preview_object is not None:
            return settings.material_preview_object
    except ReferenceError:
        pass
    return (bpy.data.objects.get(settings.material_preview_object_name)
            if settings.material_preview_object_name else None)


def _get_material_preview_attribute_name(obj, settings):
    """Return the color attribute that should currently drive material preview."""
    if not obj or obj.type != 'MESH':
        return None

    mesh = obj.data

    # If HSV Live Preview is active, display the temporary preview attribute.
    if (
        settings.preview_active
        and _preview_target_object(settings) == obj
        and settings.preview_temp_name
    ):
        temp = mesh.color_attributes.get(settings.preview_temp_name)
        if temp and temp.domain == 'CORNER':
            return temp.name

    active = get_safe_active_color_attribute(mesh)
    if active and active.domain == 'CORNER':
        return active.name

    for attr in mesh.color_attributes:
        if (
            attr.domain == 'CORNER'
            and not attr.name.startswith(_PREVIEW_PREFIX)
        ):
            return attr.name

    return None


def _ensure_material_preview_material(attribute_name, existing=None):
    """Create an owned material, or update only the owned attribute node."""
    if existing is not None:
        if not existing.use_nodes:
            return None
        node = existing.node_tree.nodes.get("VCT_ColorAttribute")
        if node is None:
            return None
        if node.layer_name != attribute_name:
            node.layer_name = attribute_name
        return existing

    # Never look up and overwrite an unrelated material with the same name.
    mat = bpy.data.materials.new(_VCT_MATERIAL_PREVIEW_MATERIAL_NAME)
    mat.use_nodes = True

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.name = "VCT_Output"
    output.location = (420, 0)

    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.name = "VCT_Principled"
    shader.location = (120, 0)

    color_attr = nodes.new("ShaderNodeVertexColor")
    color_attr.name = "VCT_ColorAttribute"
    color_attr.label = f"Color Attribute: {attribute_name}"
    color_attr.location = (-200, 0)
    color_attr.layer_name = attribute_name

    links.new(color_attr.outputs["Color"], shader.inputs["Base Color"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])

    # Keep the temporary preview visually neutral.
    if "Metallic" in shader.inputs:
        shader.inputs["Metallic"].default_value = 0.0

    if "Roughness" in shader.inputs:
        shader.inputs["Roughness"].default_value = 1.0

    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.0
    elif "Specular" in shader.inputs:
        shader.inputs["Specular"].default_value = 0.0

    return mat


def _clear_material_preview_state(scene):
    settings = scene.vct_settings
    owned_material = settings.material_preview_material
    settings.material_preview_active = False
    settings.material_preview_object = None
    settings.material_preview_object_name = ""
    settings.material_preview_attribute_name = ""
    settings.material_preview_original_slot_count = 0
    settings.material_preview_material = None
    scene.vct_material_preview_slots.clear()
    if owned_material is not None and owned_material.users == 0:
        bpy.data.materials.remove(owned_material)


def _restore_material_preview(context):
    """Restore the object's original material assignments and viewport shading."""
    settings = context.scene.vct_settings

    if not settings.material_preview_active:
        return True, ""

    obj = _preview_material_target_object(settings)

    if not obj or obj.type != 'MESH':
        _clear_material_preview_state(context.scene)
        return False, "Material preview object is no longer available."

    stored_slots = context.scene.vct_material_preview_slots
    original_count = settings.material_preview_original_slot_count

    try:
        # Restore existing original slots.
        if original_count > 0:
            for index in range(min(original_count, len(obj.material_slots))):
                saved = stored_slots[index] if index < len(stored_slots) else None
                slot = obj.material_slots[index]

                if saved:
                    try:
                        slot.link = saved.link
                    except Exception:
                        pass

                    material = saved.material
                    if material is None and saved.material_name:
                        material = bpy.data.materials.get(saved.material_name)

                    # DATA-linked slots use the untouched mesh material.
                    # Never rewrite underlying shared mesh data on restore.
                    if saved.link == 'OBJECT':
                        slot.material = material

        # File save/undo can run outside the initiating 3D viewport.
        # Recover only viewports actually modified by the preview.
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                previous = _VCT_PREVIOUS_SHADING_TYPE.pop(area.as_pointer(), None)
                if previous:
                    area.spaces.active.shading.type = previous
                    area.tag_redraw()

    except Exception as ex:
        return False, str(ex)

    _clear_material_preview_state(context.scene)
    return True, ""


def _sync_material_preview_attribute(context):
    """Keep the temporary material pointed at the active/preview Color Attribute."""
    if not context or not getattr(context, "scene", None):
        return

    settings = context.scene.vct_settings

    if not settings.material_preview_active:
        return

    obj = _preview_material_target_object(settings)
    if not obj or obj.type != 'MESH':
        return

    attribute_name = _get_material_preview_attribute_name(obj, settings)
    if not attribute_name:
        return

    # Synchronization must not rebuild nodes or change user's material slots.
    mat = _ensure_material_preview_material(
        attribute_name, settings.material_preview_material
    )
    if mat is None:
        return
    settings.material_preview_attribute_name = attribute_name

    if context.screen is not None:
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _toggle_material_preview(context):
    """Toggle a temporary material that renders the active Color Attribute."""
    settings = context.scene.vct_settings
    obj = get_active_mesh_object(context)

    if not obj:
        return False, "Select a mesh object."

    # Toggle off when preview is already active on this object.
    if settings.material_preview_active:
        preview_obj = _preview_material_target_object(settings)

        if preview_obj and preview_obj.name == obj.name:
            return _restore_material_preview(context)

        # Only one preview object at a time. Restore the old one first.
        success, message = _restore_material_preview(context)
        if not success:
            return False, message

    attribute_name = _get_material_preview_attribute_name(obj, settings)

    if not attribute_name:
        return False, "Choose or create a Face Corner Color Attribute first."

    if not obj.material_slots:
        return False, (
            "Material Preview needs an existing material slot. "
            "Use Solid Colors, or add a material slot first."
        )

    stored_slots = context.scene.vct_material_preview_slots
    stored_slots.clear()

    # Preserve material pointer + link mode for every existing slot.
    for slot in obj.material_slots:
        item = stored_slots.add()
        item.material = slot.material
        item.material_name = slot.material.name if slot.material else ""
        item.link = slot.link

    settings.material_preview_active = True
    settings.material_preview_object = obj
    settings.material_preview_object_name = obj.name
    settings.material_preview_attribute_name = attribute_name
    settings.material_preview_original_slot_count = len(obj.material_slots)

    try:
        preview_mat = _ensure_material_preview_material(attribute_name)
        settings.material_preview_material = preview_mat
        # Object-linked slots cannot mutate materials of mesh-linked instances.
        for slot in obj.material_slots:
            slot.link = 'OBJECT'
            slot.material = preview_mat
    except Exception as ex:
        _restore_material_preview(context)
        return False, "Could not start Material Preview: " + str(ex)

    # Enter Material Preview and remember the previous viewport shading type.
    if (
        context.area
        and context.area.type == 'VIEW_3D'
        and context.space_data
        and context.space_data.type == 'VIEW_3D'
    ):
        key = context.area.as_pointer()
        _VCT_PREVIOUS_SHADING_TYPE[key] = context.space_data.shading.type
        context.space_data.shading.type = 'MATERIAL'
        context.area.tag_redraw()

    return True, ""


def get_active_mesh_object(context):
    obj = context.active_object
    if obj and obj.type == 'MESH':
        return obj
    return None


def get_edit_mesh(context):
    obj = get_active_mesh_object(context)
    if not obj or obj.mode != 'EDIT':
        return None, None, None

    mesh = obj.data
    bm = bmesh.from_edit_mesh(mesh)
    return obj, mesh, bm


def get_active_color_attribute(mesh):
    return get_safe_active_color_attribute(mesh)


def set_active_color_attribute(mesh, attr_or_name):
    """Keep Blender's active color name and index synchronized."""
    if not mesh:
        return None

    attrs = mesh.color_attributes
    if not attrs:
        return None

    name = attr_or_name.name if hasattr(attr_or_name, "name") else str(attr_or_name)
    attr = attrs.get(name)
    if not attr:
        return None

    for index, candidate in enumerate(attrs):
        if candidate.name == attr.name:
            attrs.active_color_index = index
            break

    attrs.active_color_name = attr.name
    return attr


def get_active_corner_attribute(mesh):
    attr = get_active_color_attribute(mesh)
    if attr and attr.domain == 'CORNER':
        return attr
    return None


def get_bmesh_color_layer(bm, attr):
    if not attr or attr.domain != 'CORNER':
        return None

    layers = (
        bm.loops.layers.float_color
        if attr.data_type == 'FLOAT_COLOR'
        else bm.loops.layers.color
    )

    try:
        return layers[attr.name]
    except KeyError:
        return None


def color_to_bmesh(attr, rgba):
    """Convert Blender UI color values to BMesh storage values."""
    rgba = tuple(rgba)

    if attr and attr.data_type == 'BYTE_COLOR':
        rgb = Color(rgba[:3]).from_scene_linear_to_srgb()
        return (rgb.r, rgb.g, rgb.b, rgba[3])

    return rgba


def color_from_bmesh(attr, rgba):
    """Convert BMesh storage values back to Blender UI color values."""
    rgba = tuple(rgba)

    if attr and attr.data_type == 'BYTE_COLOR':
        rgb = Color(rgba[:3]).from_srgb_to_scene_linear()
        return (rgb.r, rgb.g, rgb.b, rgba[3])

    return rgba


def average_colors(colors):
    if not colors:
        return (1.0, 1.0, 1.0, 1.0)

    count = float(len(colors))
    return tuple(sum(color[i] for color in colors) / count for i in range(4))


def mix_color(existing, target, strength, affect_alpha):
    strength = max(0.0, min(1.0, strength))

    result = [
        existing[i] + (target[i] - existing[i]) * strength
        for i in range(3)
    ]

    if affect_alpha:
        alpha = existing[3] + (target[3] - existing[3]) * strength
    else:
        alpha = existing[3]

    return (result[0], result[1], result[2], alpha)


def get_active_selected_face(bm):
    active = bm.select_history.active

    if isinstance(active, bmesh.types.BMFace):
        if active.select and not active.hide:
            return active

    for face in bm.faces:
        if face.select and not face.hide:
            return face

    return None


def get_active_selected_vert(bm):
    active = bm.select_history.active

    if isinstance(active, bmesh.types.BMVert):
        if active.select and not active.hide:
            return active

    for vert in bm.verts:
        if vert.select and not vert.hide:
            return vert

    return None


def loops_for_vertex(bm, vert):
    loops = []

    for face in vert.link_faces:
        if face.hide:
            continue

        for loop in face.loops:
            if loop.vert == vert:
                loops.append(loop)
                break

    return loops


def get_effective_edit_mode(context):
    """Use Blender's actual mesh selection mode as the source of truth.

    Face Select -> FACE behavior.
    Vertex Select, Edge Select, or mixed select modes -> VERTEX behavior.
    Outside Edit Mode, fall back to the toolbox's stored mode.
    """
    settings = context.scene.vct_settings

    if context.mode == 'EDIT_MESH':
        vert_mode, edge_mode, face_mode = context.tool_settings.mesh_select_mode

        # Only pure Face Select invokes face-color behavior.
        # Edge and mixed selection modes intentionally behave like Vertex mode.
        if face_mode and not vert_mode and not edge_mode:
            return 'FACE'

        if vert_mode or edge_mode:
            return 'VERTEX'

    return settings.edit_mode


def get_selected_loops(bm, edit_mode):
    """Collect selected corners with a single face pass.

    Traversing every selected vertex's linked faces repeated work on dense
    selections. A face pass handles hard corner boundaries and hidden faces
    while visiting each affected corner only once.
    """
    loops = []
    if edit_mode == 'FACE':
        for face in bm.faces:
            if face.select and not face.hide:
                loops.extend(face.loops)
    else:
        for face in bm.faces:
            if face.hide:
                continue
            for loop in face.loops:
                if loop.vert.select and not loop.vert.hide:
                    loops.append(loop)
    return loops


def fill_selection_with_color(context, color):
    obj, mesh, bm = get_edit_mesh(context)
    if not bm:
        return False, "Enter Edit Mode on a mesh first."

    settings = context.scene.vct_settings
    if settings.preview_active:
        return False, "Apply or Cancel Live Preview before filling colors."
    attr = get_active_corner_attribute(mesh)

    if not attr:
        return False, "Choose or create a Face Corner Color Attribute."

    layer = get_bmesh_color_layer(bm, attr)
    if layer is None:
        return False, "The active Color Attribute is unavailable in Edit Mode."

    edit_mode = get_effective_edit_mode(context)
    loops = get_selected_loops(bm, edit_mode)
    if not loops:
        element = "faces" if edit_mode == 'FACE' else "vertices"
        return False, f"No {element} are selected."

    strength = settings.strength
    if strength <= 0.0:
        return True, ""

    target = tuple(color)
    if strength >= 1.0:
        # The final color does not depend on the existing RGB. Convert the
        # working color once, not once per face corner.
        encoded = color_to_bmesh(attr, target)
        if settings.affect_alpha:
            for loop in loops:
                loop[layer] = encoded
        else:
            rgb = encoded[:3]
            for loop in loops:
                old_alpha = loop[layer][3]
                loop[layer] = (rgb[0], rgb[1], rgb[2], old_alpha)
    else:
        # Preserve the existing scene-linear blend semantics for partial
        # strength, including Byte Color attributes.
        affect_alpha = settings.affect_alpha
        for loop in loops:
            existing = color_from_bmesh(attr, tuple(loop[layer]))
            result = mix_color(existing, target, strength, affect_alpha)
            loop[layer] = color_to_bmesh(attr, result)

    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    return True, ""


def sample_selection_color(context):
    obj, mesh, bm = get_edit_mesh(context)
    if not bm:
        return False, None, "Enter Edit Mode on a mesh first."

    settings = context.scene.vct_settings
    attr = get_active_corner_attribute(mesh)

    if not attr:
        return False, None, "Choose or create a Face Corner Color Attribute."

    layer = get_bmesh_color_layer(bm, attr)
    if layer is None:
        return False, None, "The active Color Attribute is unavailable in Edit Mode."

    edit_mode = get_effective_edit_mode(context)

    if edit_mode == 'FACE':
        face = get_active_selected_face(bm)
        if not face:
            return False, None, "Select a face to sample."

        color = average_colors([
            color_from_bmesh(attr, tuple(loop[layer]))
            for loop in face.loops
        ])
        return True, color, ""

    vert = get_active_selected_vert(bm)
    if not vert:
        return False, None, "Select a vertex to sample."

    vert_loops = loops_for_vertex(bm, vert)
    if not vert_loops:
        return False, None, "The selected vertex has no visible face corners."

    color = average_colors([
        color_from_bmesh(attr, tuple(loop[layer]))
        for loop in vert_loops
    ])
    return True, color, ""


def colors_match(a, b, tolerance, match_alpha):
    count = 4 if match_alpha else 3
    return max(abs(a[i] - b[i]) for i in range(count)) <= tolerance


def adjust_rgb(rgb, hue_offset, saturation_factor, value_factor):
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    h = (h + hue_offset) % 1.0
    s = max(0.0, min(1.0, s * saturation_factor))
    v = max(0.0, min(1.0, v * value_factor))

    return colorsys.hsv_to_rgb(h, s, v)


# ------------------------------------------------------------------------
# Adjust Colors Live Preview
# ------------------------------------------------------------------------

_PREVIEW_TIMER_PENDING = False
_PREVIEW_INTERNAL_CHANGE = False
_PREVIEW_PREFIX = "__VCT_PREVIEW__"


def _set_preview_active(settings, value):
    global _PREVIEW_INTERNAL_CHANGE
    _PREVIEW_INTERNAL_CHANGE = True
    try:
        settings.preview_active = value
    finally:
        _PREVIEW_INTERNAL_CHANGE = False


def _preview_target_object(settings):
    try:
        if settings.preview_object is not None:
            return settings.preview_object
    except ReferenceError:
        pass
    return (bpy.data.objects.get(settings.preview_object_name)
            if settings.preview_object_name else None)


def _clear_preview_state(settings):
    settings.preview_object = None
    settings.preview_object_name = ""
    settings.preview_source_name = ""
    settings.preview_temp_name = ""
    _set_preview_active(settings, False)

    try:
        context = bpy.context
        if context and getattr(context, "scene", None) and hasattr(context.scene, "vct_settings"):
            _sync_material_preview_attribute(context)
    except Exception:
        pass


def _remove_preview_attribute(settings):
    """Discard preview data without ever touching the source attribute."""
    obj = _preview_target_object(settings)
    if not obj or obj.type != 'MESH':
        _clear_preview_state(settings)
        return True, ""

    mesh = obj.data
    source_name = settings.preview_source_name
    temp_name = settings.preview_temp_name

    active_obj = bpy.context.view_layer.objects.active
    was_edit = obj.mode == 'EDIT'
    was_selected = obj.select_get()

    try:
        if was_edit:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.mode_set(mode='OBJECT')

        temp = mesh.color_attributes.get(temp_name)
        if temp:
            mesh.color_attributes.remove(temp)

        source = mesh.color_attributes.get(source_name)
        if source:
            set_active_color_attribute(mesh, source)

    except Exception as ex:
        return False, str(ex)

    finally:
        if was_edit and obj.name in bpy.context.view_layer.objects:
            bpy.context.view_layer.objects.active = obj
            try:
                bpy.ops.object.mode_set(mode='EDIT')
            except Exception:
                pass

        if active_obj and active_obj.name in bpy.context.view_layer.objects:
            bpy.context.view_layer.objects.active = active_obj
        if obj.name in bpy.context.view_layer.objects:
            obj.select_set(was_selected)

    _clear_preview_state(settings)
    return True, ""


def _apply_adjust_preview(context):
    """Rebuild the temporary preview layer from the untouched source layer.

    Object Mode: preview the entire Color Attribute.
    Edit Mode: preview only the current face/vertex selection.
    """
    settings = context.scene.vct_settings

    if not settings.preview_active:
        return True, ""

    obj = _preview_target_object(settings)
    if not obj or obj.type != 'MESH':
        _clear_preview_state(settings)
        return False, "Preview object is no longer available."

    if context.active_object != obj:
        _remove_preview_attribute(settings)
        return False, "Preview cancelled because the active object changed."

    if obj.mode not in {'OBJECT', 'EDIT'}:
        _remove_preview_attribute(settings)
        return False, "Live Preview is available in Object Mode or Edit Mode."

    mesh = obj.data
    source = mesh.color_attributes.get(settings.preview_source_name)
    temp = mesh.color_attributes.get(settings.preview_temp_name)

    if not source or not temp:
        _clear_preview_state(settings)
        return False, "Preview Color Attribute is no longer available."

    if source.domain != 'CORNER' or temp.domain != 'CORNER':
        _remove_preview_attribute(settings)
        return False, "Live Preview requires Face Corner Color Attributes."

    # Keep the temporary preview attribute visible.
    set_active_color_attribute(mesh, temp)

    try:
        _sync_material_preview_attribute(context)
    except Exception:
        pass

    if obj.mode == 'OBJECT':
        # Read/write contiguous arrays instead of making one Blender RNA call
        # per face corner. HSV math still comes from the untouched source.
        if len(source.data) != len(temp.data):
            _remove_preview_attribute(settings)
            return False, "Preview and source Color Attributes no longer match."

        values = array('f', [0.0]) * (4 * len(source.data))
        source.data.foreach_get("color", values)
        hue = settings.adjust_hue
        saturation = settings.adjust_saturation
        value = settings.adjust_value
        for index in range(0, len(values), 4):
            rgb = adjust_rgb(
                values[index:index + 3], hue, saturation, value
            )
            values[index] = rgb[0]
            values[index + 1] = rgb[1]
            values[index + 2] = rgb[2]

        temp.data.foreach_set("color", values)
        mesh.update()

    else:
        # Edit Mode previews only the current selected faces/vertices.
        bm = bmesh.from_edit_mesh(mesh)
        source_layer = get_bmesh_color_layer(bm, source)
        temp_layer = get_bmesh_color_layer(bm, temp)

        if source_layer is None or temp_layer is None:
            _remove_preview_attribute(settings)
            return False, "Could not access preview color data in Edit Mode."

        # Rebuild the complete preview from the untouched source first.
        for face in bm.faces:
            for loop in face.loops:
                loop[temp_layer] = loop[source_layer]

        edit_mode = get_effective_edit_mode(context)
        loops = get_selected_loops(bm, edit_mode)

        for loop in loops:
            original = color_from_bmesh(source, tuple(loop[source_layer]))

            rgb = adjust_rgb(
                original[:3],
                settings.adjust_hue,
                settings.adjust_saturation,
                settings.adjust_value,
            )

            adjusted = (rgb[0], rgb[1], rgb[2], original[3])
            loop[temp_layer] = color_to_bmesh(temp, adjusted)

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

    if context.screen is not None:
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

    return True, ""


def _preview_timer():
    global _PREVIEW_TIMER_PENDING
    _PREVIEW_TIMER_PENDING = False

    context = bpy.context
    scene = getattr(context, "scene", None)

    if not scene or not hasattr(scene, "vct_settings"):
        return None

    settings = scene.vct_settings
    if settings.preview_active:
        _apply_adjust_preview(context)

    return None


def _queue_preview_update():
    global _PREVIEW_TIMER_PENDING

    if _PREVIEW_TIMER_PENDING:
        return

    _PREVIEW_TIMER_PENDING = True
    bpy.app.timers.register(_preview_timer, first_interval=0.01)


def _on_adjustment_changed(self, context):
    if _PREVIEW_INTERNAL_CHANGE:
        return

    if self.preview_active:
        _queue_preview_update()


def _on_preview_property_changed(self, context):
    # preview_active is controlled by operators; this callback intentionally
    # does not start/stop previews on its own.
    return


def _start_adjust_preview(context):
    settings = context.scene.vct_settings

    if settings.preview_active:
        return _apply_adjust_preview(context)

    obj = get_active_mesh_object(context)
    if not obj:
        return False, "Select a mesh object."

    if obj.mode not in {'OBJECT', 'EDIT'}:
        return False, "Live Preview is available in Object Mode or Edit Mode."

    mesh = obj.data
    source = get_active_corner_attribute(mesh)

    if not source:
        return False, "Choose or create a Face Corner Color Attribute."

    # Edit Mode requires a sub-object selection. Object Mode deliberately
    # applies to the complete active Color Attribute.
    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(mesh)
        edit_mode = get_effective_edit_mode(context)
        loops = get_selected_loops(bm, edit_mode)

        if not loops:
            element = "faces" if edit_mode == 'FACE' else "vertices"
            return False, f"No {element} are selected."

    source_name = source.name
    source_type = source.data_type
    was_edit = obj.mode == 'EDIT'

    if was_edit:
        bpy.ops.object.mode_set(mode='OBJECT')

    try:
        # Do not remove similarly named user data or an unrelated preview.
        # Only the exact temporary attribute recorded below belongs to us.
        temp = mesh.color_attributes.new(
            name=_PREVIEW_PREFIX,
            type=source_type,
            domain='CORNER',
        )

        settings.preview_object = obj
        settings.preview_object_name = obj.name
        settings.preview_source_name = source_name
        settings.preview_temp_name = temp.name
        _set_preview_active(settings, True)

        set_active_color_attribute(mesh, temp)

    except Exception:
        _clear_preview_state(settings)
        if was_edit:
            bpy.ops.object.mode_set(mode='EDIT')
        raise

    if was_edit:
        bpy.ops.object.mode_set(mode='EDIT')

    success, message = _apply_adjust_preview(context)

    if not success:
        _remove_preview_attribute(settings)
        return False, message

    return True, ""


def _commit_adjust_preview(context):
    settings = context.scene.vct_settings

    if not settings.preview_active:
        return False, "Live Preview is not active."

    obj = _preview_target_object(settings)
    if not obj or obj.type != 'MESH':
        _clear_preview_state(settings)
        return False, "Preview object is no longer available."

    mesh = obj.data
    source_name = settings.preview_source_name
    temp_name = settings.preview_temp_name

    source = mesh.color_attributes.get(source_name)
    temp = mesh.color_attributes.get(temp_name)

    if not source or not temp:
        _clear_preview_state(settings)
        return False, "Preview Color Attribute is no longer available."

    active_obj = context.view_layer.objects.active
    was_edit = obj.mode == 'EDIT'

    try:
        # Leaving Edit Mode flushes the current BMesh preview into mesh data.
        if was_edit:
            context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.mode_set(mode='OBJECT')

        source = mesh.color_attributes.get(source_name)
        temp = mesh.color_attributes.get(temp_name)

        if not source or not temp:
            return False, "Preview Color Attribute is no longer available."

        if len(source.data) != len(temp.data):
            return False, "Preview and source Color Attributes no longer match."

        # Commit with bulk RNA access, preserving alpha and storage type.
        values = array('f', [0.0]) * (4 * len(temp.data))
        temp.data.foreach_get("color", values)
        source.data.foreach_set("color", values)

        mesh.color_attributes.remove(temp)
        set_active_color_attribute(mesh, source)

        try:
            _sync_material_preview_attribute(context)
        except Exception:
            pass

    except Exception as ex:
        return False, str(ex)

    finally:
        if was_edit and obj.name in context.view_layer.objects:
            context.view_layer.objects.active = obj
            try:
                bpy.ops.object.mode_set(mode='EDIT')
            except Exception:
                pass

        if active_obj and active_obj.name in context.view_layer.objects:
            context.view_layer.objects.active = active_obj

    _clear_preview_state(settings)
    return True, ""


def _cancel_adjust_preview(context):
    settings = context.scene.vct_settings

    if not settings.preview_active:
        return False, "Live Preview is not active."

    return _remove_preview_attribute(settings)


# ------------------------------------------------------------------------
# Properties
# ------------------------------------------------------------------------


class VCT_MaterialPreviewSlot(PropertyGroup):
    material: PointerProperty(
        name="Material",
        type=bpy.types.Material,
    )

    material_name: StringProperty(
        name="Material Name",
        default="",
    )

    link: EnumProperty(
        name="Link",
        items=[
            ('DATA', "Data", ""),
            ('OBJECT', "Object", ""),
        ],
        default='DATA',
    )


class VCT_PaletteItem(PropertyGroup):
    name: StringProperty(
        name="Name",
        default="Color",
    )

    color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.8, 0.8, 0.8, 1.0),
    )


class VCT_Settings(PropertyGroup):
    edit_mode: EnumProperty(
        name="Mode",
        items=[
            ('FACE', "Face", "Fill selected faces"),
            ('VERTEX', "Vertex", "Fill selected vertices and interpolate across faces"),
        ],
        default='FACE',
    )

    working_color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.8, 0.8, 0.8, 1.0),
    )

    strength: FloatProperty(
        name="Strength",
        description="How strongly the working color replaces the existing color",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )

    new_layer_name: StringProperty(
        name="New Attribute",
        default="Color",
    )

    storage_type: EnumProperty(
        name="Storage",
        items=[
            ('BYTE_COLOR', "Byte Color", "Compact 8-bit color storage"),
            ('FLOAT_COLOR', "Float Color", "32-bit floating-point color storage"),
        ],
        default='BYTE_COLOR',
    )

    affect_alpha: BoolProperty(
        name="Affect Alpha",
        description="Allow Fill Selection to modify the alpha channel",
        default=False,
    )

    select_tolerance: FloatProperty(
        name="Tolerance",
        description="Maximum per-channel difference for Select Similar",
        default=0.01,
        min=0.0,
        max=1.0,
        precision=3,
    )

    match_alpha: BoolProperty(
        name="Match Alpha",
        description="Include alpha when selecting similar colors",
        default=False,
    )


    adjust_hue: FloatProperty(
        name="Hue",
        description="Hue offset for selected colors",
        default=0.0,
        min=-0.5,
        max=0.5,
        update=_on_adjustment_changed,
    )

    adjust_saturation: FloatProperty(
        name="Saturation",
        description="Saturation multiplier",
        default=1.0,
        min=0.0,
        max=2.0,
        update=_on_adjustment_changed,
    )

    adjust_value: FloatProperty(
        name="Value",
        description="Value multiplier",
        default=1.0,
        min=0.0,
        max=2.0,
        update=_on_adjustment_changed,
    )

    preview_active: BoolProperty(
        name="Live Preview",
        default=False,
        options={'HIDDEN'},
        update=_on_preview_property_changed,
    )

    preview_object: PointerProperty(
        type=bpy.types.Object,
        options={'HIDDEN'},
    )

    preview_object_name: StringProperty(
        default="",
        options={'HIDDEN'},
    )

    preview_source_name: StringProperty(
        default="",
        options={'HIDDEN'},
    )

    preview_temp_name: StringProperty(
        default="",
        options={'HIDDEN'},
    )


    material_preview_active: BoolProperty(
        name="Material Preview Colors",
        default=False,
        options={'HIDDEN'},
    )

    material_preview_object: PointerProperty(
        type=bpy.types.Object,
        options={'HIDDEN'},
    )

    material_preview_material: PointerProperty(
        type=bpy.types.Material,
        options={'HIDDEN'},
    )

    material_preview_object_name: StringProperty(
        default="",
        options={'HIDDEN'},
    )

    material_preview_attribute_name: StringProperty(
        default="",
        options={'HIDDEN'},
    )

    material_preview_original_slot_count: IntProperty(
        default=0,
        options={'HIDDEN'},
    )


# ------------------------------------------------------------------------
# Color Attribute Menu
# ------------------------------------------------------------------------

class VCT_MT_color_attributes(Menu):
    bl_label = "Color Attributes"
    bl_idname = "VCT_MT_color_attributes"

    def draw(self, context):
        layout = self.layout
        obj = get_active_mesh_object(context)

        if not obj:
            layout.label(text="No active mesh")
            return

        attrs = obj.data.color_attributes
        if not attrs:
            layout.label(text="No Color Attributes")
            return

        active = get_safe_active_color_attribute(obj.data)

        for attr in attrs:
            if attr.name.startswith(_PREVIEW_PREFIX):
                continue

            label = attr.name

            if attr.domain != 'CORNER':
                label += "  [Unsupported Domain]"

            op = layout.operator(
                "vct.set_active_attribute",
                text=label,
                icon='CHECKMARK' if active and attr.name == active.name else 'NONE',
            )
            op.attribute_name = attr.name


# ------------------------------------------------------------------------
# Operators - Core
# ------------------------------------------------------------------------

class VCT_OT_set_active_attribute(Operator):
    bl_idname = "vct.set_active_attribute"
    bl_label = "Set Active Color Attribute"
    bl_options = {'REGISTER'}

    attribute_name: StringProperty()

    def execute(self, context):
        settings = context.scene.vct_settings
        if settings.preview_active:
            _cancel_adjust_preview(context)

        obj = get_active_mesh_object(context)
        if not obj:
            return {'CANCELLED'}

        attr = set_active_color_attribute(obj.data, self.attribute_name)
        if not attr:
            self.report({'ERROR'}, "Color Attribute not found.")
            return {'CANCELLED'}

        _sync_material_preview_attribute(context)
        return {'FINISHED'}


class VCT_OT_create_attribute(Operator):
    bl_idname = "vct.create_attribute"
    bl_label = "Create Color Attribute"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.vct_settings
        if settings.preview_active:
            _cancel_adjust_preview(context)

        obj = get_active_mesh_object(context)
        if not obj:
            self.report({'ERROR'}, "Select a mesh object.")
            return {'CANCELLED'}

        mesh = obj.data
        was_edit = obj.mode == 'EDIT'

        if was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')

        try:
            name = settings.new_layer_name.strip() or "Color"

            attr = mesh.color_attributes.new(
                name=name,
                type=settings.storage_type,
                domain='CORNER',
            )

            # Initialize in one bulk write rather than one RNA call/corner.
            whites = array('f', [1.0]) * (4 * len(attr.data))
            attr.data.foreach_set("color", whites)

            set_active_color_attribute(mesh, attr)

            try:
                mesh.color_attributes.default_color_name = attr.name
            except Exception:
                pass

        finally:
            if was_edit:
                bpy.ops.object.mode_set(mode='EDIT')

        _sync_material_preview_attribute(context)
        self.report({'INFO'}, f"Created Color Attribute: {attr.name}")
        return {'FINISHED'}


class VCT_OT_delete_attribute(Operator):
    bl_idname = "vct.delete_attribute"
    bl_label = "Delete Active Color Attribute"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Delete the selected Color Attribute and its stored colors"

    def invoke(self, context, event):
        obj = get_active_mesh_object(context)
        attr = get_safe_active_color_attribute(obj.data) if obj else None
        if attr is None:
            return {'CANCELLED'}
        return context.window_manager.invoke_confirm(
            self, event,
            title="Delete Color Attribute?",
            message=f"Delete '{attr.name}' from '{obj.name}'?",
            confirm_text="Delete Attribute",
            icon='WARNING',
        )

    @classmethod
    def poll(cls, context):
        obj = get_active_mesh_object(context)
        return bool(
            obj and get_safe_active_color_attribute(obj.data)
            and not context.scene.vct_settings.preview_active
        )

    def execute(self, context):
        settings = context.scene.vct_settings
        if settings.preview_active:
            self.report({'WARNING'}, "Apply or Cancel Live Preview before deleting.")
            return {'CANCELLED'}

        obj = get_active_mesh_object(context)
        mesh = obj.data
        attrs = mesh.color_attributes
        active = get_safe_active_color_attribute(mesh)

        if not active:
            return {'CANCELLED'}

        active_index = attrs.active_color_index
        active_name = active.name
        was_edit = obj.mode == 'EDIT'

        if was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')

        try:
            attr = attrs.get(active_name)
            if attr:
                attrs.remove(attr)

            if len(attrs) > 0:
                new_index = max(0, min(active_index, len(attrs) - 1))
                set_active_color_attribute(mesh, attrs[new_index])

        finally:
            if was_edit:
                bpy.ops.object.mode_set(mode='EDIT')

        _sync_material_preview_attribute(context)
        return {'FINISHED'}


class VCT_OT_enter_face_mode(Operator):
    bl_idname = "vct.enter_face_mode"
    bl_label = "Enter Face Edit Mode"
    bl_description = "Switch to Edit Mode with Face selection active"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(get_active_mesh_object(context))

    def execute(self, context):
        obj = get_active_mesh_object(context)
        
        if context.mode != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')
        
        bpy.ops.mesh.select_mode(type='FACE')
        context.scene.vct_settings.edit_mode = 'FACE'
        
        return {'FINISHED'}


class VCT_OT_enter_vertex_mode(Operator):
    bl_idname = "vct.enter_vertex_mode"
    bl_label = "Enter Vertex Edit Mode"
    bl_description = "Switch to Edit Mode with Vertex selection active"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(get_active_mesh_object(context))

    def execute(self, context):
        obj = get_active_mesh_object(context)
        
        if context.mode != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')
        
        bpy.ops.mesh.select_mode(type='VERT')
        context.scene.vct_settings.edit_mode = 'VERTEX'
        
        return {'FINISHED'}


class VCT_OT_set_edit_mode(Operator):
    bl_idname = "vct.set_edit_mode"
    bl_label = "Set Vertex Color Edit Mode"
    bl_options = {'REGISTER'}

    mode: EnumProperty(
        items=[
            ('FACE', "Face", ""),
            ('VERTEX', "Vertex", ""),
        ],
    )

    def execute(self, context):
        settings = context.scene.vct_settings
        settings.edit_mode = self.mode

        if context.mode == 'EDIT_MESH':
            if self.mode == 'FACE':
                context.tool_settings.mesh_select_mode = (False, False, True)
            else:
                context.tool_settings.mesh_select_mode = (True, False, False)

        if settings.preview_active:
            _apply_adjust_preview(context)

        return {'FINISHED'}


class VCT_OT_fill_selection(Operator):
    bl_idname = "vct.fill_selection"
    bl_label = "Fill Selection"
    bl_description = "Blend the working color into the selected faces or vertices using Strength"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        success, message = fill_selection_with_color(
            context,
            tuple(context.scene.vct_settings.working_color),
        )

        if not success:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        return {'FINISHED'}


class VCT_OT_sample_selection(Operator):
    bl_idname = "vct.sample_selection"
    bl_label = "Sample Selected"
    bl_description = "Sample the color of the active selected face or vertex"
    bl_options = {'REGISTER'}

    def execute(self, context):
        success, color, message = sample_selection_color(context)

        if not success:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        context.scene.vct_settings.working_color = color
        return {'FINISHED'}


# ------------------------------------------------------------------------
# Operators - Selection
# ------------------------------------------------------------------------

class VCT_OT_select_similar(Operator):
    bl_idname = "vct.select_similar"
    bl_label = "Select Similar Color"
    bl_options = {'REGISTER', 'UNDO'}

    extend: BoolProperty(default=False)

    def execute(self, context):
        obj, mesh, bm = get_edit_mesh(context)
        if not bm:
            self.report({'ERROR'}, "Enter Edit Mode on a mesh first.")
            return {'CANCELLED'}

        settings = context.scene.vct_settings
        attr = get_active_corner_attribute(mesh)

        if not attr:
            self.report({'ERROR'}, "Choose or create a Face Corner Color Attribute.")
            return {'CANCELLED'}

        layer = get_bmesh_color_layer(bm, attr)
        if layer is None:
            self.report({'ERROR'}, "The active Color Attribute is unavailable in Edit Mode.")
            return {'CANCELLED'}

        target = tuple(settings.working_color)
        edit_mode = get_effective_edit_mode(context)

        if edit_mode == 'FACE':
            if not self.extend:
                for face in bm.faces:
                    face.select = False

            found = 0

            for face in bm.faces:
                if face.hide:
                    continue

                face_color = average_colors([
                    color_from_bmesh(attr, tuple(loop[layer]))
                    for loop in face.loops
                ])

                if colors_match(
                    face_color,
                    target,
                    settings.select_tolerance,
                    settings.match_alpha,
                ):
                    face.select = True
                    found += 1

        else:
            if not self.extend:
                for vert in bm.verts:
                    vert.select = False

            found = 0

            for vert in bm.verts:
                if vert.hide:
                    continue

                vert_loops = loops_for_vertex(bm, vert)
                if not vert_loops:
                    continue

                vert_color = average_colors([
                    color_from_bmesh(attr, tuple(loop[layer]))
                    for loop in vert_loops
                ])

                if colors_match(
                    vert_color,
                    target,
                    settings.select_tolerance,
                    settings.match_alpha,
                ):
                    vert.select = True
                    found += 1

        bm.select_flush_mode()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        self.report({'INFO'}, f"Selected {found} matching elements.")
        return {'FINISHED'}


# ------------------------------------------------------------------------
# Operators - Palette
# ------------------------------------------------------------------------

class VCT_OT_palette_add(Operator):
    bl_idname = "vct.palette_add"
    bl_label = "Add Current Color"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        palette = context.scene.vct_palette
        item = palette.add()

        item.name = f"Color {len(palette):02d}"
        item.color = tuple(context.scene.vct_settings.working_color)

        context.scene.vct_palette_index = len(palette) - 1
        return {'FINISHED'}


class VCT_OT_palette_remove(Operator):
    bl_idname = "vct.palette_remove"
    bl_label = "Remove Palette Color"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        palette = context.scene.vct_palette

        if not palette:
            return {'CANCELLED'}

        index = max(
            0,
            min(context.scene.vct_palette_index, len(palette) - 1),
        )

        palette.remove(index)

        context.scene.vct_palette_index = max(
            0,
            min(index, len(palette) - 1),
        )

        return {'FINISHED'}


class VCT_OT_palette_use(Operator):
    bl_idname = "vct.palette_use"
    bl_label = "Use Palette Color"
    bl_options = {'REGISTER'}

    def execute(self, context):
        palette = context.scene.vct_palette
        if not palette:
            self.report({'ERROR'}, "Palette is empty.")
            return {'CANCELLED'}

        index = max(
            0,
            min(context.scene.vct_palette_index, len(palette) - 1),
        )

        context.scene.vct_settings.working_color = tuple(palette[index].color)
        return {'FINISHED'}


class VCT_OT_palette_fill(Operator):
    bl_idname = "vct.palette_fill"
    bl_label = "Fill With Palette Color"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        palette = context.scene.vct_palette
        if not palette:
            self.report({'ERROR'}, "Palette is empty.")
            return {'CANCELLED'}

        index = max(
            0,
            min(context.scene.vct_palette_index, len(palette) - 1),
        )

        color = tuple(palette[index].color)
        context.scene.vct_settings.working_color = color

        success, message = fill_selection_with_color(context, color)

        if not success:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        return {'FINISHED'}


class VCT_OT_palette_defaults(Operator):
    bl_idname = "vct.palette_defaults"
    bl_label = "Create Starter Palette"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        palette = context.scene.vct_palette

        defaults = [
            ("White",      (1.000, 1.000, 1.000, 1.000)),
            ("Light Gray", (0.650, 0.650, 0.650, 1.000)),
            ("Mid Gray",   (0.350, 0.350, 0.350, 1.000)),
            ("Black",      (0.000, 0.000, 0.000, 1.000)),
            ("Red",        (0.800, 0.050, 0.050, 1.000)),
            ("Green",      (0.050, 0.650, 0.120, 1.000)),
            ("Blue",       (0.050, 0.180, 0.800, 1.000)),
            ("Yellow",     (0.900, 0.700, 0.050, 1.000)),
        ]

        for name, color in defaults:
            item = palette.add()
            item.name = name
            item.color = color

        if palette:
            context.scene.vct_palette_index = 0

        return {'FINISHED'}


# ------------------------------------------------------------------------
# Operators - Adjust
# ------------------------------------------------------------------------

class VCT_OT_preview_adjustments(Operator):
    bl_idname = "vct.preview_adjustments"
    bl_label = "Live Preview"
    bl_description = "Preview Hue, Saturation, and Value adjustments without modifying the source Color Attribute"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.vct_settings

        if settings.preview_active:
            success, message = _apply_adjust_preview(context)
        else:
            success, message = _start_adjust_preview(context)

        if not success:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        return {'FINISHED'}


class VCT_OT_apply_adjustments(Operator):
    bl_idname = "vct.apply_adjustments"
    bl_label = "Apply"
    bl_description = "Commit the live color adjustment preview"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.vct_settings

        if settings.preview_active:
            success, message = _commit_adjust_preview(context)

            if not success:
                self.report({'ERROR'}, message)
                return {'CANCELLED'}

            return {'FINISHED'}

        # No preview active: perform a normal one-shot adjustment.
        obj = get_active_mesh_object(context)
        if not obj:
            self.report({'ERROR'}, "Select a mesh object.")
            return {'CANCELLED'}

        if obj.mode not in {'OBJECT', 'EDIT'}:
            self.report({'ERROR'}, "Adjust Colors is available in Object Mode or Edit Mode.")
            return {'CANCELLED'}

        mesh = obj.data
        attr = get_active_corner_attribute(mesh)

        if not attr:
            self.report({'ERROR'}, "Choose or create a Face Corner Color Attribute.")
            return {'CANCELLED'}

        if obj.mode == 'OBJECT':
            for element in attr.data:
                original = tuple(element.color)

                rgb = adjust_rgb(
                    original[:3],
                    settings.adjust_hue,
                    settings.adjust_saturation,
                    settings.adjust_value,
                )

                element.color = (
                    rgb[0],
                    rgb[1],
                    rgb[2],
                    original[3],
                )

            mesh.update()
            return {'FINISHED'}

        bm = bmesh.from_edit_mesh(mesh)
        layer = get_bmesh_color_layer(bm, attr)

        if layer is None:
            self.report({'ERROR'}, "The active Color Attribute is unavailable in Edit Mode.")
            return {'CANCELLED'}

        edit_mode = get_effective_edit_mode(context)
        loops = get_selected_loops(bm, edit_mode)

        if not loops:
            self.report({'ERROR'}, "Nothing is selected.")
            return {'CANCELLED'}

        for loop in loops:
            original = color_from_bmesh(attr, tuple(loop[layer]))

            rgb = adjust_rgb(
                original[:3],
                settings.adjust_hue,
                settings.adjust_saturation,
                settings.adjust_value,
            )

            adjusted = (rgb[0], rgb[1], rgb[2], original[3])
            loop[layer] = color_to_bmesh(attr, adjusted)

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        return {'FINISHED'}


class VCT_OT_cancel_adjustments(Operator):
    bl_idname = "vct.cancel_adjustments"
    bl_label = "Cancel"
    bl_description = "Discard the live preview and restore the untouched source Color Attribute"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bool(
            hasattr(context.scene, "vct_settings")
            and context.scene.vct_settings.preview_active
        )

    def execute(self, context):
        success, message = _cancel_adjust_preview(context)

        if not success:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        return {'FINISHED'}


class VCT_OT_reset_adjustments(Operator):
    bl_idname = "vct.reset_adjustments"
    bl_label = "Reset"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.vct_settings
        settings.adjust_hue = 0.0
        settings.adjust_saturation = 1.0
        settings.adjust_value = 1.0

        if settings.preview_active:
            _queue_preview_update()

        return {'FINISHED'}


# ------------------------------------------------------------------------
# Operators - Display
# ------------------------------------------------------------------------

class VCT_OT_show_colors(Operator):
    bl_idname = "vct.show_colors"
    bl_label = "Show Color Attribute"
    bl_options = {'REGISTER'}

    def execute(self, context):
        changed = 0

        for area in context.screen.areas:
            if area.type != 'VIEW_3D':
                continue

            shading = area.spaces.active.shading
            shading.type = 'SOLID'
            shading.color_type = 'VERTEX'

            area.tag_redraw()
            changed += 1

        if changed == 0:
            self.report({'WARNING'}, "No 3D Viewport found.")

        return {'FINISHED'}


class VCT_OT_set_color_preview_mode(Operator):
    bl_idname = "vct.set_color_preview_mode"
    bl_label = "Set Color Preview Mode"
    bl_description = "Choose the simplest viewport mode for previewing vertex colors"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        items=[
            ('SOLID', "Solid Colors", "Show the active Color Attribute directly in Solid View"),
            ('MATERIAL', "Material Preview", "Show the active Color Attribute through a temporary preview material"),
        ],
    )

    @classmethod
    def poll(cls, context):
        return bool(
            get_active_mesh_object(context)
            and context.area
            and context.area.type == 'VIEW_3D'
            and context.space_data
            and context.space_data.type == 'VIEW_3D'
        )

    def execute(self, context):
        settings = context.scene.vct_settings
        obj = get_active_mesh_object(context)
        shading = context.space_data.shading

        if self.mode == 'SOLID':
            # If temporary material preview is active, restore the object's
            # real materials before returning to direct Solid color display.
            if (
                settings.material_preview_active
                and settings.material_preview_object_name == obj.name
            ):
                success, message = _restore_material_preview(context)
                if not success:
                    self.report({'ERROR'}, message)
                    return {'CANCELLED'}

            shading.type = 'SOLID'
            shading.color_type = 'VERTEX'
            context.area.tag_redraw()
            return {'FINISHED'}

        # Material Preview
        if not (
            settings.material_preview_active
            and settings.material_preview_object_name == obj.name
        ):
            success, message = _toggle_material_preview(context)

            if not success:
                self.report({'ERROR'}, message)
                return {'CANCELLED'}
        else:
            _sync_material_preview_attribute(context)
            shading.type = 'MATERIAL'
            context.area.tag_redraw()

        return {'FINISHED'}


class VCT_OT_toggle_flat_lighting(Operator):
    bl_idname = "vct.toggle_flat_lighting"
    bl_label = "Flat Lighting"
    bl_description = "Toggle Solid View lighting between Flat and this viewport's previous lighting"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bool(
            context.area
            and context.area.type == 'VIEW_3D'
            and context.space_data
            and context.space_data.type == 'VIEW_3D'
        )

    def execute(self, context):
        shading = context.space_data.shading
        key = context.area.as_pointer()

        # Vertex-color display is part of the intended toolbox viewing mode.
        shading.type = 'SOLID'
        shading.color_type = 'VERTEX'

        if shading.light == 'FLAT':
            restore = _VCT_PREVIOUS_LIGHTING.get(key, 'STUDIO')

            if restore not in {'STUDIO', 'MATCAP'}:
                restore = 'STUDIO'

            shading.light = restore
        else:
            if shading.light in {'STUDIO', 'MATCAP'}:
                _VCT_PREVIOUS_LIGHTING[key] = shading.light
            else:
                _VCT_PREVIOUS_LIGHTING[key] = 'STUDIO'

            shading.light = 'FLAT'

        context.area.tag_redraw()
        return {'FINISHED'}


class VCT_OT_toggle_material_preview_colors(Operator):
    bl_idname = "vct.toggle_material_preview_colors"
    bl_label = "Material Preview Colors"
    bl_description = "Temporarily replace this object's materials with a preview material that displays the active Color Attribute"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(get_active_mesh_object(context))

    def execute(self, context):
        success, message = _toggle_material_preview(context)

        if not success:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        return {'FINISHED'}


class VCT_OT_show_material_color(Operator):
    bl_idname = "vct.show_material_color"
    bl_label = "Show Material Color"
    bl_options = {'REGISTER'}

    def execute(self, context):
        changed = 0

        for area in context.screen.areas:
            if area.type != 'VIEW_3D':
                continue

            shading = area.spaces.active.shading
            shading.type = 'SOLID'
            shading.color_type = 'MATERIAL'

            area.tag_redraw()
            changed += 1

        if changed == 0:
            self.report({'WARNING'}, "No 3D Viewport found.")

        return {'FINISHED'}


# ------------------------------------------------------------------------
# UI
# ------------------------------------------------------------------------

class VCT_UL_palette(UIList):
    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index,
    ):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "color", text="")
            row.prop(item, "name", text="", emboss=False)
        else:
            layout.prop(item, "color", text="")


class VCT_PT_main(Panel):
    bl_label = "Vertex Color Toolbox"
    bl_idname = "VCT_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "VColor"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is None or obj.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.vct_settings
        obj = get_active_mesh_object(context)

        # --------------------------------------------------------------
        # Core controls: intentionally always visible.
        # --------------------------------------------------------------

        if not obj:
            layout.label(text="Select a mesh object.", icon='INFO')
            return

        # Drawing does not modify scene data or viewport configuration.
        attrs = obj.data.color_attributes
        active = get_safe_active_color_attribute(obj.data)
        display_attr = (
            attrs.get(settings.preview_source_name)
            if settings.preview_active else active
        )
        has_color_data = bool(display_attr and display_attr.domain == 'CORNER')
        edit_ready = obj.mode == 'EDIT' and has_color_data
        paint_ready = edit_ready and not settings.preview_active

        if settings.preview_active and settings.preview_source_name:
            attribute_label = f"{settings.preview_source_name}  (Preview)"
        else:
            attribute_label = active.name if active else "Color Attribute"

        row = layout.row(align=True)
        row.menu(
            VCT_MT_color_attributes.bl_idname,
            text=attribute_label,
        )
        add = row.row(align=True)
        add.enabled = not settings.preview_active
        add.operator("vct.create_attribute", text="New", icon='ADD')
        remove = row.row(align=True)
        remove.enabled = bool(display_attr and not settings.preview_active)
        remove.operator("vct.delete_attribute", text="", icon='REMOVE')

        if display_attr is None:
            layout.label(text="No color data. Click New to begin.", icon='INFO')
        elif display_attr.domain != 'CORNER':
            warning = layout.row()
            warning.alert = True
            warning.label(text="Choose a Face Corner color attribute.", icon='ERROR')

        layout.label(text="Selection Mode")
        row = layout.row(align=True)
        effective_mode = get_effective_edit_mode(context)
        row.operator(
            "vct.enter_face_mode", text="Face", icon='FACESEL',
            depress=effective_mode == 'FACE' and obj.mode == 'EDIT',
        )
        row.operator(
            "vct.enter_vertex_mode", text="Vertex", icon='VERTEXSEL',
            depress=effective_mode == 'VERTEX' and obj.mode == 'EDIT',
        )

        layout.prop(settings, "working_color", text="Working Color")
        layout.prop(settings, "strength", slider=True)

        if obj.mode != 'EDIT':
            layout.label(text="Choose Face or Vertex to start editing.", icon='INFO')
        elif settings.preview_active:
            layout.label(text="Apply or Cancel preview before painting.", icon='INFO')

        col = layout.column(align=True)
        col.enabled = paint_ready
        col.scale_y = 1.25
        col.operator(
            "vct.fill_selection",
            text="Fill Selected Faces" if effective_mode == 'FACE'
            else "Fill Selected Vertices",
            icon='CHECKMARK',
        )
        col.operator(
            "vct.sample_selection",
            text="Sample Selected Color", icon='EYEDROPPER',
        )

        # --------------------------------------------------------------
        # Foldouts
        # --------------------------------------------------------------

        header, body = layout.panel("VCT_selection_foldout", default_closed=True)
        header.label(text="Selection")

        if body:
            body.enabled = edit_ready and not settings.preview_active
            row = body.row(align=True)

            op = row.operator("vct.select_similar", text="Select Similar")
            op.extend = False

            op = row.operator("vct.select_similar", text="Add Similar")
            op.extend = True

            body.prop(settings, "select_tolerance", slider=True)

            row = body.row(align=True)
            row.operator("mesh.select_more", text="Grow")
            row.operator("mesh.select_less", text="Shrink")

            row = body.row(align=True)

            op = row.operator("mesh.select_all", text="Invert")
            op.action = 'INVERT'

            op = row.operator("mesh.select_all", text="Clear")
            op.action = 'DESELECT'

        header, body = layout.panel("VCT_palette_foldout", default_closed=True)
        header.label(text="Palette")

        if body:
            body.template_list(
                "VCT_UL_palette",
                "",
                scene,
                "vct_palette",
                scene,
                "vct_palette_index",
                rows=4,
            )

            row = body.row(align=True)
            row.operator("vct.palette_add", text="Add Current", icon='ADD')
            row.operator("vct.palette_remove", text="", icon='REMOVE')

            row = body.row(align=True)
            row.operator("vct.palette_use", text="Use")
            fill_row = row.row(align=True)
            fill_row.enabled = paint_ready
            fill_row.operator("vct.palette_fill", text="Fill Selection")

            if not scene.vct_palette:
                body.operator("vct.palette_defaults", text="Create Starter Palette")

        header, body = layout.panel("VCT_adjust_foldout", default_closed=True)
        header.label(text="Adjust Colors")

        if body:
            if obj.mode == 'OBJECT':
                body.label(text="Scope: Entire Object", icon='OBJECT_DATA')
            elif obj.mode == 'EDIT':
                scope_mode = get_effective_edit_mode(context)
                scope_name = "Selected Faces" if scope_mode == 'FACE' else "Selected Vertices"
                body.label(text=f"Scope: {scope_name}", icon='RESTRICT_SELECT_OFF')
            else:
                body.label(text="Use Object Mode or Edit Mode", icon='INFO')

            body.prop(settings, "adjust_hue", slider=True)
            body.prop(settings, "adjust_saturation", slider=True)
            body.prop(settings, "adjust_value", slider=True)

            preview_row = body.row()
            preview_row.enabled = has_color_data and obj.mode in {'OBJECT', 'EDIT'}
            preview_row.scale_y = 1.1
            preview_row.operator(
                "vct.preview_adjustments",
                text="Update Preview" if settings.preview_active else "Start Live Preview",
                icon='HIDE_OFF',
                depress=settings.preview_active,
            )

            if settings.preview_active:
                status = body.row()
                status.label(text="Previewing temporary color data", icon='INFO')

            row = body.row(align=True)
            apply_row = row.row(align=True)
            apply_row.enabled = has_color_data and obj.mode in {'OBJECT', 'EDIT'}
            apply_row.operator(
                "vct.apply_adjustments",
                text="Commit Preview" if settings.preview_active else "Apply Adjustment",
                icon='CHECKMARK',
            )

            cancel = row.row(align=True)
            cancel.enabled = settings.preview_active
            cancel.operator("vct.cancel_adjustments", text="Cancel", icon='X')

            body.operator("vct.reset_adjustments", text="Reset")

        header, body = layout.panel("VCT_display_foldout", default_closed=True)
        header.label(text="Display")

        if body:
            shading = context.space_data.shading
            material_preview_active = (
                settings.material_preview_active
                and _preview_material_target_object(settings) == obj
            )

            body.label(text="Preview Mode")

            row = body.row(align=True)

            op = row.operator(
                "vct.set_color_preview_mode",
                text="Solid Colors",
                icon='SHADING_SOLID',
                depress=(shading.type == 'SOLID' and not material_preview_active),
            )
            op.mode = 'SOLID'

            material_row = row.row(align=True)
            material_row.enabled = bool(obj.material_slots)
            op = material_row.operator(
                "vct.set_color_preview_mode",
                text="Material Preview",
                icon='MATERIAL',
                depress=material_preview_active,
            )
            op.mode = 'MATERIAL'
            if not obj.material_slots:
                body.label(text="Material Preview needs a material slot.", icon='INFO')

            # Flat Lighting only has meaning in Solid View, so keep it
            # contextual instead of presenting it as a competing preview mode.
            if not material_preview_active:
                body.separator()
                body.label(text="Solid Lighting")

                body.operator(
                    "vct.toggle_flat_lighting",
                    text="Flat Lighting",
                    icon='SHADING_SOLID',
                    depress=(shading.light == 'FLAT'),
                )

                if shading.light == 'FLAT':
                    restore = _VCT_PREVIOUS_LIGHTING.get(
                        context.area.as_pointer(),
                        'STUDIO',
                    )
                    body.label(
                        text=f"Toggle off to restore {restore.title()}",
                        icon='INFO',
                    )
            elif settings.material_preview_attribute_name:
                body.label(
                    text=f"Attribute: {settings.material_preview_attribute_name}",
                    icon='INFO',
                )

        header, body = layout.panel("VCT_advanced_foldout", default_closed=True)
        header.label(text="Advanced")

        if body:
            display_attr = active
            if settings.preview_active and settings.preview_source_name:
                display_attr = obj.data.color_attributes.get(settings.preview_source_name)

            if display_attr:
                body.label(text=f"Domain: {display_attr.domain}")
                body.label(text=f"Storage: {display_attr.data_type}")
            else:
                body.label(text="No active Color Attribute.")

            body.separator()
            body.label(text="New Color Attributes")
            body.prop(settings, "new_layer_name")
            body.prop(settings, "storage_type")
            body.prop(settings, "affect_alpha")
            body.prop(settings, "match_alpha")


# ------------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------------

classes = (
    VCT_MaterialPreviewSlot,
    VCT_PaletteItem,
    VCT_Settings,
    VCT_MT_color_attributes,
    VCT_OT_set_active_attribute,
    VCT_OT_create_attribute,
    VCT_OT_delete_attribute,
    VCT_OT_enter_face_mode,
    VCT_OT_enter_vertex_mode,
    VCT_OT_set_edit_mode,
    VCT_OT_fill_selection,
    VCT_OT_sample_selection,
    VCT_OT_select_similar,
    VCT_OT_palette_add,
    VCT_OT_palette_remove,
    VCT_OT_palette_use,
    VCT_OT_palette_fill,
    VCT_OT_palette_defaults,
    VCT_OT_preview_adjustments,
    VCT_OT_apply_adjustments,
    VCT_OT_cancel_adjustments,
    VCT_OT_reset_adjustments,
    VCT_OT_show_colors,
    VCT_OT_set_color_preview_mode,
    VCT_OT_toggle_flat_lighting,
    VCT_OT_toggle_material_preview_colors,
    VCT_OT_show_material_color,
    VCT_UL_palette,
    VCT_PT_main,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.vct_settings = PointerProperty(type=VCT_Settings)
    bpy.types.Scene.vct_palette = CollectionProperty(type=VCT_PaletteItem)
    bpy.types.Scene.vct_palette_index = IntProperty(default=0)
    bpy.types.Scene.vct_material_preview_slots = CollectionProperty(type=VCT_MaterialPreviewSlot)

    for handlers, callback in (
        (bpy.app.handlers.save_pre, _vct_save_pre),
        (bpy.app.handlers.load_post, _vct_load_post),
        (bpy.app.handlers.undo_post, _vct_undo_post),
        (bpy.app.handlers.redo_post, _vct_redo_post),
    ):
        if callback not in handlers:
            handlers.append(callback)

    # No mesh or viewport changes when enabling the add-on.


def unregister():
    _cleanup_all_previews()

    for handlers, callback in (
        (bpy.app.handlers.save_pre, _vct_save_pre),
        (bpy.app.handlers.load_post, _vct_load_post),
        (bpy.app.handlers.undo_post, _vct_undo_post),
        (bpy.app.handlers.redo_post, _vct_redo_post),
    ):
        if callback in handlers:
            handlers.remove(callback)

    for callback in (_deferred_preview_cleanup, _preview_timer):
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)

    _VCT_PREVIOUS_LIGHTING.clear()
    _VCT_PREVIOUS_SHADING_TYPE.clear()

    del bpy.types.Scene.vct_material_preview_slots
    del bpy.types.Scene.vct_palette_index
    del bpy.types.Scene.vct_palette
    del bpy.types.Scene.vct_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()