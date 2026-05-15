import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_FAVORITE_TEAM,
    CONF_IDLE_POLL_INTERVAL,
    CONF_LIVE_POLL_INTERVAL,
    CONF_PRE_MATCH_BUFFER,
    CONF_TITLE,
    DEFAULT_FAVORITE_TEAM,
    DEFAULT_IDLE_POLL_INTERVAL,
    DEFAULT_LIVE_POLL_INTERVAL,
    DEFAULT_PRE_MATCH_BUFFER,
    DEFAULT_TITLE,
    DOMAIN,
)


def _build_schema(defaults):
    return vol.Schema(
        {
            vol.Required(CONF_TITLE, default=defaults.get(CONF_TITLE, DEFAULT_TITLE)): selector.TextSelector(),
            vol.Required(
                CONF_FAVORITE_TEAM,
                default=defaults.get(CONF_FAVORITE_TEAM, DEFAULT_FAVORITE_TEAM),
            ): selector.TextSelector(),
            vol.Required(
                CONF_LIVE_POLL_INTERVAL,
                default=defaults.get(CONF_LIVE_POLL_INTERVAL, DEFAULT_LIVE_POLL_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=15, max=600, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_PRE_MATCH_BUFFER,
                default=defaults.get(CONF_PRE_MATCH_BUFFER, DEFAULT_PRE_MATCH_BUFFER),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=3600, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_IDLE_POLL_INTERVAL,
                default=defaults.get(CONF_IDLE_POLL_INTERVAL, DEFAULT_IDLE_POLL_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=21600, mode=selector.NumberSelectorMode.BOX)
            ),
        }
    )


class MSHokejConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_TITLE], data=user_input)

        return self.async_show_form(step_id="user", data_schema=_build_schema({}))

    @staticmethod
    def async_get_options_flow(config_entry):
        return MSHokejOptionsFlow(config_entry)


class MSHokejOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        defaults = dict(self.config_entry.data)
        defaults.update(self.config_entry.options)
        return self.async_show_form(step_id="init", data_schema=_build_schema(defaults))
