"""UI setup without copied credentials or user-supplied executable arguments."""

import asyncio
from urllib.parse import urlsplit

import probatio as vol
from homeassistant.components.camera import async_get_stream_source
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_SEGMENT_COUNT,
    CONF_SEGMENT_SECONDS,
    CONF_SOURCE_ENTITY,
    DEFAULT_SEGMENT_COUNT,
    DEFAULT_SEGMENT_SECONDS,
    DOMAIN,
)


def source_is_rtsp(source: str | None) -> bool:
    """Reject file, HTTP, exec and other protocols; never return the URL in errors."""
    if not source or any(ord(char) < 32 for char in source):
        return False
    try:
        parsed = urlsplit(source)
        return parsed.scheme in ("rtsp", "rtsps") and bool(parsed.hostname)
    except ValueError:
        return False


def options_schema(values: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_SEGMENT_SECONDS,
                default=values.get(CONF_SEGMENT_SECONDS, DEFAULT_SEGMENT_SECONDS),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
            vol.Required(
                CONF_SEGMENT_COUNT,
                default=values.get(CONF_SEGMENT_COUNT, DEFAULT_SEGMENT_COUNT),
            ): vol.All(vol.Coerce(int), vol.Range(min=3, max=10)),
        }
    )


class LocalHlsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create one independent HLS camera for an existing RTSP camera."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            entity_id = user_input[CONF_SOURCE_ENTITY]
            registered = er.async_get(self.hass).async_get(entity_id)
            if registered is not None and registered.platform == DOMAIN:
                errors[CONF_SOURCE_ENTITY] = "invalid_source"
            else:
                try:
                    async with asyncio.timeout(5):
                        source = await async_get_stream_source(self.hass, entity_id)
                    if not source_is_rtsp(source):
                        errors[CONF_SOURCE_ENTITY] = "invalid_source"
                except HomeAssistantError, TimeoutError:
                    errors[CONF_SOURCE_ENTITY] = "source_unavailable"
            if not errors:
                await self.async_set_unique_id(entity_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_SOURCE_ENTITY: entity_id},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Local HLS Camera"): str,
                    vol.Required(CONF_SOURCE_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="camera")
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return LocalHlsOptionsFlow()


class LocalHlsOptionsFlow(OptionsFlow):
    """Only packaging settings; encoding stays in the source app."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=options_schema(dict(self.config_entry.options))
        )
