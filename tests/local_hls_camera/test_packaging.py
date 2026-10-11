"""Keep HACS installation scoped to one complete, independently versioned domain."""

import json
from pathlib import Path


def test_hacs_packaging():
    root = Path(__file__).parents[2]
    hacs = json.loads((root / "hacs.json").read_text())
    assert hacs["name"] == "Local HLS Camera"
    assert hacs["homeassistant"] == "2026.10.1"
    assert hacs["content_in_root"] is False
    assert hacs["hide_default_branch"] is False
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
    assert manifest["version"] == "2026.10.3"
    assert manifest["iot_class"] == "local_poll"
    assert manifest["requirements"] == []
    assert manifest["dependencies"] == ["camera", "http", "stream"]
