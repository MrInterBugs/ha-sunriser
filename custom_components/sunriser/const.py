# SPDX-License-Identifier: GPL-3.0-or-later
DOMAIN = "sunriser"

PLATFORMS = ["button", "light", "sensor", "switch"]

DEFAULT_PORT = 80
DEFAULT_SCAN_INTERVAL = 30

CONF_SCAN_INTERVAL = "scan_interval"

# PWM values on device are 0–1000
PWM_MAX = 1000

# Mapping from pwm#X#color id → display name, sourced from sunriser_colors_config.js
COLOR_NAMES: dict[str, str] = {
    "625nm": "RED 625nm",
    "3500k": "SUNSET 3500K",
    "4500k": "TROPIC 4500K",
    "5500k": "DAY 5500K",
    "6500k": "SKY 6500K",
    "7500k": "POLAR 7500K",
    "coralmix": "CORAL MIX",
    "11000k": "REEF 11000K",
    "13000k": "MARINE 13000K",
    "465nm": "ROYAL BLUE 465nm",
    "growx5": "PLANT-GROW / GROWx5",
    "aqualumix_freshwater": "aquaLUMix FRESHWATER",
    "aqualumix_amazon_grow": "aquaLUMix AMAZON-GROW",
    "aqualumix_african_sun": "aquaLUMix AFRICAN-SUN",
    "aqualumix_seawater": "aquaLUMix SEAWATER",
    "powermain": "powerBEAM MAIN CHANNEL",
    "powermoon": "powerBEAM MOON",
    "powersunrise": "powerBEAM SUNRISE",
    "spotmain": "spotBEAM #1 MAIN LIGHT",
    "spotmoon": "spotBEAM #2 MOON",
    "spotsunrise": "spotBEAM #3 SUNRISE",
    "pump": "Mini Pump",
    "co": "CO2 Valve",
    "custom": "Custom Color 1",
    "custompink": "Custom Color 2",
    "customcyan": "Custom Color 3",
    "customblue": "Custom Color 4",
    "customred": "Custom Color 5",
    "aqualumix_freshwater_day_tropic": "aquaLUMix FRESHWATER #1 DAY/TROPIC",
    "aqualumix_freshwater_sky_day": "aquaLUMix FRESHWATER #2 SKY/DAY",
    "aqualumix_freshwater_blue_mix": "aquaLUMix FRESHWATER #3 BLUE MIX",
    "aqualumix_freshwater_sunset_red": "aquaLUMix FRESHWATER #4 SUNSET/RED",
    "aqualumix_amazon_grow_tropic_day": "aquaLUMix AMAZON-GROW #1 TROPIC/DAY",
    "aqualumix_amazon_grow_sky_grow": "aquaLUMix AMAZON-GROW #2 SKY/GROW",
    "aqualumix_amazon_grow_blue_mix": "aquaLUMix AMAZON-GROW #3 BLUE MIX",
    "aqualumix_amazon_grow_sunset_red": "aquaLUMix AMAZON-GROW #4 SUNSET/RED",
    "aqualumix_african_sun_sky": "aquaLUMix AFRICAN-SUN #1 SKY",
    "aqualumix_african_sun_reef_polar": "aquaLUMix AFRICAN-SUN #2 REEF/POLAR",
    "aqualumix_african_sun_blue_mix": "aquaLUMix AFRICAN-SUN #3 BLUE MIX",
    "aqualumix_african_sun_sunset_mix": "aquaLUMix AFRICAN-SUN #4 SUNSET MIX",
    "aqualumix_seawater_marine_reef": "aquaLUMix SEAWATER #1 MARINE/REEF",
    "aqualumix_seawater_reef": "aquaLUMix SEAWATER #2 REEF",
    "aqualumix_seawater_blue": "aquaLUMix SEAWATER #3 BLUE",
    "aqualumix_seawater_coral_mix": "aquaLUMix SEAWATER #4 CORAL MIX",
}
