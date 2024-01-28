import datetime
import aiohttp
import logging


_LOGGER = logging.getLogger(__name__)

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

    async def pvpc(start_date, end_date):
        _LOGGER.debug(f"START - REE.pvpc(start_date={start_date.isoformat()}, end_date={end_date.isoformat()})")
        
        result = None
        url = REE.url_indicators.format(start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%dT23%%3A00%%3A00'))
        response = None
        _LOGGER.info(f"REE.get_prices(start_date={start_date.isoformat()}, end_date={end_date.isoformat()})")
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=REE.getHeaders(), ssl=False) as resp:
                if resp.status == 200:
                    response = await resp.json()
                if response is not None:
                    if len(response['indicator']['values']) > 0:
                        result = {}
                        for value in response['indicator']['values']:
                            result[int(datetime.datetime.fromisoformat(value['datetime']).timestamp())] = round(value['value'] / 1000, 5)

        _LOGGER.debug(f"END - REE.pvpc: len(result)={'None' if result is None else len(result)}")
        return result
