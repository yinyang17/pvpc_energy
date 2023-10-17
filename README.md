# pvpc_energy
![UFD logo](https://github.com/yinyang17/pvpc_energy/raw/main/assets/logo-ufd.png) ![ESIOS logo](https://github.com/yinyang17/pvpc_energy/raw/main/assets/logo-esios.png) ![CNMC logo](https://github.com/yinyang17/pvpc_energy/raw/main/assets/logo-cnmc.png)
Imports electric consumption and cost from ufd.es and ree.es. Calculate current and past bills from cnmc.gob.es

![Daily consumption](https://github.com/yinyang17/pvpc_energy/raw/main/assets/energy-daily.png)![Monthly consumption](https://github.com/yinyang17/pvpc_energy/raw/main/assets/energy-monthly.png)
![Bills](https://github.com/yinyang17/pvpc_energy/raw/main/assets/bills.png)

## Installation and configuration
You need to be registered on https://www.ufd.es.
After restart add integration indicating UFD credentials and number of bills to show in the Markdown Card.
![Config credentials](https://github.com/yinyang17/pvpc_energy/raw/main/assets/config-credentials.png)![Config bills](https://github.com/yinyang17/pvpc_energy/raw/main/assets/config-bills-number.png)
Energy (energy_data.csv) and billing (billing_periods.csv) data are stored in "user_files" directory. Create the directory and add the files to it if you have data from previous installations.
Save this files before you remove the integration if plan to install it again later.

## Output
After add the integration it gets available data from:
* https://www.ufd.es: Electricity consumptions and billings periods
* https://api.esios.ree.es: Hourly energy prices
* https://comparador.cnmc.gob.es/facturaluz/inicio: PVPC bills simulation

It takes a few minutes the fetch available data (about two years). After this time you will have:
* Statistics
    * pvpc_energy:consumption (PVPC: Consumo): Hourly electricity consumption
    * pvpc_energy:cost (PVPC: Coste): Hourly electricity costs
* States
    * pvpc_energy.current_bill: Cost of the current bill. In the "detail" attribute it has a markdown with the last "bills_number" bills


## Panels
Add consumption to Electricity grid in Energy Dashboard:
* sensor which measures grid consumption: "PVPC: Consumo"
* Use an entity tracking the total costs: "PVPC: Coste"
![Grid consumption configuration](https://github.com/yinyang17/pvpc_energy/raw/main/assets/grid-consumption-configuration.png)

Add to Lovelace a Markdown card to show the last bills indicating in content:
```yml
{{ state_attr('pvpc_energy.current_bill', 'detail')}}
```
![Markdown card configuration](https://github.com/yinyang17/pvpc_energy/raw/main/assets/markdown-card-config.png)
