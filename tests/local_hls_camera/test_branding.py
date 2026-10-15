"""The native HA brand endpoint serves bundled images without a CDN."""

from collections import deque
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.components.brands import BrandsIntegrationView
from homeassistant.loader import async_get_custom_components
from homeassistant.loader import async_setup as setup_loader


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename", ["icon.png", "logo.png", "dark_icon.png", "icon@2x.png"]
)
async def test_native_brand_endpoint(hass, aiohttp_client, filename):
    setup_loader(hass)
    integrations = await async_get_custom_components(hass)
    assert integrations["local_hls_camera"].has_branding
    hass.data["brands"] = deque(["synthetic-brand-token"], maxlen=2)
    app = hass.data["extension_test_app"]
    view = BrandsIntegrationView(hass)
    view.register(hass, app, app.router)
    client = await aiohttp_client(app)
    path = f"/api/brands/integration/local_hls_camera/{filename}"
    original = (Path(__file__).parents[2] / "home-assistant/icon.png").read_bytes()
    with patch.object(view, "_serve_from_cache_or_cdn") as cdn:
        assert (await client.get(path)).status == 403
        response = await client.get(path + "?token=synthetic-brand-token")
        assert response.status == 200
        assert response.content_type == "image/png"
        assert await response.read() == original
        cdn.assert_not_called()
