import datetime
import time
import requests
import logging

_LOGGER = logging.getLogger(__name__)


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