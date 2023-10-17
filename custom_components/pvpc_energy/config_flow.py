from homeassistant import config_entries
from typing import Any, Dict, Optional
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
import logging
from .const import DOMAIN
from .ufd import UFD

_LOGGER = logging.getLogger(__name__)

AUTH_SCHEMA = vol.Schema({
    vol.Required('ufd_login'): cv.string,
    vol.Required('ufd_password'): cv.string
})
CUPS_SCHEMA = vol.Schema({
    vol.Required('bills_number', default='5'): cv.positive_int
})

class PvpcEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    data: Optional[Dict[str, Any]]

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        if user_input is not None:
            _LOGGER.debug(f"pvpc_energy: async_step_user, user_input={user_input}")

            UFD.User = user_input['ufd_login']
            UFD.Password = user_input['ufd_password']
            await UFD.supplypoints()
            self.data = user_input
            self.data['cups'] = UFD.cups
            self.data['power_high'] = UFD.power_high
            self.data['power_low'] = UFD.power_low
            self.data['zip_code'] = UFD.zip_code

            return await self.async_step_cups()
        
        return self.async_show_form(step_id="user", data_schema=AUTH_SCHEMA, errors=None)
    
    async def async_step_cups(self, user_input: Optional[Dict[str, Any]] = None):
        if user_input is not None:
            _LOGGER.debug(f"pvpc_energy: async_step_cups, user_input={user_input}")
            self.data['bills_number'] = user_input['bills_number']

            return self.async_create_entry(title=self.data['cups'], data=self.data)
        
        return self.async_show_form(step_id="cups", data_schema=CUPS_SCHEMA, errors=None)
