import datetime
import time
import aiohttp
import random
import logging


_LOGGER = logging.getLogger(__name__)

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

    async def getHeaders(session):
        headers = {
            'authority': 'api.ufd.es',
            'accept': '*/*',
            'accept-language': 'es-ES,es;q=0.5',
            'access-control-allow-headers': 'Origin, X-Requested-With, Content-Type, Accept',
            'access-control-allow-origin': '*',
            'cache-control': 'no-cache',
            'content-encoding': 'gzip',
            'content-type': 'application/json',
            'origin': 'https://areaprivada.ufd.es',
            'pragma': 'no-cache',
            'referer': 'https://areaprivada.ufd.es/',
            'sec-ch-ua': '"Not A(Brand";v="99", "Brave";v="121", "Chromium";v="121"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'sec-gpc': '1',
            'user-agent': 'Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36',

            'X-Application': UFD.Application,
            'X-Appclientid': UFD.Appclientid,
            'X-MessageId': UFD.getMessageId(),
            'X-AppClientSecret': UFD.AppClientSecret,
            'X-AppClient': UFD.AppClient,
            'X-Appversion': UFD.Appversion,
        }
        if UFD.token == '':
            payload = {'user': UFD.User, 'password': UFD.Password}
            async with session.post(UFD.login_url, headers=headers, json=payload, ssl=False) as resp:
                response = None
                if resp.status == 200:
                    response = await resp.json()
                else:
                    text = await resp.text()
                    _LOGGER.error(f"status_code: {resp.status}, response: {text}")
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
    
    async def consumptions(start_date, end_date):
        # Hay un error en la web de UFD. Al solicitar los consumos desplaza el rango un día hacia atrás
        # y del primer día (que no se solicita) devuelve solo el consumo de las 24:00.
        # Solución: Sumamos un día a end_date y descartamos los días que no tengan 24 consumos y
        # no estén en el periodo solicitado, para que también funcione correctamente cuando se solucione la web.

        _LOGGER.debug(f"START - UFD.consumptions(start_date={start_date.isoformat()}, end_date={end_date.isoformat()})")

        result = None
        async with aiohttp.ClientSession() as session:
            headers = await UFD.getHeaders(session)
           # Fix UFD: Sumamos un día a end_date 
            url = UFD.consumptions_url.format(nif=UFD.nif, cups=UFD.cups, start_date=start_date.strftime('%d/%m/%Y'),
                                              end_date=(end_date + datetime.timedelta(days=1)).strftime('%d/%m/%Y'))
            response = None
            _LOGGER.info(f"UFD.get_consumptions(start_date={start_date.isoformat()}, end_date={end_date.isoformat()})")
            async with session.get(url, headers=headers, ssl=False) as resp:
                if resp.status == 401:
                    _LOGGER.debug(f"Unauthorized: {resp.status}")
                    UFD.token = ''
                    headers = await UFD.getHeaders(session)
                    async with session.get(url, headers=headers, ssl=False) as resp:
                        if resp.status == 200:
                            response = await resp.json()    
                        else:
                            text = await resp.text()
                            _LOGGER.error(f"status_code: {resp.status}, response: {text}")
                elif resp.status == 200:
                    response = await resp.json()    
                else:
                    text = await resp.text()
                    _LOGGER.error(f"status_code: {resp.status}, response: {text}")
            if response is not None:
                result = {}
                if 'items' in response:
                    for dayConsumption in response['items']:
                        if len(dayConsumption['consumptions']['items']) >= 23:
                            if start_date <= datetime.datetime.strptime(dayConsumption['periodStartDate'], '%d/%m/%Y').date() <= end_date:
                                timestamp = int(time.mktime(time.strptime(dayConsumption['periodStartDate'], '%d/%m/%Y')))
                                for hourConsumption in dayConsumption['consumptions']['items']:
                                    result[timestamp] = float(hourConsumption['consumptionValue'].replace(',','.'))
                                    timestamp += 3600

        _LOGGER.debug(f"END - UFD.consumptions: len(result)={'None' if result is None else len(result)}")
        return result
    
    async def billingPeriods(start_date, end_date):
        _LOGGER.debug(f"START - UFD.billingPeriods(start_date={start_date.isoformat()}, end_date={end_date.isoformat()})")
        result = []
        async with aiohttp.ClientSession() as session:
            url = UFD.billingPeriods_url.format(cups=UFD.cups, start_date=start_date.strftime('%d/%m/%Y'), end_date=end_date.strftime('%d/%m/%Y'))
            try:
                headers = await UFD.getHeaders(session)
                async with session.get(url, headers=headers, ssl=False) as resp:
                    if resp.status == 200:
                        response = await resp.json()
                        for billing_period in response['billingPeriods']['items']:
                            period_start_date = datetime.date.fromisoformat(billing_period['periodStartDate'])
                            period_end_date = datetime.date.fromisoformat(billing_period['periodEndDate'])
                            result.append({'start_date': period_start_date, 'end_date': period_end_date})
            except:
                pass
        _LOGGER.debug(f"END - UFD.billingPeriods: len(result)={len(result)}")
        return result

    async def supplypoints():
        _LOGGER.debug(f"START - UFD.supplypoints()")
        async with aiohttp.ClientSession() as session:
            headers = await UFD.getHeaders(session)
            url = UFD.supplypoints_url.format(nif=UFD.nif)
            async with session.get(url, headers=headers, ssl=False) as resp:
                if resp.status == 200:
                    response = await resp.json()
                    _LOGGER.debug(f"response={response}")
                    UFD.cups = response['supplyPoints']['items'][0]['cups']
                    UFD.power_high = float(response['supplyPoints']['items'][0]['power1'])
                    UFD.power_low = float(response['supplyPoints']['items'][0]['power2'])
                    UFD.zip_code = response['supplyPoints']['items'][0]['address']['zipCode']
                    _LOGGER.debug(f"cups={UFD.cups}, power_high={UFD.power_high}, power_low={UFD.power_low}")
        _LOGGER.debug(f"END - UFD.supplypoints()")
    