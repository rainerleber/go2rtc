"""Authenticated HA camera bridge for the app-owned local HLS backend."""

import asyncio
import logging

from homeassistant.components.camera import async_get_stream_source
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .backend import BackendClient, BackendError
from .config_flow import legacy_stream_name
from .const import (
    CONF_SEGMENT_COUNT,
    CONF_SEGMENT_SECONDS,
    CONF_SOURCE_ENTITY,
    CONF_STREAM_NAME,
    DEFAULT_SEGMENT_COUNT,
    DEFAULT_SEGMENT_SECONDS,
    DOMAIN,
)
from .http import HlsView

PLATFORMS = [Platform.CAMERA]
_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Preserve the entry/entity IDs; never delete its former source camera."""
    if entry.version > 2:
        return False
    if entry.version == 2:
        return True
    source = None
    registered = er.async_get(hass).async_get(entry.data.get(CONF_SOURCE_ENTITY, ""))
    if registered is not None and registered.platform == "generic":
        source_entry = hass.config_entries.async_get_entry(registered.config_entry_id)
        if source_entry is not None:
            # Read the config entry through HA, not .storage, and only in RAM.
            source = source_entry.options.get(
                "stream_source", source_entry.data.get("stream_source")
            )
    if source is None:
        try:
            async with asyncio.timeout(5):
                source = await async_get_stream_source(
                    hass, entry.data[CONF_SOURCE_ENTITY]
                )
        except HomeAssistantError, KeyError, TimeoutError:
            _LOGGER.error(
                "Migration requires the existing local RTSP source to be available"
            )
            return False
    name = legacy_stream_name(source)
    if name is None:
        _LOGGER.error(
            "Migration requires a local go2rtc app output; no credentials copied"
        )
        return False
    try:
        status = await BackendClient(hass, name).status()
    except BackendError:
        _LOGGER.error("Update the go2rtc app before migrating Local HLS Camera")
        return False
    if status["segment_seconds"] != entry.options.get(
        CONF_SEGMENT_SECONDS, DEFAULT_SEGMENT_SECONDS
    ) or status["segment_count"] != entry.options.get(
        CONF_SEGMENT_COUNT, DEFAULT_SEGMENT_COUNT
    ):
        _LOGGER.error(
            "Copy the existing HLS segment settings into the app before migration"
        )
        return False
    hass.config_entries.async_update_entry(
        entry,
        data={CONF_STREAM_NAME: name},
        options={},
        version=2,
        unique_id=f"go2rtc:{name}",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register our own HTTP route once, then set up the camera platform."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
        hass.http.register_view(HlsView(hass))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Revoke only this bridge's sessions; the shared app backend stays alive."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
