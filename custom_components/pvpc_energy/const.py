"""Constants for the PVPC Energy integration."""

DOMAIN = "pvpc_energy"
CURRENT_BILL_STATE = f"{DOMAIN}.current_bill"
CONSUMPTION_STATISTIC_ID = f"{DOMAIN}:consumption"
CONSUMPTION_STATISTIC_NAME = 'PVPC: Consumo'
COST_STATISTIC_ID = f"{DOMAIN}:cost"
COST_STATISTIC_NAME = 'PVPC: Coste'
ENERGY_FILE = f"/config/custom_components/{DOMAIN}/user_files/energy_data.csv"
BILLING_PERIODS_FILE = f"/config/custom_components/{DOMAIN}/user_files/billing_periods.csv"