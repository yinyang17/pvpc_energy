"""The PVPC Energy integration."""
from .const import DOMAIN, CURRENT_BILL_STATE, CONSUMPTION_STATISTIC_ID, CONSUMPTION_STATISTIC_NAME, COST_STATISTIC_ID, COST_STATISTIC_NAME, USER_FILES_PATH, ENERGY_FILE, BILLING_PERIODS_FILE
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (async_add_external_statistics, get_last_statistics, statistics_during_period, )
from homeassistant.helpers.event import async_track_time_change
import datetime
import time
from os.path import exists
from os import makedirs
import requests
import random
import base64
import logging

_LOGGER = logging.getLogger(__name__)

def setup(hass, config):
    def handle_import_energy_data(call):
        hass.async_create_task(import_energy_data(hass))

    UFD.User = config['pvpc_energy']['ufd_login']
    UFD.Password = config['pvpc_energy']['ufd_password']
    UFD.cups = config['pvpc_energy']['cups']
    UFD.power_high = config['pvpc_energy']['power_high']
    UFD.power_low = config['pvpc_energy']['power_low']
    UFD.zip_code = config['pvpc_energy']['zip_code']
    UFD.bills_number = config['pvpc_energy']['bills_number']

    if not exists(USER_FILES_PATH):
        makedirs(USER_FILES_PATH)

    hass.services.register(DOMAIN, "import_energy_data", handle_import_energy_data)
    async_track_time_change(hass, handle_import_energy_data, hour=7, minute=5, second=0)
    handle_import_energy_data(None)

    _LOGGER.debug(f"pvpc_energy: setup OK, config={config['pvpc_energy']}")
    return True

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
        total_consumptions, total_prices = load_energy_data(ENERGY_FILE)
        consumptions_len = len(total_consumptions)
        prices_len = len(total_prices)
        consumptions = await UFD.consumptions(start_date, end_date, total_consumptions, hass)
        prices = await REE.pvpc(start_date, end_date, total_prices, hass)
        if len(total_consumptions) > consumptions_len or len(total_prices) > prices_len:
            save_energy_data(ENERGY_FILE, total_consumptions, total_prices)

        _LOGGER.info(f"len(consumptions)={len(consumptions)}")
        if len(consumptions) > 0:
            start_date = max(start_date, datetime.datetime.fromtimestamp(min(list(consumptions.keys()))).date())
            consumption_statistics, cost_statistics = create_statistics(consumptions, prices, total_energy_consumption, total_energy_cost)
    
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
            await calculate_bills(total_consumptions, hass)
    if not hass.states.get(CURRENT_BILL_STATE):
        if len(total_consumptions) == 0:
            total_consumptions, total_prices = load_energy_data(ENERGY_FILE)
        await calculate_bills(total_consumptions, hass)

    _LOGGER.debug(f"END - import_energy_data")

async def calculate_bills(consumptions, hass):
    _LOGGER.debug(f"START - calculate_bills(len(consumptions)={len(consumptions)})")

    if len(consumptions) > 0:
        periods_start_date = datetime.date.fromtimestamp(min(consumptions.keys()))
        periods_end_date = datetime.date.today()
        billing_periods = load_billing_periods(BILLING_PERIODS_FILE)
        if len(billing_periods) > 0:
            periods_start_date = billing_periods[-1]['end_date']
        _LOGGER.info(f"periods_start_date={periods_start_date.isoformat()}, periods_end_date={periods_end_date.isoformat()}, (periods_end_date - periods_start_date).days={(periods_end_date - periods_start_date).days}")
        if (periods_end_date - periods_start_date).days > 25:
            new_billing_periods = await UFD.billingPeriods(periods_start_date, periods_end_date, hass)
            if len(new_billing_periods) > 0:
                billing_periods += new_billing_periods
                save_billing_periods(BILLING_PERIODS_FILE, billing_periods)

        update = False
        for billing_period in reversed(billing_periods):
            if 'total_consumption' not in billing_period:
                billing_period = await get_bill(billing_period, consumptions, hass)
                if 'total_consumption' in billing_period:
                    update = True
        if update:
            save_billing_periods(BILLING_PERIODS_FILE, billing_periods)

        current_billing_period = {'start_date': billing_periods[-1]['end_date'] + datetime.timedelta(days=1), 'end_date':datetime.date.today()}
        current_billing_period = await get_bill(current_billing_period, consumptions, hass)

        current_bill_value = ''
        bills_description = ''
        if 'total_cost' in current_billing_period:
            billing_periods.append(current_billing_period)

            days = (current_billing_period['end_date'] - current_billing_period['start_date']).days + 1
            estimation_days = 30
            estimation_end_date = current_billing_period['start_date'] + datetime.timedelta(days=estimation_days)
            cost = round(current_billing_period['total_cost'] / days * estimation_days, 2)
            current_bill_value = '%.2f' % current_billing_period['total_cost']
            bills_description += f"Estimación {current_billing_period['start_date'].strftime('%d/%m')} - {estimation_end_date.strftime('%d/%m')} ({estimation_days} días): **{cost} €**\n\n"
            
        bills_description += '| Fecha | Días | Importe | kWh | cent/kWh | €/día | kWh/día |\n'
        bills_description += '| :---: | :---: | :---: | :---: | :---: | :---: | :---: |'
        for billing_period in reversed(billing_periods[-UFD.bills_number:]):
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

async def get_bill(billing_period, consumptions, hass):
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

    bill = await CNMC.calculate_bill(UFD.cups, bill_consumptions, UFD.power_high, UFD.power_low, UFD.zip_code, hass)
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

def post(url, headers, payload):
    return requests.post(url, headers=headers, json=payload)

def get(url, headers):
    return requests.get(url, headers=headers)


class REE:
    token = "20dada670614470c2f0cd1ff9042018bbedd5ab3796b1f96fd56d0dc209f4480"
    url_indicators = "https://api.esios.ree.es/indicators/1001?geo_ids[]=8741&start_date={start_date}&end_date={end_date}"

    def getHeaders():
        headers = {
            'Accept': 'application/json; application/vnd.esios-api-v2+json',
            'Content-Type': 'application/json',
            'Host': 'api.esios.ree.es',
            'x-api-key': REE.token
        }
        return headers

    async def pvpc(start_date, end_date, prices, hass):
        _LOGGER.debug(f"START - REE.pvpc(start_date={start_date.isoformat()}, end_date={end_date.isoformat()}, len(prices)={len(prices)})")
        timestamps = prices.keys()
        if start_date == None: start_date = datetime.date.min

        result = {}
        start_timestamp = 0 if start_date == datetime.date.min else int(time.mktime(start_date.timetuple()))
        end_timestamp = int(time.mktime(datetime.datetime(end_date.year, end_date.month, end_date.day, 23).timetuple()))
        for timestamp, value in prices.items():
            if start_timestamp <= timestamp <= end_timestamp:
                result[timestamp] = value

        request_end_date = end_date + datetime.timedelta(days=1)
        while request_end_date > start_date:
            request_start_date = request_end_date - datetime.timedelta(days=1)
            while int(time.mktime(request_start_date.timetuple())) in timestamps and request_start_date >= start_date:
                request_start_date -= datetime.timedelta(days=1)
            if request_start_date < start_date: break
            request_end_date = request_start_date - datetime.timedelta(days=1)
            while int(time.mktime(request_end_date.timetuple())) not in timestamps and request_end_date >= start_date and (request_start_date - request_end_date).days < 28:
                request_end_date -= datetime.timedelta(days=1)
            request_end_date += datetime.timedelta(days=1)
            
            url = REE.url_indicators.format(start_date=request_end_date.strftime('%Y-%m-%d'), end_date=request_start_date.strftime('%Y-%m-%dT23%%3A00%%3A00'))
            response = None
            _LOGGER.info(f"REE.get_prices(start_date={request_end_date.isoformat()}, end_date={request_start_date.isoformat()})")
            r = await hass.async_add_executor_job(get, url, REE.getHeaders())
            if r.status_code == 200:
                response = r.json()
            if response is not None and len(response['indicator']['values']) > 0:
                for value in response['indicator']['values']:
                    timestamp = int(time.mktime(time.strptime(value['datetime'][:13], '%Y-%m-%dT%H')))
                    prices[timestamp] = round(value['value'] / 1000, 5)
                    result[timestamp] = prices[timestamp]
            else:
                break
        _LOGGER.debug(f"END - REE.pvpc: len(result)={len(result)}")
        return result


class UFD:
    Appclientid = "1f3n1frmnqn14arndr3507lnok"
    AppClient = "ACUFDW"
    Application = "ACUFD"
    Appversion = "1.0.0.0"
    AppClientSecret = "102sml3ajvkdjakoh2rhgrfpvjogl4b0or5nqmcmilvt2odpu9ce"
    User = None
    Password = None
    userId = '0'
    sequence = -1
    rand = ''
    token = ''
    nif = ''
    cups = ''
    power_high = 0
    power_low = 0
    zip_code = ''
    bills_number = 5
    login_url = "https://api.ufd.es/ufd/v1.0/login"
    supplypoints_url = "https://api.ufd.es/ufd/v1.0/supplypoints?filter=documentNumber::{nif}"
    billingPeriods_url = "https://api.ufd.es/ufd/v1.0/billingPeriods?filter=cups::{cups}%7CstartDate::{start_date}%7CendDate::{end_date}"
    consumptions_url = "https://api.ufd.es/ufd/v1.0/consumptions?filter=nif::{nif}%7Ccups::{cups}%7CstartDate::{start_date}%7CendDate::{end_date}%7Cgranularity::H%7Cunit::K%7Cgenerator::0%7CisDelegate::N%7CisSelfConsumption::0%7CmeasurementSystem::O"

    def getMessageId():
        if UFD.rand == '':
            randChars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
            for x in range(15):
                UFD.rand = UFD.rand + randChars[random.randint(0, len(randChars) - 1)]
        UFD.sequence += 1
        return f"{UFD.userId}/{UFD.rand}/{UFD.sequence}"

    async def getHeaders(hass):
        headers = {
            'X-Application': UFD.Application,
            'X-Appclientid': UFD.Appclientid,
            'X-MessageId': UFD.getMessageId(),
            'X-AppClientSecret': UFD.AppClientSecret,
            'X-AppClient': UFD.AppClient,
            'X-Appversion': UFD.Appversion,
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.141 Mobile Safari/537.36'
        }
        if UFD.token == '':
            payload = {'user': UFD.User, 'password': UFD.Password}
            response = (await hass.async_add_executor_job(post, UFD.login_url, headers, payload)).json()
            UFD.userId = response['user']['userId']
            UFD.token = response['accessToken']
            UFD.nif = response['user']['documentNumber']
            headers['Authorization'] = f"Bearer {UFD.token}"
            headers['X-MessageId'] = UFD.getMessageId()
            _LOGGER.info(f"UFD.getHeaders: headers={headers}")
        else:
            headers['Authorization'] = f"Bearer {UFD.token}"
        return headers
    
    async def consumptions(start_date, end_date, consumptions, hass):
        _LOGGER.debug(f"START - UFD.consumptions(start_date={start_date.isoformat()}, end_date={end_date.isoformat()}, len(consumptions)={len(consumptions)})")
        timestamps = consumptions.keys()
        if start_date == None: start_date = datetime.date.min

        result = {}
        start_timestamp = 0 if start_date == datetime.date.min else int(time.mktime(start_date.timetuple()))
        end_timestamp = int(time.mktime(datetime.datetime(end_date.year, end_date.month, end_date.day, 23).timetuple()))
        for timestamp, value in consumptions.items():
            if start_timestamp <= timestamp <= end_timestamp:
                result[timestamp] = value

        request_end_date = end_date + datetime.timedelta(days=1)
        while request_end_date > start_date:
            request_start_date = request_end_date - datetime.timedelta(days=1)
            while int(time.mktime(request_start_date.timetuple())) in timestamps and request_start_date >= start_date:
                request_start_date -= datetime.timedelta(days=1)
            if request_start_date < start_date: break
            request_end_date = request_start_date - datetime.timedelta(days=1)
            while int(time.mktime(request_end_date.timetuple())) not in timestamps and request_end_date >= start_date and (request_start_date - request_end_date).days < 14:
                request_end_date -= datetime.timedelta(days=1)
            request_end_date += datetime.timedelta(days=1)
            
            headers = await UFD.getHeaders(hass)
            url = UFD.consumptions_url.format(nif=UFD.nif, cups=UFD.cups, start_date=request_end_date.strftime('%d/%m/%Y'), end_date=request_start_date.strftime('%d/%m/%Y'))
            response = None
            _LOGGER.info(f"UFD.get_consumptions(start_date={request_end_date.isoformat()}, end_date={request_start_date.isoformat()})")
            r = await hass.async_add_executor_job(get, url, headers)
            if r.status_code == 200:
                response = r.json()
            if response is not None and 'items' in response:
                for dayConsumption in response['items']:
                    timestamp = int(time.mktime(time.strptime(dayConsumption['periodStartDate'], '%d/%m/%Y')))
                    for hourConsumption in dayConsumption['consumptions']['items']:
                        consumptions[timestamp] = float(hourConsumption['consumptionValue'].replace(',','.'))
                        result[timestamp] = consumptions[timestamp]
                        timestamp += 3600
            else:
                break
        _LOGGER.debug(f"END - UFD.consumptions: len(result)={len(result)}")
        return result

    async def billingPeriods(start_date, end_date, hass):
        _LOGGER.debug(f"START - UFD.billingPeriods(start_date={start_date.isoformat()}, end_date={end_date.isoformat()})")
        result = []
        url = UFD.billingPeriods_url.format(cups=UFD.cups, start_date=start_date.strftime('%d/%m/%Y'), end_date=end_date.strftime('%d/%m/%Y'))
        headers = await UFD.getHeaders(hass)
        r = await hass.async_add_executor_job(get, url, headers)
        if r.status_code == 200:
            response = r.json()
            for billing_period in response['billingPeriods']['items']:
                period_start_date = datetime.date.fromisoformat(billing_period['periodStartDate'])
                period_end_date = datetime.date.fromisoformat(billing_period['periodEndDate'])
                result.append({'start_date': period_start_date, 'end_date': period_end_date})
        _LOGGER.debug(f"END - UFD.billingPeriods: len(result)={len(result)}")
        return result

    async def supplypoints(hass):
        _LOGGER.debug(f"START - UFD.supplypoints()")
        headers = await UFD.getHeaders(hass)
        url = UFD.supplypoints_url.format(nif=UFD.nif)
        r = await hass.async_add_executor_job(url, headers)
        if r.status_code == 200:
            response = r.json()
            UFD.cups = response['supplyPoints']['items'][0]['cups']
            UFD.power_high = float(response['supplyPoints']['items'][0]['power1'])
            UFD.power_low = float(response['supplyPoints']['items'][0]['power2'])
            _LOGGER.debug(f"cups={UFD.cups}, power_high={UFD.power_high}, power_low={UFD.power_low}")
        _LOGGER.debug(f"END - UFD.supplypoints()")

class CNMC:
    upload_file_url = "https://comparador.cnmc.gob.es/api/facturaluz/cargar/curvaConsumo"
    calculate_bill_url = "https://comparador.cnmc.gob.es/api/ofertas/pvpc?tipoContador=I&codigoPostal={zip_code}&bonoSocial=false&tipoConsumidor=1&categoria=1&contador=1&potenciaPrimeraFranja={power_high}&potenciaSegundaFranja={power_low}&curvaConsumo={energy_file}&vivienda=false&tarifa=4&calculoAntiguo=false&forzarCalculoNuevo=false"

    def getHeaders():
        headers = {
            'Content-Type': 'application/json'
        }
        return headers
    
    async def calculate_bill(cups, consumptions, power_high, power_low, zip_code, hass):
        _LOGGER.debug(f"START - CNMC.calculate_bill(cups={cups}, len(consumptions)={len(consumptions)}, power_high={power_high}, power_low={power_low}, zip_code={zip_code})")
        cnmc_consumptions = "CUPS;Fecha;Hora;Consumo;Metodo_obtencion\r\n"
        timestamps = list(consumptions.keys())
        timestamps.sort()
        for timestamp in timestamps:
            date = datetime.datetime.fromtimestamp(timestamp)
            cnmc_consumptions += f"{cups};{date.strftime('%d/%m/%Y')};{date.hour + 1};{('%.3f' % consumptions[timestamp]).replace('.',',')};R\r\n"
        encoded = base64.b64encode(bytes(cnmc_consumptions, 'utf-8')).decode('utf-8')

        payload = {'file': f"data:text/csv;base64,77u/{encoded}"}
        response = await hass.async_add_executor_job(post, CNMC.upload_file_url, CNMC.getHeaders(), payload)
        energy_file = response.text[0:-8]

        # payload = {'file': energy_file}
        # response = await requests.post(CNMC.upload_file_url, json=payload)

        url = CNMC.calculate_bill_url.format(zip_code=zip_code, power_high=str(power_high), power_low=str(power_low), energy_file=energy_file)
        result = (await hass.async_add_executor_job(get, url, None)).json()
        if 'graficoGastoTotalActual' in result:
            _LOGGER.debug(f"END - CNMC.calculate_bill: result={result['graficoGastoTotalActual']}")
        else:
            _LOGGER.debug(f"END - CNMC.calculate_bill: result={result}")
        return result
    
