import datetime
import time
import aiohttp
from aiohttp import ContentTypeError
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
    login_url = "https://api.ufd.es/ufd/v1.0/login"
    supplypoints_url = "https://api.ufd.es/ufd/v1.0/supplypoints?filter=documentNumber::{nif}"
    billingPeriods_url = "https://api.ufd.es/ufd/v1.0/billingPeriods?filter=cups::{cups}%7CstartDate::{start_date}%7CendDate::{end_date}"
    consumptions_url = "https://api.ufd.es/ufd/v1.0/consumptions?filter=nif::{nif}%7Ccups::{cups}%7CstartDate::{start_date}%7CendDate::{end_date}%7Cgranularity::H%7Cunit::K%7Cgenerator::0%7CisDelegate::N%7CisSelfConsumption::0%7CmeasurementSystem::O"

    NO_NEW_BILLS = "No existen facturas en el periodo"
    CAPTCHA_PROVIDERS = ("perfdrive.com", "shieldsquare.com")
    CAPTCHA_TEXT = (
        "Captcha Page",
        "Please solve this CAPTCHA",
        "made us think that you are a bot",
    )
    USER_AGENTS = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
    )
    USER_AGENT_MAX_REQUESTS = 12
    BACKOFF_BASE_SECONDS = 5 * 60
    BACKOFF_MAX_SECONDS = 24 * 60 * 60
    _session = None
    _user_agent = None
    _user_agent_requests = 0
    _blocked_until = None
    _block_attempts = 0
    _last_block_reason = None

    def rotateUserAgent():
        UFD._user_agent = random.choice(UFD.USER_AGENTS)
        UFD._user_agent_requests = 0
        return UFD._user_agent

    def getUserAgent():
        if UFD._user_agent is None or UFD._user_agent_requests >= UFD.USER_AGENT_MAX_REQUESTS:
            UFD.rotateUserAgent()
        UFD._user_agent_requests += 1
        return UFD._user_agent

    async def getSession():
        if UFD._session is None or UFD._session.closed:
            UFD._session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        return UFD._session

    async def closeSession():
        if UFD._session is not None and not UFD._session.closed:
            await UFD._session.close()
        UFD._session = None

    def getBackoffRemainingSeconds():
        if UFD._blocked_until is None:
            return 0
        return max(0, int((UFD._blocked_until - datetime.datetime.now()).total_seconds()))

    def isBackoffActive():
        return UFD.getBackoffRemainingSeconds() > 0

    def getBackoffStatus():
        remaining = UFD.getBackoffRemainingSeconds()
        if remaining == 0:
            return None
        retry_at = UFD._blocked_until.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"UFD bloqueado temporalmente por {UFD._last_block_reason}. "
            f"Siguiente intento a partir de {retry_at} ({remaining // 60} min restantes)."
        )

    def registerSuccessfulResponse():
        if UFD._block_attempts > 0:
            _LOGGER.info("UFD vuelve a responder correctamente; se reinicia el backoff.")
        UFD._blocked_until = None
        UFD._block_attempts = 0
        UFD._last_block_reason = None

    def registerBlockedResponse(reason):
        UFD.token = ''
        UFD.rotateUserAgent()
        UFD._block_attempts += 1
        raw_delay = min(
            UFD.BACKOFF_BASE_SECONDS * (2 ** (UFD._block_attempts - 1)),
            UFD.BACKOFF_MAX_SECONDS,
        )
        delay = min(int(raw_delay * random.uniform(0.85, 1.15)), UFD.BACKOFF_MAX_SECONDS)
        UFD._blocked_until = datetime.datetime.now() + datetime.timedelta(seconds=delay)
        UFD._last_block_reason = reason
        _LOGGER.warning(
            "UFD ha devuelto una pagina de bloqueo/CAPTCHA (%s). "
            "Se pausa la importacion durante %s minutos; siguiente intento a partir de %s. "
            "Nuevo User-Agent preparado para el proximo intento.",
            reason,
            max(1, delay // 60),
            UFD._blocked_until.strftime("%Y-%m-%d %H:%M:%S"),
        )
        if UFD._block_attempts >= 4:
            _LOGGER.warning(
                "UFD sigue bloqueando las peticiones tras %s intentos. "
                "Alternativas recomendadas: Datadis/API oficial, lectura directa del contador "
                "(Shelly, Tasmota o P1) o descarga manual periodica.",
                UFD._block_attempts,
            )

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
            'user-agent': UFD.getUserAgent(),

            'X-Application': UFD.Application,
            'X-Appclientid': UFD.Appclientid,
            'X-MessageId': UFD.getMessageId(),
            'X-AppClientSecret': UFD.AppClientSecret,
            'X-AppClient': UFD.AppClient,
            'X-Appversion': UFD.Appversion,
        }
        if UFD.token == '':
            if UFD.isBackoffActive():
                _LOGGER.info(UFD.getBackoffStatus())
                return None
            payload = {'user': UFD.User, 'password': UFD.Password}
            async with session.post(UFD.login_url, headers=headers, json=payload, ssl=False) as resp:
                response = await UFD.checkResponse(resp)
                if response is not None:
                    UFD.userId = response['user']['userId']
                    UFD.token = response['accessToken']
                    UFD.nif = response['user']['documentNumber']
                    headers['Authorization'] = f"Bearer {UFD.token}"
                    headers['X-MessageId'] = UFD.getMessageId()
                    _LOGGER.debug(f"UFD.getHeaders: headers={headers}")
        else:
            headers['Authorization'] = f"Bearer {UFD.token}"
        return headers
    
    async def getResponse(session, url, headers):
        if UFD.isBackoffActive():
            _LOGGER.info(UFD.getBackoffStatus())
            return None
        if headers is None:
            return None
        response = None
        async with session.get(url, headers=headers, ssl=False) as resp:
            if resp.status == 401:
                _LOGGER.debug(f"Unauthorized: {resp.status}")
                UFD.token = ''
                headers = await UFD.getHeaders(session)
                if headers is None:
                    return None
                async with session.get(url, headers=headers, ssl=False) as resp:
                    response = await UFD.checkResponse(resp)
            else:
                response = await UFD.checkResponse(resp)
        return response
    
    def isCaptchaResponse(resp, text=''):
        url = str(resp.url).lower()
        if any(provider in url for provider in UFD.CAPTCHA_PROVIDERS):
            return True
        return any(captcha_text.lower() in text.lower() for captcha_text in UFD.CAPTCHA_TEXT)

    async def checkResponse(resp):
        response = None
        text = None
        if resp.status == 200:
            try:
                response = await resp.json()
                UFD.registerSuccessfulResponse()
            except ContentTypeError:
                text = await resp.text()
                if UFD.isCaptchaResponse(resp, text):
                    UFD.registerBlockedResponse("respuesta HTML con CAPTCHA")
                else:
                    _LOGGER.error(
                        "UFD returned status 200 with unexpected content type: %s",
                        resp.headers.get("Content-Type", "unknown"),
                    )
        else:
            text = await resp.text()
            if UFD.NO_NEW_BILLS in text:
                _LOGGER.debug(f"UFD.billingPeriods: NO_NEW_BILLS")
            elif UFD.isCaptchaResponse(resp, text):
                UFD.registerBlockedResponse(f"HTTP {resp.status} con CAPTCHA")
            else:
                _LOGGER.error(f"status_code: {resp.status}, response: {text}")
        return response
    
    async def consumptions(start_date, end_date):
        _LOGGER.debug(f"START - UFD.consumptions(start_date={start_date.isoformat()}, end_date={end_date.isoformat()})")

        result = None
        session = await UFD.getSession()
        headers = await UFD.getHeaders(session)
        url = UFD.consumptions_url.format(nif=UFD.nif, cups=UFD.cups, start_date=start_date.strftime('%d/%m/%Y'),
                                          end_date=end_date.strftime('%d/%m/%Y'))
        _LOGGER.info(f"UFD.get_consumptions(start_date={start_date.isoformat()}, end_date={end_date.isoformat()})")
        response = await UFD.getResponse(session, url, headers)
        if response is not None:
            result = {}
            if 'items' in response:
                for dayConsumption in response['items']:
                    if len(dayConsumption['consumptions']['items']) >= 23:
                        # El formato de las fechas varia entre:
                        #   "periodStartDate": "2025-12-03T00:00:00.000+01:00",
                        #   "hour": "1",
                        #   "consumptionDate": "2025-12-03T00:00:00.000+01:00",
                        # y
                        #   "periodStartDate": "03/12/2025",
                        #   "hour": "1",
                        #   "consumptionDate": "03/12/2025",
                        if len(dayConsumption['periodStartDate']) == 10:
                            if start_date <= datetime.datetime.strptime(dayConsumption['periodStartDate'], '%d/%m/%Y').date() <= end_date:
                                for hourConsumption in dayConsumption['consumptions']['items']:
                                    hour = int(hourConsumption['hour'])
                                    if len(dayConsumption['consumptions']['items']) == 23 and hour == 3:
                                        # Si se adelanta la hora, la hora 3 de la respuesta es el consumo de de 1 a 2
                                        hour = 2
                                    result[int(time.mktime(time.strptime(f"{dayConsumption['periodStartDate']} {(hour - 1):02}", '%d/%m/%Y %H')))] = {
                                        'value': float(hourConsumption['consumptionValue'].replace(',','.')),
                                        'reading_type': hourConsumption['readingType']
                                    }
                        else:
                            if start_date <= datetime.datetime.fromisoformat(dayConsumption['periodStartDate']).date() <= end_date:
                                for hourConsumption in dayConsumption['consumptions']['items']:
                                    result[int(datetime.datetime.fromisoformat(hourConsumption['consumptionDate']).timestamp())] = {
                                       'value': float(hourConsumption['consumptionValue'].replace(',','.')),
                                       'reading_type': hourConsumption['readingType']
                                    }

        _LOGGER.debug(f"END - UFD.consumptions: len(result)={'None' if result is None else len(result)}")
        return result
    
    async def billingPeriods(start_date, end_date):
        _LOGGER.debug(f"START - UFD.billingPeriods(start_date={start_date.isoformat()}, end_date={end_date.isoformat()})")
        result = []
        session = await UFD.getSession()
        url = UFD.billingPeriods_url.format(cups=UFD.cups, start_date=start_date.strftime('%d/%m/%Y'), end_date=end_date.strftime('%d/%m/%Y'))
        try:
            headers = await UFD.getHeaders(session)
            response = await UFD.getResponse(session, url, headers)
            if response is not None:
                for billing_period in response['billingPeriods']['items']:
                    period_start_date = datetime.date.fromisoformat(billing_period['periodStartDate'])
                    period_end_date = datetime.date.fromisoformat(billing_period['periodEndDate'])
                    if UFD.power_high == 0 and UFD.power_low == 0:
                        await UFD.supplyPointPowers(UFD.cups)
                    result.append({'start_date': period_start_date, 'end_date': period_end_date, 'power_high': UFD.power_high, 'power_low': UFD.power_low})                        
        except Exception:
            _LOGGER.exception("Error obteniendo periodos de facturacion de UFD")
        _LOGGER.debug(f"END - UFD.billingPeriods: len(result)={len(result)}")
        return result

    async def supplyPoints():
        _LOGGER.debug(f"START - UFD.supplypoints()")
        result = {}
        session = await UFD.getSession()
        headers = await UFD.getHeaders(session)
        url = UFD.supplypoints_url.format(nif=UFD.nif)
        response = await UFD.getResponse(session, url, headers)
        if response is not None:
            _LOGGER.debug(f"response={response}")
            for supplyPoint in response['supplyPoints']['items']:
                if supplyPoint['power1'] != '' and supplyPoint['power1'] != '':
                    result[supplyPoint['cups']] = {
                        'cups': supplyPoint['cups'],
                        'power_high': float(supplyPoint['power1']),
                        'power_low': float(supplyPoint['power2']),
                        'zip_code': supplyPoint['address']['zipCode'],
                        'contract_start_date': supplyPoint['contractStartDate']
                    }
                    _LOGGER.debug(f"cups={supplyPoint['cups']}, power_high={float(supplyPoint['power1'])}, power_low={float(supplyPoint['power2'])}, contract_start_date={supplyPoint['contractStartDate']}")
        _LOGGER.debug(f"END - UFD.supplypoints()")
        return result

    async def supplyPointPowers(cups):
        _LOGGER.debug(f"START - UFD.supplyPointPowers(cups={cups})")
        if UFD.power_high == 0 and UFD.power_high == 0:
            supplyPoints = await UFD.supplyPoints()
            if cups in supplyPoints.keys():
                UFD.power_high = supplyPoints[cups]['power_high']
                UFD.power_low = supplyPoints[cups]['power_low']
        _LOGGER.debug(f"END - UFD.supplyPointPowers: UFD.power_high={UFD.power_high}, UFD.power_low={UFD.power_low}")
        return UFD.power_high, UFD.power_low
