"""Optional legacy HLS camera; does not modify HA Core or the go2rtc app."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .http import HlsView

PLATFORMS = [Platform.CAMERA]


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
    """The entity stops its worker and removes its sessions on unload."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
