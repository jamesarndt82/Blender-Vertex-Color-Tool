"""Numerical regression tests for the HSV buffer, runnable without Blender."""
from array import array
import ast
import colorsys
from pathlib import Path
import random
import unittest

try:
    import numpy as np
except ImportError:
    np = None


CODE = (Path(__file__).resolve().parents[1] /
        "vertex_color_toolbox_blender_5_2.py").read_text(encoding="utf-8")
TREE = ast.parse(CODE)
FUNCTIONS = {"adjust_rgb", "_adjust_colors_buffer"}
DECLARATIONS = [node for node in TREE.body
                if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
assert len(DECLARATIONS) == len(FUNCTIONS), "Missing an HSV helper"
ns = {"array": array, "colorsys": colorsys, "_np": np}
exec(compile(ast.Module(body=DECLARATIONS, type_ignores=[]),
             "<vertex-color-toolbox-hsv>", "exec"), ns)
adjust_rgb = ns["adjust_rgb"]
adjust_buffer = ns["_adjust_colors_buffer"]


def samples():
    rng = random.Random(20261029)
    # Exercise tie breaks, exact grayscale, zero value, vivid primaries and
    # colors at the byte-attribute resolution as well as arbitrary floats.
    colors = [
        (0, 0, 0, 0), (1, 1, 1, 1), (.5, .5, .5, .125),
        (1, 0, 0, 1), (0, 1, 0, .7), (0, 0, 1, .25),
        (1, 1, 0, 1), (0, 1, 1, 0), (1, 0, 1, 1),
        (.3, .3, .8, .6), (.9, .1, .1, .4),
        (1 / 255, 254 / 255, 128 / 255, 0),
    ]
    colors.extend((rng.random(), rng.random(), rng.random(), rng.random())
                  for _ in range(2048))
    return colors


class HSVBufferTests(unittest.TestCase):
    def test_scalar_and_vector_agree_with_colorsys_and_keep_alpha(self):
        palette = samples()
        for hue, saturation, value in (
            (0.0, 1.0, 1.0),
            (-0.5, 2.0, 2.0),
            (0.5, 0.0, 0.0),
            (0.173, 1.6, 0.78),
            (-0.249, 0.25, 1.75),
        ):
            original = array("f", (channel for c in palette for channel in c))
            baseline = array("f", original)
            # A float32 buffer is what Blender's foreach_get supplies.
            expected = []
            for i in range(0, len(original), 4):
                rgb = adjust_rgb(original[i:i + 3], hue, saturation, value)
                expected.extend((*rgb, original[i + 3]))
            ns["_np"] = None
            self.assertIs(adjust_buffer(baseline, hue, saturation, value), baseline)

            for i, expected_value in enumerate(expected):
                self.assertAlmostEqual(
                    baseline[i], expected_value, delta=2e-6,
                    msg=f"scalar mismatch at {i}, settings {(hue, saturation, value)}",
                )
                if i % 4 == 3:
                    self.assertEqual(baseline[i], original[i])

            if np is not None:
                ns["_np"] = np
                optimized = array("f", original)
                self.assertIs(adjust_buffer(optimized, hue, saturation, value), optimized)
                for i, expected_value in enumerate(expected):
                    self.assertAlmostEqual(
                        optimized[i], expected_value, delta=2e-6,
                        msg=f"vector mismatch at {i}, settings {(hue, saturation, value)}",
                    )
                    if i % 4 == 3:
                        self.assertEqual(optimized[i], original[i])

    def test_small_buffers_and_identity(self):
        ns["_np"] = np
        rgba = array("f", [0.2, 0.4, 0.6, 0.8] * 3)
        unchanged = array("f", rgba)
        self.assertIs(adjust_buffer(rgba, 0.0, 1.0, 1.0), rgba)
        self.assertEqual(rgba, unchanged)
        adjust_buffer(rgba, .25, 1.0, 1.0)
        self.assertEqual(rgba[3], unchanged[3])
        self.assertNotEqual(rgba[:3], unchanged[:3])


if __name__ == "__main__":
    unittest.main()
