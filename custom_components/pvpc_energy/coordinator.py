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
from os import makedirs
import logging

_LOGGER = logging.getLogger(__name__)


class PvpcCoordinator:
    ufd_login = None
    ufd_password = None
    cups = None
    zip_code = None
    contract_start_date = None
    bills_number = None

    def set_config(config):
        _LOGGER.debug(f"START - set_config(config={config})")
        PvpcCoordinator.ufd_login = config['ufd_login']
        PvpcCoordinator.ufd_password = config['ufd_password']
        PvpcCoordinator.cups = config['cups']
        PvpcCoordinator.zip_code = config['zip_code']
        if 'contract_start_date' in config:
            PvpcCoordinator.contract_start_date = datetime.datetime.strptime(config['contract_start_date'], '%d/%m/%Y').date()
        PvpcCoordinator.bills_number = config['bills_number']

        UFD.User = config['ufd_login']
        UFD.Password = config['ufd_password']
        UFD.cups = config['cups']        
        _LOGGER.debug(f"END - set_config")

    async def reprocess_energy_data(hass):
        _LOGGER.debug(f"START - reprocess_statistics()")
        consumptions, prices = await PvpcCoordinator.load_energy_data(hass, ENERGY_FILE)

        _LOGGER.info(f"len(total_consumptions)={len(consumptions)}")
        if len(consumptions) > 0:
            consumption_statistics, cost_statistics = PvpcCoordinator.create_statistics(0, consumptions, prices, 0, 0)
    
            consumption_metadata = StatisticMetaData(
                name=CONSUMPTION_STATISTIC_NAME,
                mean_type=0,
                unit_class=None,
                has_sum=True,
                source=DOMAIN,
                statistic_id=CONSUMPTION_STATISTIC_ID,
                unit_of_measurement='kWh'
            )
            cost_metadata = StatisticMetaData(
                name=COST_STATISTIC_NAME,
                mean_type=0,
                unit_class=None,
                has_sum=True,
                source=DOMAIN,
                statistic_id=COST_STATISTIC_ID,
                unit_of_measurement='EUR',
            )
            _LOGGER.info(f"len(consumption_statistics)={len(consumption_statistics)}, len(cost_statistics)={len(cost_statistics)}")
            get_instance(hass).async_add_executor_job(async_add_external_statistics, hass, consumption_metadata, consumption_statistics)
            get_instance(hass).async_add_executor_job(async_add_external_statistics, hass, cost_metadata, cost_statistics)

            billing_periods = await PvpcCoordinator.load_billing_periods(hass, BILLING_PERIODS_FILE)
            await PvpcCoordinator.calculate_bills(hass, billing_periods, consumptions, True)
        _LOGGER.debug(f"END - reprocess_statistics()")

    async def import_energy_data(hass, force_update=False):
        _LOGGER.debug(f"START - import_energy_data(), force_update={force_update}")

        consumptions, prices = await PvpcCoordinator.load_energy_data(hass, ENERGY_FILE)
        consumptions_len = len(consumptions)
        prices_len = len(prices)

        start_date = datetime.datetime(year=datetime.date.today().year - 2, month=datetime.date.today().month, day=1).date()
        if PvpcCoordinator.contract_start_date:
            start_date = PvpcCoordinator.contract_start_date
        end_date = datetime.date.today() - datetime.timedelta(days=2)

        first_consumption_date = None
        last_consumption_date = None
        start_billing_date = start_date
        if consumptions_len > 0:
            first_consumption_date = datetime.datetime.fromtimestamp(min(list(consumptions.keys()))).date()
            last_consumption_date = datetime.datetime.fromtimestamp(max(list(consumptions.keys()))).date()
            start_billing_date = min(start_date, first_consumption_date)

        get_new_periods = last_consumption_date is None or end_date > last_consumption_date
        billing_periods = await PvpcCoordinator.get_billing_periods(hass, start_billing_date, get_new_periods)

        first_billing_date = None
        for billing_period in billing_periods:
            if not first_billing_date or billing_period['start_date'] < first_billing_date:
                first_billing_date = billing_period['start_date']
        if first_billing_date and first_billing_date > start_date:
            start_date = first_billing_date

        if force_update or first_consumption_date is None or first_consumption_date > start_date:
            await PvpcCoordinator.get_data(UFD.consumptions, start_date, end_date, consumptions, 14, force_update)
        elif end_date > last_consumption_date:
            await PvpcCoordinator.get_data(UFD.consumptions, last_consumption_date + datetime.timedelta(days=1), end_date, consumptions, 14)
        
        first_price_date = None
        last_price_date = None
        if prices_len > 0:
            first_price_date = datetime.datetime.fromtimestamp(min(list(prices.keys()))).date()
            last_price_date = datetime.datetime.fromtimestamp(max(list(prices.keys()))).date()

        if force_update or first_price_date is None or first_price_date > start_date:
            await PvpcCoordinator.get_data(REE.pvpc, start_date, end_date, prices, 28, force_update)
        elif end_date > last_price_date:
            await PvpcCoordinator.get_data(REE.pvpc, last_price_date + datetime.timedelta(days=1), end_date, prices, 28)
        
        if force_update or len(consumptions) > consumptions_len or len(prices) > prices_len:
            await PvpcCoordinator.save_energy_data(hass, ENERGY_FILE, consumptions, prices)

            if len(consumptions) > 0:
                last_stat = await get_instance(hass).async_add_executor_job(get_last_statistics, hass, 1, CONSUMPTION_STATISTIC_ID, True, set())
                if force_update or last_stat is None or first_consumption_date is None or first_consumption_date != datetime.datetime.fromtimestamp(min(list(consumptions.keys()))).date():
                    consumption_statistics, cost_statistics = PvpcCoordinator.create_statistics(0, consumptions, prices, 0, 0)
                else:
                    start = datetime.datetime.utcfromtimestamp(last_stat[CONSUMPTION_STATISTIC_ID][0]['start']).replace(tzinfo=datetime.timezone.utc)
                    stats = await get_instance(hass).async_add_executor_job(statistics_during_period, hass, start, None, {CONSUMPTION_STATISTIC_ID, COST_STATISTIC_ID}, 'hour', None, {'sum'})
                    total_energy_consumption = stats[CONSUMPTION_STATISTIC_ID][0]["sum"]
                    total_energy_cost = stats[COST_STATISTIC_ID][0]["sum"]
                    last_statistic_timestamp = stats[COST_STATISTIC_ID][0]["start"]
                    _LOGGER.info(f"last_stat={last_stat}, stats={stats}")
                    consumption_statistics, cost_statistics = PvpcCoordinator.create_statistics(last_statistic_timestamp, consumptions, prices, total_energy_consumption, total_energy_cost)
        
                consumption_metadata = StatisticMetaData(
                    name=CONSUMPTION_STATISTIC_NAME,
                    mean_type=0,
                    unit_class=None,
                    has_sum=True,
                    source=DOMAIN,
                    statistic_id=CONSUMPTION_STATISTIC_ID,
                    unit_of_measurement='kWh'
                )
                cost_metadata = StatisticMetaData(
                    name=COST_STATISTIC_NAME,
                    mean_type=0,
                    unit_class=None,
                    has_sum=True,
                    source=DOMAIN,
                    statistic_id=COST_STATISTIC_ID,
                    unit_of_measurement='EUR',
                )
                _LOGGER.info(f"len(consumption_statistics)={len(consumption_statistics)}, len(cost_statistics)={len(cost_statistics)}")
                get_instance(hass).async_add_executor_job(async_add_external_statistics, hass, consumption_metadata, consumption_statistics)
                get_instance(hass).async_add_executor_job(async_add_external_statistics, hass, cost_metadata, cost_statistics)
                await PvpcCoordinator.calculate_bills(hass, billing_periods, consumptions, force_update)
        elif not hass.states.get(CURRENT_BILL_STATE) and len(consumptions) > 0:
            await PvpcCoordinator.calculate_bills(hass, billing_periods, consumptions, force_update)

        _LOGGER.debug(f"END - import_energy_data")

    async def get_data(getter, start_date, end_date, data, days, force_update=False):
        _LOGGER.debug(f"START - get_data(getter={getter}, start_date={start_date.isoformat()}, end_date={end_date.isoformat()}, len(data)={len(data)}, days={days}, force_update={force_update})")    
        data_len = len(data)
        
        request_start_date = end_date + datetime.timedelta(days=1)
        while request_start_date > start_date:
            request_end_date = request_start_date - datetime.timedelta(days=1)
            while not force_update and int(time.mktime(request_end_date.timetuple())) in data.keys() and request_end_date >= start_date:
                request_end_date -= datetime.timedelta(days=1)
            if request_end_date < start_date: break
            request_start_date = request_end_date - datetime.timedelta(days=1)
            while (force_update or int(time.mktime(request_start_date.timetuple())) not in data.keys()) and request_start_date >= start_date and (request_end_date - request_start_date).days < days:
                request_start_date -= datetime.timedelta(days=1)
            request_start_date += datetime.timedelta(days=1)
            new_data = await getter(request_start_date, request_end_date)

            if new_data is None:
                break
            elif len(new_data) > 0:
                data.update(new_data)

        _LOGGER.debug(f"END - get_data: new_data=={len(data)-data_len}")

    async def get_billing_periods(hass, start_billing_date, get_new_periods):
        _LOGGER.debug(f"START - get_billing_periods(start_billing_date={start_billing_date}, get_new_periods={get_new_periods})")
        billing_periods = await PvpcCoordinator.load_billing_periods(hass, BILLING_PERIODS_FILE)

        if start_billing_date:
            remove_periods = []
            for billing_period in billing_periods:
                if billing_period['start_date'] < start_billing_date:
                    remove_periods.append(billing_period)
            if len(remove_periods) > 0:
                for billing_period in remove_periods:
                    billing_periods.remove(billing_period)
                await PvpcCoordinator.save_billing_periods(hass, BILLING_PERIODS_FILE, billing_periods)

        if len(billing_periods) == 0:
            start_date = datetime.date(2000, 1, 1)
        else:
            start_date = billing_periods[-1]['end_date']
            previous_end_date = None
            for billing_period in billing_periods:
                if previous_end_date and billing_period['start_date'] != (previous_end_date + datetime.timedelta(days=1)):
                    billing_period['start_date'] = previous_end_date + datetime.timedelta(days=1)
                    if 'total_cost' in billing_period:
                        del billing_period['total_cost']
                previous_end_date = billing_period['end_date']

        end_date = datetime.date.today()
        _LOGGER.debug(f"start_date={start_date.isoformat()}, end_date={end_date.isoformat()}, (end_date - start_date).days={(end_date - start_date).days}")
        if get_new_periods and (end_date - start_date).days > 2:
            new_billing_periods = await UFD.billingPeriods(start_date, end_date)
            if len(new_billing_periods) > 0:
                billing_periods += new_billing_periods
                await PvpcCoordinator.save_billing_periods(hass, BILLING_PERIODS_FILE, billing_periods)
        _LOGGER.debug(f"END - get_billing_periods: len(billing_periods)={len(billing_periods)}")
        return billing_periods

    async def calculate_bills(hass, billing_periods, consumptions, force_update=False):
        _LOGGER.debug(f"START - calculate_bills(len(billing_periods)={len(billing_periods)}, len(consumptions)={len(consumptions)}, force_update={force_update})")

        if len(consumptions) > 0 and len(billing_periods) > 0:
            update = False
            first_consumption_date = datetime.datetime.fromtimestamp(min(consumptions.keys())).date()
            last_consumption_date = datetime.datetime.fromtimestamp(max(consumptions.keys())).date()
            for billing_period in reversed(billing_periods):
                if billing_period['start_date'] >= first_consumption_date and (force_update or 'total_cost' not in billing_period):
                    billing_period = await PvpcCoordinator.get_bill(hass, billing_period, consumptions)
                    if 'total_cost' in billing_period:
                        update = True
            if update:
                await PvpcCoordinator.save_billing_periods(hass, BILLING_PERIODS_FILE, billing_periods)

            current_billing_period = None
            if (last_consumption_date - billing_periods[-1]['end_date']).days >= 2:
                current_billing_period = {'start_date': billing_periods[-1]['end_date'] + datetime.timedelta(days=1), 'end_date':last_consumption_date}
                current_billing_period['power_high'], current_billing_period['power_low'] = await UFD.supplyPointPowers(PvpcCoordinator.cups)
                current_billing_period = await PvpcCoordinator.get_bill(hass, current_billing_period, consumptions)

            current_bill_value = ''
            bills_description = ''
            if current_billing_period and 'total_cost' in current_billing_period and current_billing_period['total_cost'] != '-':
                billing_periods.append(current_billing_period)
                current_bill_value = '%.2f' % current_billing_period['total_cost']
                days = (current_billing_period['end_date'] - current_billing_period['start_date']).days + 1

                estimation_days = 30
                if estimation_days > days:
                    estimation_end_date = current_billing_period['start_date'] + datetime.timedelta(days=estimation_days-1)
                    cost = round(current_billing_period['total_cost'] / days * estimation_days, 2)
                    bills_description += f"Estimación {current_billing_period['start_date'].strftime('%d/%m')} - {estimation_end_date.strftime('%d/%m')} ({estimation_days} días): **{cost} €**\n\n"
                    
            bills_description += '| Fecha | Días | Importe | kWh | kWh/día | cent/kWh | €/día |\n'
            bills_description += '| :---: | :---: | :---: | :---: | :---: | :---: | :---: |'
            for billing_period in reversed(billing_periods[-PvpcCoordinator.bills_number:]):
                if 'total_cost' in billing_period and billing_period['total_cost'] != '-':
                    date = billing_period['end_date'].strftime('%d/%m')
                    days = (billing_period['end_date'] - billing_period['start_date']).days + 1
                    consumption = round(billing_period['total_consumption'], 0)
                    day_consumption = round(billing_period['total_consumption'] / days, 1)
                    cost = ''
                    cost_kwh = ''
                    day_cost = ''
                    if 'total_cost' in billing_period and billing_period['total_cost'] != '-':
                        cost = round(billing_period['total_cost'], 2)
                        if billing_period['total_consumption'] != 0:
                            cost_kwh = round(billing_period['energy_cost'] / billing_period['total_consumption'] * 100, 1)
                        day_cost = round(billing_period['total_cost'] / days, 2)
                    if billing_period == current_billing_period:
                        bills_description += f"\n|\n| {date} | {days} | {cost} | {consumption} | {day_consumption} | **{cost_kwh}** | {day_cost} |\n|"
                    else:
                        bills_description += f"\n| {date} | {days} | {cost} | {consumption} | {day_consumption} | {cost_kwh} | {day_cost} |"

            _LOGGER.debug(f"current_bill_value={current_bill_value}, bills_description={bills_description}")
            hass.states.async_set(CURRENT_BILL_STATE, current_bill_value, {'detail': bills_description})
        _LOGGER.debug(f"END - calculate_bills")

    async def get_bill(hass, billing_period, consumptions):
        _LOGGER.debug(f"START - get_bill(billing_period={billing_period}, len(consumptions)={len(consumptions)})")
        start_timestamp = int(time.mktime(billing_period['start_date'].timetuple()))
        end_timestamp = int(time.mktime((billing_period['end_date'] + datetime.timedelta(days=1)).timetuple())) - 3600
        bill_consumptions = {}
        for timestamp, consumption in consumptions.items():
            if start_timestamp <= timestamp <= end_timestamp:
                bill_consumptions[timestamp] = consumption
        if bill_consumptions:
            billing_period, consumptions_file = await CNMC.calculate_bill(billing_period, PvpcCoordinator.cups, bill_consumptions, PvpcCoordinator.zip_code)
            if consumptions_file is not None:
                path = f"{USER_FILES_PATH}/consumption_files/{billing_period['start_date'].year}"
                if not exists(path):
                    makedirs(path)
                with await hass.async_add_executor_job(open, f"{path}/consumptions_{billing_period['start_date'].strftime('%Y-%m-%d')}.csv", 'w') as file:
                    file.write(consumptions_file)
        _LOGGER.debug(f"END - get_bill: {billing_period}")
        return billing_period

    async def load_energy_data(hass, file_path):
        _LOGGER.debug(f"START - load_energy_data(file_path={file_path})")
        consumptions = {}
        prices = {}
        if exists(file_path):
            with await hass.async_add_executor_job(open, file_path, 'r') as file:
                file.readline()
                for line in file:
                    timestamp, consumption, price = line[0:-1].split(',')[-3:]
                    timestamp = int(timestamp)
                    if consumption != '-' and consumption != '':
                        consumptions[timestamp] = float(consumption)
                    if price != '-' and price != '':
                        prices[timestamp] = float(price)
        _LOGGER.debug(f"END - load_energy_data: len(consumptions): {len(consumptions)}, len(prices): {len(prices)}")
        return consumptions, prices

    async def save_energy_data(hass, file_path, consumptions, prices):
        _LOGGER.debug(f"START - save_energy_data(file_path={file_path}, len(consumptions)={len(consumptions)}, len(prices)={len(prices)})")
        timestamps = list(consumptions.keys())
        timestamps = timestamps + list(set(list(prices.keys())) - set(timestamps))
        timestamps.sort()
        with await hass.async_add_executor_job(open, file_path, 'w') as file:
            file.write("date,timestamp,consumption,price\n")
            for timestamp in timestamps:
                date = datetime.datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H')
                consumption = '' if timestamp not in consumptions else consumptions[timestamp]
                price = '' if timestamp not in prices else prices[timestamp]
                file.write(f"{date},{timestamp},{consumption},{price}\n")
        _LOGGER.debug(f"END - save_energy_data")

    async def load_billing_periods(hass, file_path):
        _LOGGER.debug(f"START - load_billing_periods(file_path={file_path})")
        billing_periods = []
        update = False
        if exists(file_path):
            with await hass.async_add_executor_job(open, file_path, 'r') as file:
                if file.readline().count(',') == 7:
                    update = True
                    power_high, power_low = await UFD.supplyPointPowers(PvpcCoordinator.cups)
                for line in file:
                    if line.count(',') == 7:
                        start_date, end_date, total_cost, power_cost, energy_cost, rent_cost, tax_cost, total_consumption = line[0:-1].split(',')
                    else:
                        start_date, end_date, power_high, power_low, total_cost, power_cost, energy_cost, rent_cost, tax_cost, total_consumption = line[0:-1].split(',')

                    billing_period = {'start_date': datetime.date.fromisoformat(start_date), 'end_date': datetime.date.fromisoformat(end_date)}
                    billing_period['power_high'] = float(power_high)
                    billing_period['power_low'] = float(power_low)
                    if total_cost != '':
                        if total_cost == '-':
                            billing_period['total_cost'] = total_cost
                        else:
                            billing_period['total_cost'] = float(total_cost)
                    if power_cost != '': billing_period['power_cost'] = float(power_cost)
                    if energy_cost != '': billing_period['energy_cost'] = float(energy_cost)
                    if rent_cost != '': billing_period['rent_cost'] = float(rent_cost)
                    if tax_cost != '': billing_period['tax_cost'] = float(tax_cost)
                    if total_consumption != '': billing_period['total_consumption'] = float(total_consumption)
                    billing_periods.append(billing_period)
        if update:
            await PvpcCoordinator.save_billing_periods(hass, file_path, billing_periods)
        _LOGGER.debug(f"END - load_billing_periods: len(billing_periods): {len(billing_periods)}")
        return billing_periods

    async def save_billing_periods(hass, file_path, billing_periods):
        _LOGGER.debug(f"START - save_billing_periods(file_path={file_path}, len(billing_periods)={len(billing_periods)})")
        with await hass.async_add_executor_job(open, file_path, 'w') as file:
            file.write("start_date,end_date,power_high,power_low,total_cost,power_cost,energy_cost,rent_cost,tax_cost,total_consumption\n")
            for billing_period in billing_periods:
                total_cost = billing_period['total_cost'] if 'total_cost' in billing_period else ''
                power_cost = billing_period['power_cost'] if 'power_cost' in billing_period else ''
                energy_cost = billing_period['energy_cost'] if 'energy_cost' in billing_period else ''
                rent_cost = billing_period['rent_cost'] if 'rent_cost' in billing_period else ''
                tax_cost = billing_period['tax_cost'] if 'tax_cost' in billing_period else ''
                total_consumption = billing_period['total_consumption'] if 'total_consumption' in billing_period else ''

                file.write(f"{billing_period['start_date'].isoformat()},{billing_period['end_date'].isoformat()},{billing_period['power_high']},{billing_period['power_low']},{total_cost},{power_cost},{energy_cost},{rent_cost},{tax_cost},{total_consumption}\n")
        _LOGGER.debug(f"END - save_billing_periods")

    def create_statistics(last_statistic_timestamp, consumptions, prices, total_energy_consumption, total_energy_cost):
        _LOGGER.debug(f"START - create_statistics(last_statistic_timestamp={last_statistic_timestamp}, len(consumptions)={len(consumptions)}, len(prices)={len(prices)}, total_energy_consumption={total_energy_consumption}, total_energy_cost={total_energy_cost})")
        day_energy_consumption = 0
        day_energy_cost = 0
        consumption_statistics = []
        cost_statistics = []
        timestamp = max(min(consumptions.keys()), last_statistic_timestamp + 3600)
        last_timestamp = max(consumptions.keys())
        while timestamp <= last_timestamp:
            consumption = 0
            if timestamp in consumptions:
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

            cost = 0
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
            timestamp += 3600
        _LOGGER.debug(f"END - create_statistics: len(consumption_statistics)={len(consumption_statistics)}, len(cost_statistics)={len(cost_statistics)}")
        return consumption_statistics, cost_statistics
