"""Non-sensitive counters only; never export camera configuration or URLs."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    adapter = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if adapter is None:
        return {"running": False}
    return adapter.get_diagnostics()
