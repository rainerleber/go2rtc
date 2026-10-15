"""Stamp the App and HACS integration with one validated CalVer release."""

import argparse
import json
import re
from pathlib import Path


def set_release_version(root: Path, version: str) -> None:
    """Validate both files before changing either; never touch runtime settings."""
    if not re.fullmatch(r"[0-9]{4}\.(?:0[1-9]|1[0-2])\.[1-9][0-9]*", version):
        raise ValueError("Expected YYYY.MM.BUILD with a positive build number")
    app_path = root / "home-assistant/config.yaml"
    manifest_path = root / "custom_components/local_hls_camera/manifest.json"
    app = app_path.read_text()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("domain") != "local_hls_camera":
        raise ValueError("Unexpected integration domain")
    app, count = re.subn(r"^version: .*?$", f'version: "{version}"', app, flags=re.M)
    if count != 1:
        raise ValueError("Expected exactly one top-level App version")
    manifest["version"] = version
    app_path.write_text(app)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    set_release_version(args.root, args.version)
