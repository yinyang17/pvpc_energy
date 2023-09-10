import datetime
import requests
import base64
import logging


_LOGGER = logging.getLogger(__name__)

def post(url, headers, payload):
    return requests.post(url, headers=headers, json=payload)

def get(url, headers):
    return requests.get(url, headers=headers)

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
    
