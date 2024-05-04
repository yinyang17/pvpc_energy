import datetime
import aiohttp
import base64
import logging
import re


_LOGGER = logging.getLogger(__name__)

class CNMC:
    OLD_FILE = 'Aviso: El fichero de consumo introducido es demasiado antiguo. Por favor, introduzca un fichero cuya fecha inicial sea igual o posterior al uno de enero de hace dos años'
    NO_DATA = 'Aviso: No hay datos para el período de facturación'
    BAD_FILE = 'Aviso: El formato del fichero de consumo no es el correcto'
    upload_file_url = "https://comparador.cnmc.gob.es/api/facturaluz/cargar/curvaConsumo"
    calculate_bill_url = "https://comparador.cnmc.gob.es/api/ofertas/pvpc?tipoContador=I&codigoPostal={zip_code}&bonoSocial=false&tipoConsumidor=1&categoria=1&contador=1&potenciaPrimeraFranja={power_high}&potenciaSegundaFranja={power_low}&curvaConsumo={energy_file}&vivienda=false&tarifa=4&calculoAntiguo=false&forzarCalculoNuevo=false"

    def getHeaders():
        headers = {
            'Content-Type': 'application/json'
        }
        return headers
    
    async def calculate_bill(billing_period, cups, consumptions, power_high, power_low, zip_code):
        _LOGGER.debug(f"START - CNMC.calculate_bill(cups={cups}, len(consumptions)={len(consumptions)}, power_high={power_high}, power_low={power_low}, zip_code={zip_code})")
        timestamps = list(consumptions.keys())
        timestamps.sort()
        if len(consumptions) > 24 and billing_period['start_date'] == datetime.datetime.fromtimestamp(timestamps[0]).date() and billing_period['end_date'] == datetime.datetime.fromtimestamp(timestamps[-1]).date():
            correlative_timestamps = True
            for i in range(1, len(timestamps)):
                if timestamps[i-1] + 3600 != timestamps[i]:
                    _LOGGER.info(f"CNMC.calculate_bill: NOT_CORRELATIVE_TIMESTAMPS ({timestamps[i-1]} - {timestamps[i]:})")
                    correlative_timestamps = False
                    break
            if correlative_timestamps:
                total_consumption = 0.0
                cnmc_consumptions = "CUPS;Fecha;Hora;Consumo;Metodo_obtencion\r\n"
                for timestamp in timestamps:
                    date = datetime.datetime.fromtimestamp(timestamp)
                    total_consumption += consumptions[timestamp]
                    cnmc_consumptions += f"{cups};{date.strftime('%d/%m/%Y')};{date.hour + 1};{('%.3f' % consumptions[timestamp]).replace('.',',')};R\r\n"
                encoded = base64.b64encode(bytes(cnmc_consumptions, 'utf-8')).decode('utf-8')
                billing_period['total_consumption'] = total_consumption

                async with aiohttp.ClientSession() as session:
                    energy_file = None
                    payload = {'file': f"data:text/csv;base64,77u/{encoded}"}
                    async with session.post(CNMC.upload_file_url, headers=CNMC.getHeaders(), json=payload, ssl=False) as resp:
                        response = await resp.text()
                        if response == CNMC.OLD_FILE:
                            billing_period['total_cost'] = '-'
                        elif response == CNMC.NO_DATA:
                            _LOGGER.info(f"CNMC.calculate_bill: NO_DATA")
                        elif response.startswith(CNMC.BAD_FILE):
                            _LOGGER.info(f"CNMC.calculate_bill: BAD_FILE, alert={response}")
                        elif response.startswith('Aviso:'):
                            _LOGGER.info(f"CNMC.calculate_bill: alert={response}")
                        else:
                            name_search = re.search(r'^(\D+\d+)-.*$', response)
                            if name_search:
                                energy_file = name_search.group(1)

                    # payload = {'file': energy_file}
                    # response = await requests.post(CNMC.upload_file_url, json=payload)
                            
                    if energy_file:
                        url = CNMC.calculate_bill_url.format(zip_code=zip_code, power_high=str(power_high), power_low=str(power_low), energy_file=energy_file)
                        async with session.get(url, ssl=False) as resp:
                            bill = await resp.json()
                            if 'graficoGastoTotalActual' in bill:
                                billing_period['start_date'] = datetime.datetime.strptime(bill['graficaConsumoDiario']['consumosDiarios'][0]['fecha'], '%d/%m/%Y').date()
                                billing_period['end_date'] = datetime.datetime.strptime(bill['graficaConsumoDiario']['consumosDiarios'][-1]['fecha'], '%d/%m/%Y').date()
                                billing_period['total_cost'] = bill['graficoGastoTotalActual']['importeTotal']
                                billing_period['power_cost'] = bill['graficoGastoTotalActual']['importePotencia']
                                billing_period['energy_cost'] = bill['graficoGastoTotalActual']['importeEnergia']
                                billing_period['rent_cost'] = bill['graficoGastoTotalActual']['importeAlquiler']
                                billing_period['tax_cost'] = bill['graficoGastoTotalActual']['importeIVA']
                                _LOGGER.debug(f"END - CNMC.calculate_bill: result={bill['graficoGastoTotalActual']}")
                            else:
                                _LOGGER.debug(f"END - CNMC.calculate_bill: result={bill}")
        return billing_period
    
