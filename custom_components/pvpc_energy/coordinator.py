from .const import DOMAIN, CURRENT_BILL_STATE, CONSUMPTION_STATISTIC_ID, CONSUMPTION_STATISTIC_NAME, COST_STATISTIC_ID, COST_STATISTIC_NAME, USER_FILES_PATH, ENERGY_FILE, BILLING_PERIODS_FILE
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (async_add_external_statistics, get_last_statistics, statistics_during_period, )
from .ufd import UFD
from .ree import REE
from .cnmc import CNMC
import datetime
import time
from os.path import exists
import logging

_LOGGER = logging.getLogger(__name__)


class PvpcCoordinator:
    ufd_login = None
    ufd_password = None
    cups = None
    power_high = None
    power_low = None
    zip_code = None
    bills_number = None

    def set_config(config):
        _LOGGER.debug(f"START - set_config(config={config})")
        PvpcCoordinator.ufd_login = config['ufd_login']
        PvpcCoordinator.ufd_password = config['ufd_password']
        PvpcCoordinator.cups = config['cups']
        PvpcCoordinator.power_high = config['power_high']
        PvpcCoordinator.power_low = config['power_low']
        PvpcCoordinator.zip_code = config['zip_code']
        PvpcCoordinator.bills_number = config['bills_number']

        UFD.User = config['ufd_login']
        UFD.Password = config['ufd_password']
        UFD.cups = config['cups']        
        _LOGGER.debug(f"END - set_config")

    async def test(hass):
        start_date = datetime.date.today() - datetime.timedelta(days=12)
        end_date = datetime.date.today() - datetime.timedelta(days=2)
        data = await REE.pvpc(start_date, end_date, hass)
        _LOGGER.debug(f"test: {data}")

    async def reprocess_statistics(hass):
        _LOGGER.debug(f"START - reprocess_statistics()")
        total_consumptions, total_prices = PvpcCoordinator.load_energy_data(ENERGY_FILE)

        _LOGGER.info(f"len(total_consumptions)={len(total_consumptions)}")
        if len(total_consumptions) > 0:
            consumption_statistics, cost_statistics = PvpcCoordinator.create_statistics(total_consumptions, total_prices, 0, 0)
    
            consumption_metadata = StatisticMetaData(
                name=CONSUMPTION_STATISTIC_NAME,
                has_mean=False,
                has_sum=True,
                source=DOMAIN,
                statistic_id=CONSUMPTION_STATISTIC_ID,
                unit_of_measurement='kWh'
            )
            cost_metadata = StatisticMetaData(
                name=COST_STATISTIC_NAME,
                has_mean=False,
                has_sum=True,
                source=DOMAIN,
                statistic_id=COST_STATISTIC_ID,
                unit_of_measurement='EUR',
            )
            _LOGGER.info(f"len(consumption_statistics)={len(consumption_statistics)}, len(cost_statistics)={len(cost_statistics)}")
            await get_instance(hass).async_add_executor_job(async_add_external_statistics, hass, consumption_metadata, consumption_statistics)
            await get_instance(hass).async_add_executor_job(async_add_external_statistics, hass, cost_metadata, cost_statistics)
        _LOGGER.debug(f"END - reprocess_statistics()")

    async def import_energy_data(hass):
        _LOGGER.debug(f"START - import_energy_data()")
        start_date = datetime.date.min
        end_date = datetime.date.today() - datetime.timedelta(days=2)

        total_consumptions = {}
        total_energy_consumption = 0
        total_energy_cost = 0

        last_stat = await get_instance(hass).async_add_executor_job(get_last_statistics, hass, 1, CONSUMPTION_STATISTIC_ID, True, set())
        if last_stat:
            start = datetime.datetime.utcfromtimestamp(last_stat[CONSUMPTION_STATISTIC_ID][0]['start']).replace(tzinfo=datetime.timezone.utc)
            stats = await get_instance(hass).async_add_executor_job(statistics_during_period, hass, start, None, {CONSUMPTION_STATISTIC_ID, COST_STATISTIC_ID}, 'hour', None, {'sum'})
            total_energy_consumption = stats[CONSUMPTION_STATISTIC_ID][0]["sum"]
            total_energy_cost = stats[COST_STATISTIC_ID][0]["sum"]
            start_date = (datetime.datetime.fromtimestamp(stats[COST_STATISTIC_ID][0]["start"]) + datetime.timedelta(hours=1)).date()
            _LOGGER.info(f"last_stat={last_stat}, stats={stats}")
        
        _LOGGER.info(f"start_date={start_date.isoformat()}, end_date={end_date.isoformat()}")
        if end_date >= start_date:
            total_consumptions, total_prices = PvpcCoordinator.load_energy_data(ENERGY_FILE)
            consumptions_len = len(total_consumptions)
            prices_len = len(total_prices)
            consumptions = await PvpcCoordinator.get_data(UFD.consumptions, start_date, end_date, total_consumptions, 14)
            prices = await PvpcCoordinator.get_data(REE.pvpc, start_date, end_date, total_prices, 28)
            if len(total_consumptions) > consumptions_len or len(total_prices) > prices_len:
                PvpcCoordinator.save_energy_data(ENERGY_FILE, total_consumptions, total_prices)

            _LOGGER.info(f"len(consumptions)={len(consumptions)}")
            if len(consumptions) > 0:
                start_date = max(start_date, datetime.datetime.fromtimestamp(min(list(consumptions.keys()))).date())
                consumption_statistics, cost_statistics = PvpcCoordinator.create_statistics(consumptions, prices, total_energy_consumption, total_energy_cost)
        
                consumption_metadata = StatisticMetaData(
                    name=CONSUMPTION_STATISTIC_NAME,
                    has_mean=False,
                    has_sum=True,
                    source=DOMAIN,
                    statistic_id=CONSUMPTION_STATISTIC_ID,
                    unit_of_measurement='kWh'
                )
                cost_metadata = StatisticMetaData(
                    name=COST_STATISTIC_NAME,
                    has_mean=False,
                    has_sum=True,
                    source=DOMAIN,
                    statistic_id=COST_STATISTIC_ID,
                    unit_of_measurement='EUR',
                )
                _LOGGER.info(f"len(consumption_statistics)={len(consumption_statistics)}, len(cost_statistics)={len(cost_statistics)}")
                await get_instance(hass).async_add_executor_job(async_add_external_statistics, hass, consumption_metadata, consumption_statistics)
                await get_instance(hass).async_add_executor_job(async_add_external_statistics, hass, cost_metadata, cost_statistics)
                await PvpcCoordinator.calculate_bills(total_consumptions, hass)
        if not hass.states.get(CURRENT_BILL_STATE):
            if len(total_consumptions) == 0:
                total_consumptions, total_prices = PvpcCoordinator.load_energy_data(ENERGY_FILE)
            await PvpcCoordinator.calculate_bills(total_consumptions, hass)

        _LOGGER.debug(f"END - import_energy_data")

    async def get_data(getter, start_date, end_date, total_data, days):
        _LOGGER.debug(f"START - get_data(getter={getter}, start_date={start_date.isoformat()}, end_date={end_date.isoformat()}, len(total_data)={len(total_data)}, days={days})")    
        result = {}
        timestamps = total_data.keys()
        if start_date == None: start_date = datetime.date.min

        start_timestamp = 0 if start_date == datetime.date.min else int(time.mktime(start_date.timetuple()))
        end_timestamp = int(time.mktime(datetime.datetime(end_date.year, end_date.month, end_date.day, 23).timetuple()))
        for timestamp, value in total_data.items():
            if start_timestamp <= timestamp <= end_timestamp:
                result[timestamp] = value

        request_end_date = end_date + datetime.timedelta(days=1)
        while request_end_date > start_date:
            request_start_date = request_end_date - datetime.timedelta(days=1)
            while int(time.mktime(request_start_date.timetuple())) in timestamps and request_start_date >= start_date:
                request_start_date -= datetime.timedelta(days=1)
            if request_start_date < start_date: break
            request_end_date = request_start_date - datetime.timedelta(days=1)
            while int(time.mktime(request_end_date.timetuple())) not in timestamps and request_end_date >= start_date and (request_start_date - request_end_date).days < days:
                request_end_date -= datetime.timedelta(days=1)
            request_end_date += datetime.timedelta(days=1)
            data = await getter(request_end_date, request_start_date)
            if len(data) == 0: break
            result |= data
            total_data |= data
        _LOGGER.debug(f"END - get_data: len(result)={len(result)}")
        return result

    async def calculate_bills(consumptions, hass):
        _LOGGER.debug(f"START - calculate_bills(len(consumptions)={len(consumptions)})")

        if len(consumptions) > 0:
            periods_start_date = datetime.date.fromtimestamp(min(consumptions.keys()))
            periods_end_date = datetime.date.today()
            billing_periods = PvpcCoordinator.load_billing_periods(BILLING_PERIODS_FILE)
            if len(billing_periods) > 0:
                periods_start_date = billing_periods[-1]['end_date']
            _LOGGER.info(f"periods_start_date={periods_start_date.isoformat()}, periods_end_date={periods_end_date.isoformat()}, (periods_end_date - periods_start_date).days={(periods_end_date - periods_start_date).days}")
            if (periods_end_date - periods_start_date).days > 25:
                new_billing_periods = await UFD.billingPeriods(periods_start_date, periods_end_date)
                if len(new_billing_periods) > 0:
                    billing_periods += new_billing_periods
                    PvpcCoordinator.save_billing_periods(BILLING_PERIODS_FILE, billing_periods)

            update = False
            for billing_period in reversed(billing_periods):
                if 'total_consumption' not in billing_period:
                    billing_period = await PvpcCoordinator.get_bill(billing_period, consumptions)
                    if 'total_consumption' in billing_period:
                        update = True
            if update:
                PvpcCoordinator.save_billing_periods(BILLING_PERIODS_FILE, billing_periods)

            current_billing_period = {'start_date': billing_periods[-1]['end_date'] + datetime.timedelta(days=1), 'end_date':datetime.date.today()}
            current_billing_period = await PvpcCoordinator.get_bill(current_billing_period, consumptions)

            current_bill_value = ''
            bills_description = ''
            if 'total_cost' in current_billing_period:
                billing_periods.append(current_billing_period)
                current_bill_value = '%.2f' % current_billing_period['total_cost']
                days = (current_billing_period['end_date'] - current_billing_period['start_date']).days + 1

                estimation_days = 30
                if estimation_days > days:
                    estimation_end_date = current_billing_period['start_date'] + datetime.timedelta(days=estimation_days-1)
                    cost = round(current_billing_period['total_cost'] / days * estimation_days, 2)
                    bills_description += f"Estimación {current_billing_period['start_date'].strftime('%d/%m')} - {estimation_end_date.strftime('%d/%m')} ({estimation_days} días): **{cost} €**\n\n"
                
            bills_description += '| Fecha | Días | Importe | kWh | cent/kWh | €/día | kWh/día |\n'
            bills_description += '| :---: | :---: | :---: | :---: | :---: | :---: | :---: |'
            for billing_period in reversed(billing_periods[-PvpcCoordinator.bills_number:]):
                date = billing_period['end_date'].strftime('%d/%m')
                days = (billing_period['end_date'] - billing_period['start_date']).days + 1
                cost = round(billing_period['total_cost'], 2)
                consumption = round(billing_period['total_consumption'], 0)
                cost_kwh = round(billing_period['energy_cost'] / billing_period['total_consumption'] * 100, 1)
                day_cost = round(billing_period['total_cost'] / days, 2)
                day_consumption = round(billing_period['total_consumption'] / days, 1)
                if billing_period == current_billing_period:
                    bills_description += f"\n|\n| {date} | {days} | {cost} | {consumption} | **{cost_kwh}** | {day_cost} | {day_consumption} |\n|"
                else:
                    bills_description += f"\n| {date} | {days} | {cost} | {consumption} | {cost_kwh} | {day_cost} | {day_consumption} |"

            _LOGGER.info(f"current_bill_value={current_bill_value}, bills_description={bills_description}")
            hass.states.async_set(CURRENT_BILL_STATE, current_bill_value, {'detail': bills_description})
        _LOGGER.debug(f"END - calculate_bills")

    async def get_bill(billing_period, consumptions):
        _LOGGER.debug(f"START - get_bill(billing_period={billing_period}, len(consumptions)={len(consumptions)})")
        start_timestamp = int(time.mktime(billing_period['start_date'].timetuple()))
        end_timestamp = int(time.mktime((billing_period['end_date'] + datetime.timedelta(days=1)).timetuple())) - 3600
        total_consumption = 0.0
        bill_consumptions = {}
        for timestamp, consumption in consumptions.items():
            if start_timestamp <= timestamp <= end_timestamp:
                bill_consumptions[timestamp] = consumption
                total_consumption += consumption

        if end_timestamp - start_timestamp <= (3600 * 24): return {}

        bill = await CNMC.calculate_bill(PvpcCoordinator.cups, bill_consumptions, PvpcCoordinator.power_high, PvpcCoordinator.power_low, PvpcCoordinator.zip_code)
        if 'graficoGastoTotalActual' in bill:
            billing_period['start_date'] = datetime.datetime.strptime(bill['graficaConsumoDiario']['consumosDiarios'][0]['fecha'], '%d/%m/%Y').date()
            billing_period['end_date'] = datetime.datetime.strptime(bill['graficaConsumoDiario']['consumosDiarios'][-1]['fecha'], '%d/%m/%Y').date()
            billing_period['total_cost'] = bill['graficoGastoTotalActual']['importeTotal']
            billing_period['power_cost'] = bill['graficoGastoTotalActual']['importePotencia']
            billing_period['energy_cost'] = bill['graficoGastoTotalActual']['importeEnergia']
            billing_period['rent_cost'] = bill['graficoGastoTotalActual']['importeAlquiler']
            billing_period['tax_cost'] = bill['graficoGastoTotalActual']['importeIVA']
        billing_period['total_consumption'] = total_consumption

        _LOGGER.debug(f"END - get_bill: {billing_period}")
        return billing_period

    def load_energy_data(file_path):
        _LOGGER.debug(f"START - load_energy_data(file_path={file_path})")
        consumptions = {}
        prices = {}
        if exists(file_path):
            with open(file_path, 'r') as file:
                file.readline()
                for line in file:
                    timestamp, consumption, price = line[0:-1].split(',')
                    timestamp = int(timestamp)
                    if consumption != '':
                        consumptions[timestamp] = float(consumption)
                    if price != '':
                        prices[timestamp] = float(price)
        _LOGGER.debug(f"END - load_energy_data: len(consumptions): {len(consumptions)}, len(prices): {len(prices)}")
        return consumptions, prices

    def save_energy_data(file_path, consumptions, prices):
        _LOGGER.debug(f"START - save_energy_data(file_path={file_path}, len(consumptions)={len(consumptions)}, len(prices)={len(prices)})")
        timestamps = list(consumptions.keys())
        timestamps = timestamps + list(set(list(prices.keys())) - set(timestamps))
        timestamps.sort()
        with open(file_path, 'w') as file:
            file.write("timestamp,consumption,price\n")
            for timestamp in timestamps:
                consumption = '' if timestamp not in consumptions else consumptions[timestamp]
                price = '' if timestamp not in prices else prices[timestamp]
                file.write(f"{timestamp},{consumption},{price}\n")
        _LOGGER.debug(f"END - save_energy_data")

    def load_billing_periods(file_path):
        _LOGGER.debug(f"START - load_billing_periods(file_path={file_path})")
        billing_periods = []
        if exists(file_path):
            with open(file_path, 'r') as file:
                file.readline()
                for line in file:
                    start_date, end_date, total_cost, power_cost, energy_cost, rent_cost, tax_cost, total_consumption = line[0:-1].split(',')
                    billing_period = {'start_date': datetime.date.fromisoformat(start_date), 'end_date': datetime.date.fromisoformat(end_date)}
                    if total_cost != '': billing_period['total_cost'] = float(total_cost)
                    if power_cost != '': billing_period['power_cost'] = float(power_cost)
                    if energy_cost != '': billing_period['energy_cost'] = float(energy_cost)
                    if rent_cost != '': billing_period['rent_cost'] = float(rent_cost)
                    if tax_cost != '': billing_period['tax_cost'] = float(tax_cost)
                    if total_consumption != '': billing_period['total_consumption'] = float(total_consumption)
                    billing_periods.append(billing_period)
        _LOGGER.debug(f"END - load_billing_periods: len(billing_periods): {len(billing_periods)}")
        return billing_periods

    def save_billing_periods(file_path, billing_periods):
        _LOGGER.debug(f"START - save_billing_periods(file_path={file_path}, len(billing_periods)={len(billing_periods)})")
        with open(file_path, 'w') as file:
            file.write("start_date,end_date,total_cost,power_cost,energy_cost,rent_cost,tax_cost,total_consumption\n")
            for billing_period in billing_periods:
                total_cost = billing_period['total_cost'] if 'total_cost' in billing_period else ''
                power_cost = billing_period['power_cost'] if 'power_cost' in billing_period else ''
                energy_cost = billing_period['energy_cost'] if 'energy_cost' in billing_period else ''
                rent_cost = billing_period['rent_cost'] if 'rent_cost' in billing_period else ''
                tax_cost = billing_period['tax_cost'] if 'tax_cost' in billing_period else ''
                total_consumption = billing_period['total_consumption'] if 'total_consumption' in billing_period else ''

                file.write(f"{billing_period['start_date'].isoformat()},{billing_period['end_date'].isoformat()},{total_cost},{power_cost},{energy_cost},{rent_cost},{tax_cost},{total_consumption}\n")
        _LOGGER.debug(f"END - save_billing_periods")

    def create_statistics(consumptions, prices, total_energy_consumption, total_energy_cost):
        _LOGGER.debug(f"START - create_statistics(len(consumptions)={len(consumptions)}, len(prices)={len(prices)}, total_energy_consumption={total_energy_consumption}, total_energy_cost={total_energy_cost})")
        day_energy_consumption = 0
        day_energy_cost = 0
        consumption_statistics = []
        cost_statistics = []
        timestamps = list(consumptions.keys())
        timestamps.sort()
        for timestamp in timestamps:
            consumption = consumptions[timestamp]
            total_energy_consumption += consumption
            day_energy_consumption += consumption
            if datetime.datetime.fromtimestamp(timestamp).hour == 0:
                day_energy_consumption = consumption
            start = datetime.datetime.utcfromtimestamp(timestamp).replace(tzinfo=datetime.timezone.utc)
            consumption_statistics.append(
                StatisticData(
                    start=start, state=day_energy_consumption, sum=total_energy_consumption
                )
            )

            if timestamp in prices:
                cost = prices[timestamp]
                hour_cost = consumption * cost
                total_energy_cost += hour_cost
                day_energy_cost += hour_cost
                if datetime.datetime.fromtimestamp(timestamp).hour == 0:
                    day_energy_cost = hour_cost
                cost_statistics.append(
                    StatisticData(
                        start=start, state=day_energy_cost, sum=total_energy_cost
                    )
                )
        _LOGGER.debug(f"END - create_statistics: len(consumption_statistics)={len(consumption_statistics)}, len(cost_statistics)={len(cost_statistics)}")
        return consumption_statistics, cost_statistics
