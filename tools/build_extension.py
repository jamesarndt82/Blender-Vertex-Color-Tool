#!/usr/bin/env python3
"""Build the GPL-3.0-or-later Blender extension ZIP from one Python add-on.

The same ZIP supports local installation, GitHub Releases, and submission to
https://extensions.blender.org/submit/. The legacy single-file .py remains
available to existing users.

Usage:
    python tools/build_extension.py
    python tools/build_extension.py --verify dist/vertex_color_toolbox-2.5.1.zip
    python tools/build_extension.py --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
"""
import argparse
import ast
from pathlib import Path
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
    "schema_version", "id", "version", "name", "tagline", "maintainer",
    "type", "blender_version_min", "license",
)
SPDX = b"# SPDX-License-Identifier: GPL-3.0-or-later\n"


def info():
    """Validate manifest consistency and GPL declaration before building."""
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    for key in REQUIRED_MANIFEST:
        if key not in manifest:
            raise ValueError(f"Missing manifest field: {key}")
    if manifest["schema_version"] != "1.0.0":
        raise ValueError("Unsupported Blender manifest schema")
    if manifest["type"] != "add-on":
        raise ValueError("Extension type must be add-on")
    if manifest["id"] != "vertex_color_toolbox":
        raise ValueError("Unexpected extension identifier")
    if not 1 <= len(manifest["tagline"]) <= 64:
        raise ValueError("Manifest tagline must be between 1 and 64 characters")
    if manifest["tagline"].endswith((".", "!", "?")):
        raise ValueError("Manifest tagline must not end with punctuation")
    if manifest["license"] != ["SPDX:GPL-3.0-or-later"]:
        raise ValueError("Extension license must be GPL-3.0-or-later")
    if tuple(map(int, manifest["blender_version_min"].split("."))) < (5, 2, 0):
        raise ValueError("Blender version minimum is older than supported version")
    if manifest["version"].count(".") != 2:
        raise ValueError("Expected MAJOR.MINOR.PATCH version")

    source = SOURCE.read_bytes()
    if not source.startswith(SPDX):
        raise ValueError("Add-on source is missing the GPL-3.0-or-later SPDX header")
    tree = ast.parse(source.decode("utf-8"), filename=str(SOURCE))
    header = next(
        (n.value for n in tree.body
         if isinstance(n, ast.Assign)
         and any(isinstance(t, ast.Name) and t.id == "bl_info"
                 for t in n.targets)), None,
    )
    if header is None:
        raise ValueError("The add-on must include bl_info for legacy installs")
    metadata = ast.literal_eval(header)
    version = ".".join(str(n) for n in metadata["version"])
    if version != manifest["version"]:
        raise ValueError(f"Version mismatch: source {version}, manifest {manifest['version']}")
    if tuple(metadata["blender"]) > tuple(map(int, manifest["blender_version_min"].split("."))):
        raise ValueError("Manifest supports Blender versions below the add-on minimum")
    license_text = LICENSE.read_text(encoding="utf-8")
    if not license_text.startswith("GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007"):
        raise ValueError("LICENSE must contain the full GPL version 3")
    return manifest


def files():
    """The only three package files: no tests, build tools or duplicate code."""
    return {
        "__init__.py": SOURCE.read_bytes(),
        "blender_manifest.toml": MANIFEST.read_bytes(),
        "LICENSE": LICENSE.read_bytes(),
    }


def verify(path):
    info()
    if not path.is_file():
        raise FileNotFoundError(path)
    expected = files()
    with zipfile.ZipFile(path) as z:
        entries = z.namelist()
        if len(entries) != len(PACKAGE_CONTENTS) or set(entries) != set(PACKAGE_CONTENTS):
            raise ValueError(f"Unexpected extension package files: {entries}")
        if z.testzip() is not None:
            raise ValueError("Extension ZIP failed integrity validation")
        for name, content in expected.items():
            if z.read(name) != content:
                raise ValueError(f"Package file differs from source: {name}")
        packed_manifest = tomllib.loads(z.read("blender_manifest.toml").decode("utf-8"))
        if packed_manifest != info():
            raise ValueError("Packaged extension manifest is inconsistent")
    print(f"VALID GPL EXTENSION PACKAGE: {path}")


def build_python_zip(output):
    """Reproducible ZIP creation, usable in CI without Blender installed."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files().items():
            entry = zipfile.ZipInfo(filename=name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, content, compresslevel=9)


def build_with_blender(output, blender):
    """Use Blender's extension CLI for submission-grade validation and build."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vct-extension-") as directory:
        stage = Path(directory)
        for name, content in files().items():
            (stage / name).write_bytes(content)
        subprocess.run(
            [str(blender), "--command", "extension", "validate", str(stage)],
            check=True,
        )
        subprocess.run(
            [str(blender), "--command", "extension", "build",
             "--source-dir", str(stage), "--output-filepath", str(output.resolve())],
            check=True,
        )
    subprocess.run(
        [str(blender), "--command", "extension", "validate", str(output.resolve())],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--blender", type=Path, help="Use Blender to build and validate")
    parser.add_argument("--verify", type=Path, help="Verify a previously built ZIP")
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
