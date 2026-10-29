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
import os

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
    elapsed = median(measurements)
    print(f"VCT BENCH {label}: {elapsed*1000:.2f} ms "
          f"(median of {repeats})")
    return elapsed


vct.register()
try:
    mesh = bpy.data.meshes.new("VCT Benchmark Mesh")
    bm = bmesh.new()
    # 160 -> 102,400 corners; 500 -> 1,000,000 corners.
    segments = int(os.environ.get("VCT_BENCH_GRID", "160"))
    if not 8 <= segments <= 750:
        raise ValueError("VCT_BENCH_GRID must be between 8 and 750")
    bmesh.ops.create_grid(bm, x_segments=segments, y_segments=segments, size=10)
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
    # Run identical Blender API work with scalar and vectorized conversion.
    # Disable NumPy only inside this benchmark to measure the real fallback.
    numpy_module = vct._np
    try:
        vct._np = None
        scalar = measured(
            "HSV scalar reference",
            lambda: vct._apply_adjust_preview(bpy.context),
        )
    finally:
        vct._np = numpy_module

    optimized = measured(
        "HSV optimized refresh",
        lambda: vct._apply_adjust_preview(bpy.context),
    )
    if numpy_module is not None and optimized > 0:
        print(f"VCT BENCH HSV speedup: {scalar / optimized:.2f}x")
    else:
        print("VCT BENCH NumPy unavailable; scalar fallback used")

    vct._cancel_adjust_preview(bpy.context)

    print("VCT PHASE 2 BENCHMARK: COMPLETE (informational only)")
finally:
    vct.unregister()
