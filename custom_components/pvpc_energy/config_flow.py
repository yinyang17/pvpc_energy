from homeassistant import config_entries
from homeassistant.helpers.selector import selector
from typing import Any, Dict, Optional
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
import logging
from .const import DOMAIN
from .ufd import UFD

_LOGGER = logging.getLogger(__name__)

AUTH_SCHEMA = {
    vol.Required('ufd_login'): cv.string,
    vol.Required('ufd_password'): cv.string
}
CUPS_SCHEMA = {
    vol.Required('cups'): cv.string,
    vol.Required('bills_number', default='5'): cv.positive_int
}

class PvpcEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    data: Optional[Dict[str, Any]]

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        if user_input is not None:
            _LOGGER.debug(f"pvpc_energy: async_step_user, user_input={user_input}")

            UFD.User = user_input['ufd_login']
            UFD.Password = user_input['ufd_password']
            self.data = user_input
            self.data['cups_list'] = await UFD.supplypoints()
            return await self.async_step_cups()
        
        return self.async_show_form(step_id="user", data_schema=vol.Schema(AUTH_SCHEMA), errors=None)
    
    async def async_step_cups(self, user_input: Optional[Dict[str, Any]] = None):
        _LOGGER.debug(f"cups: {list(self.data['cups_list'].keys())}")
        CUPS_SCHEMA['cups'] = selector({
            "select": {
                "options": list(self.data['cups_list'].keys()),
            }
        })
        if user_input is not None:
            _LOGGER.debug(f"pvpc_energy: async_step_cups, user_input={user_input}")
            supply_point = self.data['cups_list'][user_input['cups']]
            self.data['cups'] = supply_point['cups']
            self.data['power_high'] = supply_point['power_high']
            self.data['power_low'] = supply_point['power_low']
            self.data['zip_code'] = supply_point['zip_code']
            self.data['bills_number'] = user_input['bills_number']

            return self.async_create_entry(title=self.data['cups'], data=self.data)
        
        return self.async_show_form(step_id="cups", data_schema=vol.Schema(CUPS_SCHEMA), errors=None)
