"""Phase 2 Blender 5.2+ integration smoke tests.

Run:
  & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --background --factory-startup --python tests\\blender_phase2_smoke.py

Requires Blender: CI's Python-only source tests are not a runtime substitute.
"""
import importlib.util
from pathlib import Path

import bmesh
import bpy


path = Path(__file__).resolve().parents[1] / "vertex_color_toolbox_blender_5_2.py"
spec = importlib.util.spec_from_file_location("vct_phase2_addon", path)
vct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vct)


def require(value, description):
    if not value:
        raise AssertionError(description)


def near(a, b, tolerance=0.025):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def edit_mesh_state(mesh, attribute_name):
    """Fetch fresh Edit Mode handles after each bpy.ops invocation.

    Blender can invalidate BMesh layer handles on operator/undo/mode changes.
    Failing here also distinguishes a missing layer from incorrect fill data.
    """
    bm = bmesh.from_edit_mesh(mesh)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    attr = mesh.color_attributes.get(attribute_name)
    require(attr is not None, f"Color Attribute {attribute_name!r} disappeared")
    layer = vct.get_bmesh_color_layer(bm, attr)
    require(
        layer is not None,
        f"Missing BMesh layer {attribute_name!r} ({attr.data_type} / {attr.domain}); "
        f"byte layers={list(bm.loops.layers.color.keys())!r}; "
        f"float layers={list(bm.loops.layers.float_color.keys())!r}",
    )
    return bm, attr, layer


vct.register()
try:
    mesh = bpy.data.meshes.new("VCT Phase 2 Mesh")
    mesh.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        [],
        [(0, 1, 2), (0, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new("VCT Phase 2 Object", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    settings = bpy.context.scene.vct_settings
    settings.new_layer_name = "Color"
    settings.storage_type = 'BYTE_COLOR'
    require(bpy.ops.vct.create_attribute() == {'FINISHED'}, "Byte attribute create failed")
    attribute = mesh.color_attributes.active_color
    attribute_name = attribute.name
    require(all(near(element.color, (1, 1, 1, 1)) for element in attribute.data),
            "Bulk initialization did not produce white")

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_mode(type='FACE')
    bm, attribute, layer = edit_mesh_state(mesh, attribute_name)
    for face in bm.faces:
        face.select_set(False)
    bm.faces[0].select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(mesh)

    settings.strength = 1.0
    settings.affect_alpha = True
    settings.working_color = (1, 0, 0, 0.5)
    require(bpy.ops.vct.fill_selection() == {'FINISHED'}, "Full-strength fill failed")
    bm, attribute, layer = edit_mesh_state(mesh, attribute_name)
    require(all(near(vct.color_from_bmesh(attribute, tuple(loop[layer]))[:3],
                         (1, 0, 0)) for loop in bm.faces[0].loops),
            "Face fill did not paint selected face red")
    require(all(near(vct.color_from_bmesh(attribute, tuple(loop[layer]))[:3],
                         (1, 1, 1)) for loop in bm.faces[1].loops),
            "Face fill modified an unselected face")

    # Full-strength replacement must preserve alpha when affect_alpha is off.
    original_alpha = [loop[layer][3] for loop in bm.faces[0].loops]
    settings.affect_alpha = False
    settings.working_color = (0, 1, 0, 1)
    require(bpy.ops.vct.fill_selection() == {'FINISHED'}, "Second face fill failed")
    bm, attribute, layer = edit_mesh_state(mesh, attribute_name)
    require(all(abs(loop[layer][3] - alpha) < 0.01
                for loop, alpha in zip(bm.faces[0].loops, original_alpha)),
            "Fast fill changed alpha with Affect Alpha disabled")

    # Selecting the shared vertex must paint its two corners but no others.
    bpy.ops.mesh.select_mode(type='VERT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bm, attribute, layer = edit_mesh_state(mesh, attribute_name)
    bm.verts[0].select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(mesh)
    require(len(vct.get_selected_loops(bm, 'VERTEX')) == 2,
            "Selected vertex did not resolve to exactly two face corners")
    settings.working_color = (0, 0, 1, 1)
    require(bpy.ops.vct.fill_selection() == {'FINISHED'}, "Vertex fill failed")
    bm, attribute, layer = edit_mesh_state(mesh, attribute_name)
    for face in bm.faces:
        for loop in face.loops:
            painted = vct.color_from_bmesh(attribute, tuple(loop[layer]))
            if loop.vert == bm.verts[0]:
                require(near(painted[:3], (0, 0, 1)), "Selected corner was not blue")
            else:
                require(not near(painted[:3], (0, 0, 1)), "Unselected corner was painted")

    bpy.ops.object.mode_set(mode='OBJECT')
    source = mesh.color_attributes.get(attribute_name)
    require(source is not None, "Source Color Attribute missing after Edit Mode")
    before = [tuple(value.color) for value in source.data]
    settings.adjust_hue = 0.2
    require(vct._start_adjust_preview(bpy.context)[0], "Bulk HSV preview failed")
    temp = mesh.color_attributes.get(settings.preview_temp_name)
    require(temp is not None, "HSV preview layer missing")
    require([tuple(value.color) for value in source.data] == before,
            "Preview changed source values")
    settings.adjust_hue = 0.4
    require(vct._apply_adjust_preview(bpy.context)[0], "HSV refresh failed")
    expected = [(*vct.adjust_rgb(c[:3], 0.4, 1.0, 1.0), c[3]) for c in before]
    require(all(near(v.color, e) for v, e in zip(temp.data, expected)),
            "Bulk HSV preview differs from original HSV math")
    require(vct._commit_adjust_preview(bpy.context)[0], "HSV bulk commit failed")
    require(not settings.preview_active, "HSV preview state not cleared")
    source = mesh.color_attributes.get(attribute_name)
    require(source is not None, "Source attribute missing after HSV commit")
    require(all(near(v.color, e) for v, e in zip(source.data, expected)),
            "Bulk HSV commit did not copy preview colors")

    settings.new_layer_name = "FloatColor"
    settings.storage_type = 'FLOAT_COLOR'
    require(bpy.ops.vct.create_attribute() == {'FINISHED'}, "Float attribute create failed")
    require(mesh.color_attributes.active_color.data_type == 'FLOAT_COLOR',
            "Float attribute storage type lost")
    require(all(near(v.color, (1, 1, 1, 1), 0.0001)
                for v in mesh.color_attributes.active_color.data),
            "Float initialization failed")

    print("VCT PHASE 2 BLENDER SMOKE: PASS")
finally:
    vct.unregister()
