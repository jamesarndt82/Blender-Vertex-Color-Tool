"""Optional, non-gating Blender 5.2+ performance benchmark.

From repository root:
  blender --background --factory-startup --python tests/blender_phase2_benchmark.py

Reports wall-clock times for selection scanning, full-strength fill, and
Object Mode HSV preview. No time thresholds: hardware and geometry vary.
"""
from pathlib import Path
from statistics import median
from time import perf_counter
import importlib.util

import bpy
import bmesh


addon = Path(__file__).resolve().parents[1] / "vertex_color_toolbox_blender_5_2.py"
spec = importlib.util.spec_from_file_location("vct_bench", addon)
vct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vct)


def measured(label, fn, repeats=3):
    measurements = []
    for _ in range(repeats):
        start = perf_counter()
        fn()
        measurements.append(perf_counter() - start)
    print(f"VCT BENCH {label}: {median(measurements)*1000:.2f} ms "
          f"(median of {repeats})")


vct.register()
try:
    mesh = bpy.data.meshes.new("VCT Benchmark Mesh")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=160, y_segments=160, size=10)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    obj = bpy.data.objects.new("VCT Benchmark", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    settings = bpy.context.scene.vct_settings
    bpy.ops.vct.create_attribute()
    print(f"VCT BENCH geometry: {len(mesh.polygons)} faces, "
          f"{len(mesh.loops)} face corners")

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_mode(type='VERT')
    bpy.ops.mesh.select_all(action='SELECT')
    edit_bm = bmesh.from_edit_mesh(mesh)

    # Legacy reference collection logic for relative selection cost.
    def legacy_selected_loops():
        loops = []
        for vert in edit_bm.verts:
            if vert.select and not vert.hide:
                loops.extend(vct.loops_for_vertex(edit_bm, vert))
        return loops

    modern = vct.get_selected_loops(edit_bm, 'VERTEX')
    legacy = legacy_selected_loops()
    assert len(modern) == len(legacy), "Selection traversal changed number of corners"

    measured("old selected corners", legacy_selected_loops)
    measured("new selected corners", lambda: vct.get_selected_loops(edit_bm, 'VERTEX'))

    settings.strength = 1.0
    settings.affect_alpha = False
    settings.working_color = (0.2, 0.65, 0.8, 1.0)
    measured("full strength fill", lambda: vct.fill_selection_with_color(
        bpy.context, tuple(settings.working_color)
    ))

    bpy.ops.object.mode_set(mode='OBJECT')
    settings.adjust_hue = 0.25
    ok, message = vct._start_adjust_preview(bpy.context)
    assert ok, message
    measured("HSV preview refresh", lambda: vct._apply_adjust_preview(bpy.context))
    vct._cancel_adjust_preview(bpy.context)

    print("VCT PHASE 2 BENCHMARK: COMPLETE (informational only)")
finally:
    vct.unregister()
