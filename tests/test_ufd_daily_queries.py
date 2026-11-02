"""Offline coordinator regressions; run with python -m unittest discover -s tests -v.

Load the real coordinator with small HA/provider boundary doubles, so these tests
need neither a running Home Assistant installation nor UFD credentials.
"""
import asyncio
import datetime
import importlib.util
import logging
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


def load_coordinator():
    source = Path(__file__).resolve().parents[1] / 'custom_components' / 'pvpc_energy' / 'coordinator.py'
    modules = {}

    def module(name, **attributes):
        value = ModuleType(name)
        value.__dict__.update(attributes)
        modules[name] = value
        return value

    package = '_pvpc_coordinator_test'
    module(package, __path__=[])
    module(package + '.const', DOMAIN='pvpc_energy', CURRENT_BILL_STATE='pvpc_energy.current_bill',
           CONSUMPTION_STATISTIC_ID='pvpc_energy:consumption', CONSUMPTION_STATISTIC_NAME='PVPC: Consumo',
           COST_STATISTIC_ID='pvpc_energy:cost', COST_STATISTIC_NAME='PVPC: Coste',
           USER_FILES_PATH='unused', ENERGY_FILE='unused', BILLING_PERIODS_FILE='unused')
    module(package + '.ufd', UFD=SimpleNamespace(consumptions=Mock()))
    module(package + '.ree', REE=SimpleNamespace(pvpc=Mock()))
    module(package + '.cnmc', CNMC=SimpleNamespace())
    for name in ['homeassistant', 'homeassistant.components', 'homeassistant.util']:
        module(name, __path__=[])
    module('homeassistant.components.recorder', get_instance=lambda hass: hass)
    module('homeassistant.components.recorder.models', StatisticData=dict, StatisticMetaData=dict,
           StatisticMeanType=SimpleNamespace(NONE=0))
    module('homeassistant.components.recorder.statistics', async_add_external_statistics=Mock(),
           get_last_statistics=Mock(), statistics_during_period=Mock())
    module('homeassistant.util.unit_conversion', EnergyConverter=SimpleNamespace(UNIT_CLASS='energy'))
    module('homeassistant.const', UnitOfEnergy=SimpleNamespace(KILO_WATT_HOUR='kWh'), CURRENCY_EURO='€')
    spec = importlib.util.spec_from_file_location(package + '.coordinator', source)
    loaded = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(loaded)
    return loaded


class FakeHass:
    def __init__(self):
        self.states = SimpleNamespace(get=lambda _: True)

    async def async_add_executor_job(self, function, *args):
        # Exercise the executor boundary with a real worker thread.
        return await asyncio.to_thread(function, *args)


class DailyQueryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_coordinator()
        self.coordinator = self.module.PvpcCoordinator
        self.hass = FakeHass()

    async def test_single_day_requests_preserve_distinct_readings(self):
        calls = []
        async def fetch(start, end):
            self.assertEqual(start, end)
            calls.append(start)
            timestamp = int(datetime.datetime.combine(start, datetime.time()).timestamp())
            return {timestamp: {'value': float(start.day), 'reading_type': 'R'}}
        data = {}
        start, end = datetime.date(2026, 10, 27), datetime.date(2026, 10, 31)
        await self.coordinator.get_data(fetch, start, end, data, 1)
        self.assertEqual(len(calls), 5)
        self.assertEqual({entry['value'] for entry in data.values()}, {27., 28., 29., 30., 31.})
        calls.clear()
        await self.coordinator.get_data(fetch, start, end, data, 1)
        self.assertEqual(calls, [])
        await self.coordinator.get_data(fetch, start, end, data, 1, True)
        self.assertEqual(len(calls), 5)

    async def test_provider_failure_stops_remaining_requests(self):
        fetch = AsyncMock(return_value=None)
        await self.coordinator.get_data(fetch, datetime.date(2026, 10, 1), datetime.date(2026, 10, 3), {}, 1, True)
        fetch.assert_awaited_once_with(datetime.date(2026, 10, 3), datetime.date(2026, 10, 3))

    async def test_initial_import_uses_daily_ufd_requests(self):
        c = self.coordinator
        c.contract_start_date = datetime.date.today() - datetime.timedelta(days=3)
        c.load_energy_data = AsyncMock(return_value=({}, {}))
        c.get_billing_periods = AsyncMock(return_value=[])
        c.get_data = AsyncMock()
        c.calculate_bills = AsyncMock()
        await c.import_energy_data(self.hass)
        call = c.get_data.await_args_list[0]
        self.assertIs(call.args[0], self.module.UFD.consumptions)
        self.assertEqual(call.args[4], 1)
        self.assertEqual(c.get_data.await_args_list[1].args[4], 28)

    async def test_incremental_import_uses_daily_ufd_requests(self):
        c = self.coordinator
        day = datetime.date.today() - datetime.timedelta(days=3)
        timestamp = int(datetime.datetime.combine(day, datetime.time()).timestamp())
        c.contract_start_date = day
        c.load_energy_data = AsyncMock(return_value=({timestamp: {'value': 1., 'reading_type': 'R'}}, {timestamp: .2}))
        c.get_billing_periods = AsyncMock(return_value=[])
        c.get_data = AsyncMock()
        await c.import_energy_data(self.hass)
        call = c.get_data.await_args_list[0]
        self.assertIs(call.args[0], self.module.UFD.consumptions)
        self.assertEqual(call.args[4], 1)

if __name__ == '__main__':
    unittest.main()
