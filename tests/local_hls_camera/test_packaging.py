"""Keep HACS scoped to one branded domain and the shared App release."""

import json
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def test_hacs_packaging():
    root = ROOT
    hacs = json.loads((root / "hacs.json").read_text())
    assert hacs["name"] == "Local HLS Camera"
    assert hacs["homeassistant"] == "2026.10.1"
    assert hacs["content_in_root"] is False
    assert hacs["hide_default_branch"] is True
    domains = {
        p.name
        for p in (root / "custom_components").iterdir()
        if (p / "manifest.json").is_file()
    }
    assert domains == {"local_hls_camera"}
    manifest = json.loads(
        (root / "custom_components/local_hls_camera/manifest.json").read_text()
    )
    assert manifest["domain"] == "local_hls_camera"
    app = (root / "home-assistant/config.yaml").read_text()
    version = re.search(r'^version: "([0-9]{4}\.[0-9]{2}\.[0-9]+)"$', app, re.M)
    assert version is not None
    assert manifest["version"] == version[1]
    assert manifest["iot_class"] == "local_poll"
    assert manifest["requirements"] == []
    assert manifest["dependencies"] == ["camera", "http", "stream"]


@pytest.mark.parametrize("filename", ["icon.png", "logo.png"])
def test_integration_bundles_native_app_branding(filename):
    image = (ROOT / "custom_components/local_hls_camera/brand" / filename).read_bytes()
    assert image == (ROOT / "home-assistant" / filename).read_bytes()
    assert image[:8] == b"\x89PNG\r\n\x1a\n"
    assert image[12:16] == b"IHDR"
    width, height = struct.unpack(">II", image[16:24])
    assert width > 0 and height > 0
    if filename == "icon.png":
        assert width == height


def release_fixture(tmp_path):
    app = tmp_path / "home-assistant/config.yaml"
    manifest = tmp_path / "custom_components/local_hls_camera/manifest.json"
    app.parent.mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    app.write_text('name: go2rtc\nversion: "2026.10.31"\noptions: {}\n')
    manifest.write_text('{"domain": "local_hls_camera", "version": "2026.10.31"}\n')
    return app, manifest


def stamp(tmp_path, version):
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/release_version.py"),
            version,
            "--root",
            str(tmp_path),
        ],
        capture_output=True,
        check=False,
    )


def test_release_stamp_updates_both_and_preserves_settings(tmp_path):
    app, manifest = release_fixture(tmp_path)
    result = stamp(tmp_path, "2026.11.42")
    assert result.returncode == 0, result.stderr
    assert app.read_text() == 'name: go2rtc\nversion: "2026.11.42"\noptions: {}\n'
    assert json.loads(manifest.read_text()) == {
        "domain": "local_hls_camera",
        "version": "2026.11.42",
    }
    original = app.read_bytes(), manifest.read_bytes()
    assert stamp(tmp_path, "2026.11.42").returncode == 0
    assert (app.read_bytes(), manifest.read_bytes()) == original


@pytest.mark.parametrize(
    "version", ["2026.13.42", "2026.1.42", "2026.10.0", "v2026.10.42"]
)
def test_invalid_release_never_changes_files(tmp_path, version):
    app, manifest = release_fixture(tmp_path)
    original = app.read_bytes(), manifest.read_bytes()
    assert stamp(tmp_path, version).returncode != 0
    assert (app.read_bytes(), manifest.read_bytes()) == original


def test_invalid_manifest_never_stamps_app(tmp_path):
    app, manifest = release_fixture(tmp_path)
    manifest.write_text("invalid JSON")
    original = app.read_bytes(), manifest.read_bytes()
    assert stamp(tmp_path, "2026.11.42").returncode != 0
    assert (app.read_bytes(), manifest.read_bytes()) == original


@pytest.mark.parametrize("app_text", ["name: go2rtc\n", "version: a\nversion: b\n"])
def test_missing_or_duplicate_app_version_never_stamps_manifest(tmp_path, app_text):
    app, manifest = release_fixture(tmp_path)
    app.write_text(app_text)
    original = app.read_bytes(), manifest.read_bytes()
    assert stamp(tmp_path, "2026.11.42").returncode != 0
    assert (app.read_bytes(), manifest.read_bytes()) == original
