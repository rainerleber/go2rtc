"""A separate camera entity; existing cameras and automations remain untouched."""

import logging
from typing import cast

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.camera.prefs import get_dynamic_camera_stream_settings
from homeassistant.components.stream import Stream
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_SEGMENT_COUNT,
    CONF_SEGMENT_SECONDS,
    CONF_SOURCE_ENTITY,
    DEFAULT_SEGMENT_COUNT,
    DEFAULT_SEGMENT_SECONDS,
    DOMAIN,
)
from .stream import StreamAdapter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([LocalHlsCamera(entry)])


class LocalHlsCamera(Camera):
    """Supply our own HLS adapter only for this camera, not globally."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_brand = "Local HLS"
    _attr_model = "H.264/AAC MPEG-TS"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__()
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_name = entry.title
        self.adapter: StreamAdapter | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        settings = await get_dynamic_camera_stream_settings(self.hass, self.entity_id)
        self.adapter = StreamAdapter(
            self.hass,
            self.entry.entry_id,
            self.entry.data[CONF_SOURCE_ENTITY],
            self.entry.options.get(CONF_SEGMENT_SECONDS, DEFAULT_SEGMENT_SECONDS),
            self.entry.options.get(CONF_SEGMENT_COUNT, DEFAULT_SEGMENT_COUNT),
            settings,
        )
        self.adapter.entity_id = self.entity_id
        self.adapter.set_update_callback(self.async_write_ha_state)
        # The cast documents the internal duck-typed HA contract. No HA Stream
        # class, provider registry, worker or Alexa handler is replaced.
        self.stream = cast(Stream, self.adapter)
        self.hass.data[DOMAIN][self.entry.entry_id] = self.adapter

        async def shutdown(event) -> None:
            if self.adapter is not None:
                await self.adapter.stop()

        self.async_on_remove(
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown)
        )
        if settings.preload_stream and self.hass.state == CoreState.running:
            try:
                await self.adapter.start()
            except HomeAssistantError:
                _LOGGER.warning("Local HLS preload waiting for its source camera")

    async def async_create_stream(self) -> Stream | None:
        return cast(Stream | None, self.adapter)

    async def async_camera_image(self, width=None, height=None) -> bytes | None:
        if self.adapter is None:
            return None
        return await self.adapter.async_get_image(width=width, height=height)

    @callback
    def _remove_adapter(self) -> None:
        self.hass.data[DOMAIN].pop(self.entry.entry_id, None)

    async def async_will_remove_from_hass(self) -> None:
        self._remove_adapter()
        if self.adapter is not None:
            await self.adapter.stop()
        await super().async_will_remove_from_hass()
