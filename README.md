# pvpc_energy
Imports electric consumption and cost from ufd.es and ree.es. Calculate current and past bills from cnmc.gob.es

## Instalation and configuration
You need to be registered on https://www.ufd.es.
After restart add the following configuration to configuration.yaml, indicating UFD data:
```yaml
pvpc_energy:
  ufd_login: ''
  ufd_password: ''
  cups: ''
  zip_code: ''
  power_high: 4.6
  power_low: 4.6
  bills_number: 5
```

Restart again to activate the integration. When Home Assistant starts the integration gets available data from:
* https://www.ufd.es: Electricity consumptions and billings periods
* https://api.esios.ree.es: Hourly energy prices
* https://comparador.cnmc.gob.es/facturaluz/inicio: PVPC bills simulation


## Output
It takes a few minutes the fetch available data (about two years). After this time you will have:
* Statistics
    * pvpc_energy:consumption (PVPC: Consumo): Hourly electricity consumption
    * pvpc_energy:cost (PVPC: Coste): Hourly electricity costs
* States
    * pvpc_energy.current_bill: Cost of the current bill. In the "detail" attribute it has a markdown with the last "bills_number" bills


## Panels
Add to Energy panel the electricity consumption "PVPC: Consumo" and entity with total costs "PVPC: Coste".
Add to Lovelace a Markdown card to show the last bills indicating in content:
```yml
{{ state_attr('pvpc_energy.current_bill', 'detail')}}
```
