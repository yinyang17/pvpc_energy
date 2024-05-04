"""The PVPC Energy integration."""
from .const import DOMAIN, USER_FILES_PATH
from homeassistant.helpers.event import async_track_time_change
from homeassistant.const import Platform
from .coordinator import PvpcCoordinator
from os.path import exists
from os import makedirs
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry) -> bool:
    _LOGGER.debug(f"pvpc_energy: async_setup_entry, entry_id={entry.entry_id}, hass_data={dict(entry.data)}")
    hass_data = dict(entry.data)
    PvpcCoordinator.set_config(hass_data)

    unsub_options_update_listener = entry.add_update_listener(options_update_listener)
    hass_data["unsub_options_update_listener"] = unsub_options_update_listener
    hass.data[DOMAIN][entry.entry_id] = hass_data

    await hass.async_add_executor_job(setup_hass_services, hass)
    await hass.async_create_task(PvpcCoordinator.import_energy_data(hass))
    return True

def setup_hass_services(hass) -> None:
    async def async_handle_import_energy_data(call):
        hass.async_create_task(PvpcCoordinator.import_energy_data(hass))
    async def async_handle_force_import_energy_data(call):
        hass.async_create_task(PvpcCoordinator.import_energy_data(hass, True))
    async def async_handle_reprocess_energy_data(call):
        hass.async_create_task(PvpcCoordinator.reprocess_energy_data(hass))

    hass.services.register(DOMAIN, "import_energy_data", async_handle_import_energy_data)
    hass.services.register(DOMAIN, "force_import_energy_data", async_handle_force_import_energy_data)
    hass.services.register(DOMAIN, "reprocess_energy_data", async_handle_reprocess_energy_data)
    
    async_track_time_change(hass, async_handle_import_energy_data, hour=7, minute=5, second=0)

async def options_update_listener(hass, config_entry):
    _LOGGER.debug(f"pvpc_energy: options_update_listener, config_entry={config_entry}")
    await hass.config_entries.async_reload(config_entry.entry_id)

async def async_unload_entry(hass, entry) -> bool:
    _LOGGER.debug(f"pvpc_energy: async_unload_entry, entry_id={entry.entry_id}, hass_data={dict(entry.data)}")
    entry_data = hass.data[DOMAIN].pop(entry.entry_id)
    entry_data["unsub_options_update_listener"]()
    return True

def setup(hass, config):
    _LOGGER.debug(f"pvpc_energy: setup")
    if not exists(USER_FILES_PATH):
        makedirs(USER_FILES_PATH)
    hass.data.setdefault(DOMAIN, {})

    return True
