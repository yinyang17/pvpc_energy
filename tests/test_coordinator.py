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


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_coordinator()
        self.coordinator = self.module.PvpcCoordinator
        self.hass = FakeHass()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    async def read_csv(self, body):
        path = Path(self.temp.name) / 'energy.csv'
        path.write_text(body)
        return await self.coordinator.load_energy_data(self.hass, str(path))

    async def test_truncated_blank_and_invalid_rows_preserve_valid_rows(self):
        consumption, prices = await self.read_csv(
            'date,timestamp,consumption,price,reading_type\n'
            'x,1700000000,1.2,0.3,R\n\n18/06/2026 1\n'
            'x,invalid,5,0.4,R\nx,1700003600,invalid,0.4,R\n'
            'x,1700007200,2.5,0.4,R')
        self.assertEqual(set(consumption), {1700000000, 1700007200})
        self.assertEqual(consumption[1700007200]['value'], 2.5)
        self.assertEqual(prices, {1700000000: 0.3, 1700007200: 0.4})

    async def test_legacy_csv_without_final_newline(self):
        consumption, prices = await self.read_csv(
            'date,timestamp,consumption,price\nx,1700000000,1.2,0.35')
        self.assertEqual(consumption[1700000000]['reading_type'], '')
        self.assertEqual(prices[1700000000], 0.35)

    async def test_empty_consumption_and_price_markers(self):
        consumption, prices = await self.read_csv(
            'date,timestamp,consumption,price,reading_type\n'
            'x,1700000000,-,0.3,\nx,1700003600,0,-,R\n')
        self.assertEqual(consumption, {1700003600: {'value': 0.0, 'reading_type': 'R'}})
        self.assertEqual(prices, {1700000000: 0.3})

    def prepare_import(self):
        coordinator = self.coordinator
        day = datetime.date.today() - datetime.timedelta(days=2)
        timestamp = int(datetime.datetime.combine(day, datetime.time()).timestamp())
        coordinator.contract_start_date = day
        coordinator.load_energy_data = AsyncMock(return_value=(
            {timestamp: {'value': 1.2, 'reading_type': 'R'}}, {timestamp: 0.3}))
        coordinator.get_billing_periods = AsyncMock(return_value=[])
        coordinator.load_billing_periods = AsyncMock(return_value=[])
        coordinator.get_data = AsyncMock()
        coordinator.save_energy_data = AsyncMock()
        coordinator.calculate_bills = AsyncMock()
        loop = asyncio.get_running_loop()
        def register(hass, metadata, statistics):
            self.assertIs(asyncio.get_running_loop(), loop)
            self.assertTrue(statistics)
        self.module.async_add_external_statistics = Mock(side_effect=register)
        return timestamp

    async def test_missing_statistics_rebuilt_without_new_downloads(self):
        self.prepare_import()
        self.module.get_last_statistics.return_value = {}
        await self.coordinator.import_energy_data(self.hass)
        self.assertEqual(self.module.async_add_external_statistics.call_count, 2)
        self.assertEqual([call.args[1]['statistic_id'] for call in
                          self.module.async_add_external_statistics.call_args_list],
                         ['pvpc_energy:consumption', 'pvpc_energy:cost'])

    async def test_missing_cost_statistics_triggers_rebuild(self):
        timestamp = self.prepare_import()
        self.module.get_last_statistics.side_effect = [
            {'pvpc_energy:consumption': [{'start': timestamp}]}, {}]
        await self.coordinator.import_energy_data(self.hass)
        self.assertEqual(self.module.async_add_external_statistics.call_count, 2)

    async def test_reprocess_registers_both_statistics_on_event_loop(self):
        self.prepare_import()
        await self.coordinator.reprocess_energy_data(self.hass)
        self.assertEqual(self.module.async_add_external_statistics.call_count, 2)

    async def test_no_data_does_not_create_statistics(self):
        self.prepare_import()
        self.coordinator.load_energy_data.return_value = ({}, {})
        await self.coordinator.import_energy_data(self.hass)
        self.module.async_add_external_statistics.assert_not_called()


if __name__ == '__main__':
    unittest.main()
