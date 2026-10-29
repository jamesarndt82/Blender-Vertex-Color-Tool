#!/usr/bin/env python3
"""Build a Blender 5.2+ installable extension ZIP from the legacy single-file add-on.

Maintains exactly one add-on implementation in the repository. The same Python
source becomes __init__.py inside the extension ZIP, while the source .py
continues to support legacy installs.

Usage:
    python tools/build_extension.py
    python tools/build_extension.py --verify dist/vertex_color_toolbox-2.5.1.zip
    python tools/build_extension.py --blender "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe"
"""
import argparse
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vertex_color_toolbox_blender_5_2.py"
MANIFEST = ROOT / "blender_manifest.toml"
LICENSE = ROOT / "LICENSE"
PACKAGE_CONTENTS = ("__init__.py", "blender_manifest.toml", "LICENSE")
REQUIRED_MANIFEST = (
    "schema_version", "id", "version", "name", "tagline",
    "maintainer", "type", "blender_version_min", "license",
)


def info():
    """Ensure add-on and manifest versions cannot silently drift."""
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    for key in REQUIRED_MANIFEST:
        if key not in manifest:
            raise ValueError(f"Missing manifest field: {key}")
    if manifest["schema_version"] != "1.0.0":
        raise ValueError("Unsupported manifest schema")
    if manifest["type"] != "add-on":
        raise ValueError("Extension type must be add-on")
    if manifest["id"] != "vertex_color_toolbox":
        raise ValueError("Unexpected extension identifier")
    if not 1 <= len(manifest["tagline"]) <= 64:
        raise ValueError("Manifest tagline must have 1-64 characters")
    if manifest["tagline"].endswith((".", "!", "?")):
        raise ValueError("Manifest tagline cannot end with punctuation")
    if manifest["license"] != ["SPDX:MIT"]:
        raise ValueError("Manifest license must match the repository MIT license")
    if tuple(map(int, manifest["blender_version_min"].split("."))) < (5, 2, 0):
        raise ValueError("Blender version minimum is too old")

    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    header = next((n.value for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "bl_info"
                           for t in n.targets)), None)
    if header is None:
        raise ValueError("The source has no bl_info")
    metadata = ast.literal_eval(header)
    version = ".".join(str(n) for n in metadata["version"])
    if version != manifest["version"]:
        raise ValueError(f"Version mismatch: source {version} vs manifest {manifest['version']}")
    if tuple(metadata["blender"]) > tuple(map(int, manifest["blender_version_min"].split("."))):
        raise ValueError("Manifest allows Blender versions below the add-on minimum")
    if not LICENSE.read_text(encoding="utf-8").startswith("MIT License"):
        raise ValueError("Missing MIT license file")
    if not manifest["version"].count(".") == 2:
        raise ValueError("Expected semantic version MAJOR.MINOR.PATCH")
    return manifest


def files():
    """Read the exact files included in the installable ZIP."""
    return {
        "__init__.py": SOURCE.read_bytes(),
        "blender_manifest.toml": MANIFEST.read_bytes(),
        "LICENSE": LICENSE.read_bytes(),
    }


def verify(path):
    manifest = info()
    if not path.is_file():
        raise FileNotFoundError(path)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if set(names) != set(PACKAGE_CONTENTS) or len(names) != len(PACKAGE_CONTENTS):
            raise ValueError(f"Unexpected extension ZIP layout: {names}")
        if z.testzip() is not None:
            raise ValueError("Extension ZIP has corrupted contents")
        expected = files()
        for name in PACKAGE_CONTENTS:
            if z.read(name) != expected[name]:
                raise ValueError(f"Unexpected contents in {name}")
        packed = tomllib.loads(z.read("blender_manifest.toml").decode("utf-8"))
        if packed != manifest:
            raise ValueError("Packaged manifest differs from checked-out manifest")
    print(f"VALID EXTENSION PACKAGE: {path}")


def build_python_zip(output):
    """Create reproducible ZIPs without requiring Blender in CI."""
    output.parent.mkdir(parents=True, exist_ok=True)
    package = files()
    with zipfile.ZipFile(output, "w") as z:
        for name in PACKAGE_CONTENTS:
            entry = zipfile.ZipInfo(filename=name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            z.writestr(entry, package[name], compresslevel=9)


def build_with_blender(output, blender):
    """Build and validate using Blender's official extension commands."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vct-extension-") as directory:
        stage = Path(directory)
        for name, content in files().items():
            (stage / name).write_bytes(content)
        subprocess.run([str(blender), "--command", "extension", "validate",
                        str(stage)], check=True)
        subprocess.run([str(blender), "--command", "extension", "build",
                        "--source-dir", str(stage),
                        "--output-filepath", str(output.resolve())], check=True)
    subprocess.run([str(blender), "--command", "extension", "validate",
                    str(output.resolve())], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--blender", type=Path, help="Use official Blender build and validation")
    parser.add_argument("--verify", type=Path, help="Check a previously built ZIP")
    args = parser.parse_args()

    manifest = info()
    if args.verify:
        verify(args.verify)
        return

    output = args.output_dir / f"{manifest['id']}-{manifest['version']}.zip"
    if args.blender:
        if not args.blender.is_file():
            parser.error(f"Blender executable not found: {args.blender}")
        build_with_blender(output, args.blender)
    else:
        build_python_zip(output)

    verify(output)
    print(f"BUILD SUCCESS: {output}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"BUILD FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
