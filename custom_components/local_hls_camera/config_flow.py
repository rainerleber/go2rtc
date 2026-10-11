"""UI setup points to a named app output, never a camera URL or credential."""

from urllib.parse import urlsplit

import probatio as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback

from .backend import STREAM_NAME, BackendClient, BackendError
from .const import CONF_STREAM_NAME, DEFAULT_STREAM_NAME, DOMAIN


def legacy_stream_name(source: str | None) -> str | None:
    """Migrate only the app's exact loopback RTSP output, without copied secrets."""
    if (
        not isinstance(source, str)
        or not source
        or any(ord(char) < 32 for char in source)
    ):
        return None
    try:
        parsed = urlsplit(source)
        name = parsed.path.removeprefix("/")
        if (
            parsed.scheme == "rtsp"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == 8554
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and STREAM_NAME.fullmatch(name)
        ):
            return name
    except ValueError:
        pass
    return None


def stream_schema(values: dict, *, name: bool = False) -> vol.Schema:
    fields = {
        vol.Required(
            CONF_STREAM_NAME, default=values.get(CONF_STREAM_NAME, DEFAULT_STREAM_NAME)
        ): vol.All(str, vol.Match(r"^[A-Za-z0-9_-]{1,64}$"))
    }
    if name:
        fields[vol.Required(CONF_NAME, default="Local HLS Camera")] = str
    return vol.Schema(fields)


async def validate_stream(hass, stream_name: str) -> str | None:
    try:
        await BackendClient(hass, stream_name).status()
    except BackendError:
        return "app_unavailable"
    return None


class LocalHlsConfigFlow(ConfigFlow, domain=DOMAIN):
    """One HA camera bridge per named app output."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = await validate_stream(self.hass, user_input[CONF_STREAM_NAME])
            if error:
                errors[CONF_STREAM_NAME] = error
            else:
                await self.async_set_unique_id(f"go2rtc:{user_input[CONF_STREAM_NAME]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_STREAM_NAME: user_input[CONF_STREAM_NAME]},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=stream_schema(user_input or {}, name=True),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return LocalHlsOptionsFlow()


class LocalHlsOptionsFlow(OptionsFlow):
    """Packaging and encoding settings belong exclusively to the app."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = await validate_stream(self.hass, user_input[CONF_STREAM_NAME])
            if error:
                errors[CONF_STREAM_NAME] = error
            else:
                other = next(
                    (
                        entry
                        for entry in self.hass.config_entries.async_entries(DOMAIN)
                        if entry.entry_id != self.config_entry.entry_id
                        and entry.options.get(
                            CONF_STREAM_NAME, entry.data.get(CONF_STREAM_NAME)
                        )
                        == user_input[CONF_STREAM_NAME]
                    ),
                    None,
                )
                if other:
                    errors[CONF_STREAM_NAME] = "already_configured"
                else:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={CONF_STREAM_NAME: user_input[CONF_STREAM_NAME]},
                        unique_id=f"go2rtc:{user_input[CONF_STREAM_NAME]}",
                    )
                    return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=stream_schema(
                user_input
                or dict(self.config_entry.data) | dict(self.config_entry.options)
            ),
        )
