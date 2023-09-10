import datetime
import time
import requests
import random
import logging
import json

_LOGGER = logging.getLogger(__name__)


def post(url, headers, payload):
    return requests.post(url, headers=headers, json=payload)

def get(url, headers):
    return requests.get(url, headers=headers)

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
    zip_code = None
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
            r = await hass.async_add_executor_job(post, UFD.login_url, headers, payload)
            _LOGGER.debug(f"status_code: {r.status_code}, response: {r.text}")
            response = None
            if r.status_code == 200:    
                response = r.json()
            else:
                _LOGGER.error(f"status_code: {r.status_code}, response: {r.text}")
            if response is not None:
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
            if r.status_code == 401:
                _LOGGER.debug(f"Unauthorized: {r.status_code}")
                UFD.token = ''
                headers=UFD.getHeaders()
                r = requests.get(url, headers=headers)
            if r.status_code == 200:
                response = r.json()
            else:
                _LOGGER.error(f"status_code: {r.status_code}, response: {r.text}")
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
        r = await hass.async_add_executor_job(get, url, headers)
        if r.status_code == 200:
            response = r.json()
            _LOGGER.debug(f"response={response}")
            UFD.cups = response['supplyPoints']['items'][0]['cups']
            UFD.power_high = float(response['supplyPoints']['items'][0]['power1'])
            UFD.power_low = float(response['supplyPoints']['items'][0]['power2'])
            UFD.zip_code = response['supplyPoints']['items'][0]['address']['zipCode']
            _LOGGER.debug(f"cups={UFD.cups}, power_high={UFD.power_high}, power_low={UFD.power_low}")
        _LOGGER.debug(f"END - UFD.supplypoints()")
    