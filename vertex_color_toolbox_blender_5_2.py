bl_info = {
    "name": "Vertex Color Toolbox",
    "author": "James Arndt",
    "version": (2, 4, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar > VColor",
    "description": "Compact Edit Mode vertex-color workflow inspired by 3ds Max VertexPaint",
    "category": "Mesh",
}

import bpy
import bmesh
import colorsys

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
# Automatic Setup
# ------------------------------------------------------------------------

_VCT_MSG_OWNER = object()
_VCT_SETUP_PENDING = False
_VCT_PREVIOUS_LIGHTING = {}
_VCT_PREVIOUS_SHADING_TYPE = {}
_VCT_MATERIAL_PREVIEW_MATERIAL_NAME = "__VCT_VertexColorPreview__"


def _initialize_color_attribute_for_object(obj):
    """Ensure a compatible Face Corner color attribute exists and is active."""
    if not obj or obj.type != 'MESH':
        return None

    mesh = obj.data

    corner_attrs = [
        attr for attr in mesh.color_attributes
        if attr.domain == 'CORNER'
        and not attr.name.startswith(_PREVIEW_PREFIX)
    ]

    if corner_attrs:
        active = get_safe_active_color_attribute(mesh)
        if not active or active.domain != 'CORNER':
            set_active_color_attribute(mesh, corner_attrs[0])
            return corner_attrs[0]
        return active

    # Create directly in the current mode. No Object/Edit mode switching.
    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(mesh)

        base_name = 'Color'
        name = base_name
        suffix = 1
        existing_names = {attr.name for attr in mesh.color_attributes}

        while name in existing_names:
            name = f'{base_name}.{suffix:03d}'
            suffix += 1

        layer = bm.loops.layers.color.new(name)

        for face in bm.faces:
            for loop in face.loops:
                loop[layer] = (1.0, 1.0, 1.0, 1.0)

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

        attr = mesh.color_attributes.get(name)
        if attr:
            set_active_color_attribute(mesh, attr)
            try:
                mesh.color_attributes.default_color_name = attr.name
            except Exception:
                pass

        return attr

    attr = mesh.color_attributes.new(
        name='Color',
        type='BYTE_COLOR',
        domain='CORNER',
    )

    for element in attr.data:
        element.color = (1.0, 1.0, 1.0, 1.0)

    set_active_color_attribute(mesh, attr)

    try:
        mesh.color_attributes.default_color_name = attr.name
    except Exception:
        pass

    return attr


def _setup_current_active_object():
    """Initialize the current active mesh outside panel drawing."""
    global _VCT_SETUP_PENDING
    _VCT_SETUP_PENDING = False

    try:
        obj = bpy.context.active_object
        if obj and obj.type == 'MESH':
            _initialize_color_attribute_for_object(obj)
    except Exception:
        # Never let initialization interfere with Blender interaction.
        pass

    return None


def _schedule_active_object_setup():
    global _VCT_SETUP_PENDING

    if _VCT_SETUP_PENDING:
        return

    _VCT_SETUP_PENDING = True
    bpy.app.timers.register(_setup_current_active_object, first_interval=0.0)


def _on_active_object_changed():
    # The message-bus callback only schedules setup. It does not touch panel UI
    # and only fires when Blender's active object changes.
    _schedule_active_object_setup()


def _subscribe_active_object():
    bpy.msgbus.clear_by_owner(_VCT_MSG_OWNER)
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.LayerObjects, 'active'),
        owner=_VCT_MSG_OWNER,
        args=(),
        notify=_on_active_object_changed,
        options={'PERSISTENT'},
    )


def _set_default_viewport_display():
    """Set existing 3D viewports to Solid + Color Attribute once."""
    try:
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue

                space = area.spaces.active
                if not space or space.type != 'VIEW_3D':
                    continue

                shading = space.shading
                shading.type = 'SOLID'
                shading.color_type = 'VERTEX'
                area.tag_redraw()
    except Exception:
        pass


def _initial_setup_timer():
    _set_default_viewport_display()
    _setup_current_active_object()
    return None


@persistent
def _vct_load_post(_dummy):
    # Blender clears message-bus subscriptions when a new .blend loads.
    _subscribe_active_object()
    bpy.app.timers.register(_initial_setup_timer, first_interval=0.0)


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
    if not settings.material_preview_object_name:
        return None
    return bpy.data.objects.get(settings.material_preview_object_name)


def _get_material_preview_attribute_name(obj, settings):
    """Return the color attribute that should currently drive material preview."""
    if not obj or obj.type != 'MESH':
        return None

    mesh = obj.data

    # If HSV Live Preview is active, display the temporary preview attribute.
    if (
        settings.preview_active
        and settings.preview_object_name == obj.name
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


def _ensure_material_preview_material(attribute_name):
    """Create/update the temporary preview material."""
    mat = bpy.data.materials.get(_VCT_MATERIAL_PREVIEW_MATERIAL_NAME)

    if mat is None:
        mat = bpy.data.materials.new(_VCT_MATERIAL_PREVIEW_MATERIAL_NAME)

    mat.use_nodes = True
    mat.use_fake_user = True

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


def _restore_material_preview(context):
    """Restore the object's original material assignments and viewport shading."""
    settings = context.scene.vct_settings

    if not settings.material_preview_active:
        return True, ""

    obj = _preview_material_target_object(settings)

    if not obj or obj.type != 'MESH':
        settings.material_preview_active = False
        settings.material_preview_object_name = ""
        settings.material_preview_attribute_name = ""
        settings.material_preview_original_slot_count = 0
        context.scene.vct_material_preview_slots.clear()
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

                    slot.material = material

        # If the object originally had no slots, remove the temporary slot.
        elif len(obj.material_slots) > 0:
            # The preview only adds a slot in the zero-slot case.
            obj.data.materials.clear()

        # Restore the viewport shading type used before preview.
        if (
            context.area
            and context.area.type == 'VIEW_3D'
            and context.space_data
            and context.space_data.type == 'VIEW_3D'
        ):
            key = context.area.as_pointer()
            previous = _VCT_PREVIOUS_SHADING_TYPE.pop(key, None)

            if previous:
                context.space_data.shading.type = previous

            context.area.tag_redraw()

    except Exception as ex:
        return False, str(ex)

    settings.material_preview_active = False
    settings.material_preview_object_name = ""
    settings.material_preview_attribute_name = ""
    settings.material_preview_original_slot_count = 0
    stored_slots.clear()

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

    mat = _ensure_material_preview_material(attribute_name)
    settings.material_preview_attribute_name = attribute_name

    # Re-assert the preview material in case a slot changed while previewing.
    for slot in obj.material_slots:
        try:
            slot.link = 'OBJECT'
        except Exception:
            pass
        slot.material = mat

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

    stored_slots = context.scene.vct_material_preview_slots
    stored_slots.clear()

    # Preserve material pointer + link mode for every existing slot.
    for slot in obj.material_slots:
        item = stored_slots.add()
        item.material = slot.material
        item.material_name = slot.material.name if slot.material else ""
        item.link = slot.link

    settings.material_preview_active = True
    settings.material_preview_object_name = obj.name
    settings.material_preview_attribute_name = attribute_name
    settings.material_preview_original_slot_count = len(obj.material_slots)

    preview_mat = _ensure_material_preview_material(attribute_name)

    if len(obj.material_slots) == 0:
        # Zero-slot objects need one temporary slot for Material Preview.
        obj.data.materials.append(preview_mat)
        try:
            obj.material_slots[0].link = 'OBJECT'
        except Exception:
            pass
    else:
        # OBJECT link prevents changing the underlying mesh material data for
        # existing slots, which is safer for meshes shared by multiple objects.
        for slot in obj.material_slots:
            try:
                slot.link = 'OBJECT'
            except Exception:
                pass
            slot.material = preview_mat

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
    """Get face-corner data affected by the current artist-facing edit mode."""
    loops = []

    if edit_mode == 'FACE':
        for face in bm.faces:
            if face.select and not face.hide:
                loops.extend(face.loops)
        return loops

    for vert in bm.verts:
        if vert.select and not vert.hide:
            loops.extend(loops_for_vertex(bm, vert))

    return loops


def fill_selection_with_color(context, color):
    obj, mesh, bm = get_edit_mesh(context)
    if not bm:
        return False, "Enter Edit Mode on a mesh first."

    settings = context.scene.vct_settings
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

    target = tuple(color)

    for loop in loops:
        existing = color_from_bmesh(attr, tuple(loop[layer]))
        result = mix_color(
            existing,
            target,
            settings.strength,
            settings.affect_alpha,
        )
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
    if not settings.preview_object_name:
        return None
    return bpy.data.objects.get(settings.preview_object_name)


def _clear_preview_state(settings):
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
        # Object Mode previews the entire active color attribute.
        if len(source.data) != len(temp.data):
            _remove_preview_attribute(settings)
            return False, "Preview and source Color Attributes no longer match."

        for index in range(len(source.data)):
            original = tuple(source.data[index].color)

            rgb = adjust_rgb(
                original[:3],
                settings.adjust_hue,
                settings.adjust_saturation,
                settings.adjust_value,
            )

            temp.data[index].color = (
                rgb[0],
                rgb[1],
                rgb[2],
                original[3],
            )

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
        # Clean up any stale preview attribute from a previous interrupted run.
        for attr in list(mesh.color_attributes):
            if attr.name.startswith(_PREVIEW_PREFIX):
                mesh.color_attributes.remove(attr)

        temp = mesh.color_attributes.new(
            name=_PREVIEW_PREFIX,
            type=source_type,
            domain='CORNER',
        )

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

        # Commit the temporary preview into the real source attribute.
        for index in range(len(source.data)):
            source.data[index].color = temp.data[index].color

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

            for element in attr.data:
                element.color = (1.0, 1.0, 1.0, 1.0)

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

    @classmethod
    def poll(cls, context):
        obj = get_active_mesh_object(context)
        return bool(obj and get_safe_active_color_attribute(obj.data))

    def execute(self, context):
        settings = context.scene.vct_settings
        if settings.preview_active:
            _cancel_adjust_preview(context)

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

        row = layout.row(align=True)
        row.operator("vct.enter_face_mode", text="Face Mode", icon='FACESEL')
        row.operator("vct.enter_vertex_mode", text="Vertex Mode", icon='VERTEXSEL')
        layout.separator()
        
        # Panel drawing is intentionally read-only. Automatic mesh/view setup
        # is handled by registration and active-object notifications.
        attrs = obj.data.color_attributes
        active = get_safe_active_color_attribute(obj.data)

        if settings.preview_active and settings.preview_source_name:
            attribute_label = f"{settings.preview_source_name}  (Preview)"
        else:
            attribute_label = active.name if active else "Color Attribute"

        row = layout.row(align=True)
        row.menu(
            VCT_MT_color_attributes.bl_idname,
            text=attribute_label,
        )
        row.operator("vct.create_attribute", text="", icon='ADD')
        row.operator("vct.delete_attribute", text="", icon='REMOVE')

        if active and active.domain != 'CORNER':
            warning = layout.row()
            warning.alert = True
            warning.label(text="Active attribute is not Face Corner data.", icon='ERROR')

        layout.prop(settings, "working_color", text="Color")
        layout.prop(settings, "strength", slider=True)

        row = layout.row(align=True)
        effective_mode = get_effective_edit_mode(context)

        op = row.operator(
            "vct.set_edit_mode",
            text="Face",
            depress=effective_mode == 'FACE',
            icon='FACESEL',
        )
        op.mode = 'FACE'

        op = row.operator(
            "vct.set_edit_mode",
            text="Vertex",
            depress=effective_mode == 'VERTEX',
            icon='VERTEXSEL',
        )
        op.mode = 'VERTEX'

        col = layout.column(align=True)
        col.scale_y = 1.25
        col.operator("vct.fill_selection", text="Fill Selection", icon='CHECKMARK')

        layout.operator(
            "vct.sample_selection",
            text="Sample Selected",
            icon='EYEDROPPER',
        )

        # --------------------------------------------------------------
        # Foldouts
        # --------------------------------------------------------------

        header, body = layout.panel("VCT_selection_foldout", default_closed=True)
        header.label(text="Selection")

        if body:
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
            row.operator("vct.palette_fill", text="Fill Selection")

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
            preview_row.scale_y = 1.1
            preview_row.operator(
                "vct.preview_adjustments",
                text="Live Preview",
                icon='HIDE_OFF',
                depress=settings.preview_active,
            )

            if settings.preview_active:
                status = body.row()
                status.label(text="Previewing temporary color data", icon='INFO')

            row = body.row(align=True)
            row.operator("vct.apply_adjustments", text="Apply", icon='CHECKMARK')

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
                and settings.material_preview_object_name == obj.name
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

            op = row.operator(
                "vct.set_color_preview_mode",
                text="Material Preview",
                icon='MATERIAL',
                depress=material_preview_active,
            )
            op.mode = 'MATERIAL'

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

    _subscribe_active_object()

    if _vct_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_vct_load_post)

    # Do the first setup after registration, before normal tool interaction.
    bpy.app.timers.register(_initial_setup_timer, first_interval=0.0)


def unregister():
    bpy.msgbus.clear_by_owner(_VCT_MSG_OWNER)

    if _vct_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_vct_load_post)

    _VCT_PREVIOUS_LIGHTING.clear()
    _VCT_PREVIOUS_SHADING_TYPE.clear()

    try:
        scene = bpy.context.scene
        if scene and hasattr(scene, "vct_settings"):
            settings = scene.vct_settings
            if settings.material_preview_active:
                _restore_material_preview(bpy.context)
            if settings.preview_active:
                _remove_preview_attribute(settings)
    except Exception:
        pass

    del bpy.types.Scene.vct_material_preview_slots
    del bpy.types.Scene.vct_palette_index
    del bpy.types.Scene.vct_palette
    del bpy.types.Scene.vct_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()