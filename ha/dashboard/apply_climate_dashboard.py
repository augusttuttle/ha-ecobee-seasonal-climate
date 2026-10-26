"""Add the seasonal-thermostat cards to the home-hub dashboard. Idempotent.

Runs INSIDE the HA container (it has aiohttp); see apply-dashboard.sh.
  - Home view, "Climate" section: existing thermostat tiles are kept, the season
    picker and a link to the Climate tab are appended (replaced on re-run).
  - A "Climate" view (path: climate) is inserted after "house", holding what you
    read day to day, plus a "Climate settings" subview (path: climate-settings)
    holding the knobs. Both are replaced on re-run. A subview has no tab of its own;
    it is reached from the "Settings" link on the Climate tab.
Pass --restore FILE to save FILE's dashboard config back verbatim instead.
"""
import asyncio
import json
import os
import sys

import aiohttp

DASHBOARD = "home-hub"


def tile(entity, **kw):
    return {"type": "tile", "entity": entity, **kw}


def number(entity, name):
    return tile(entity, name=name, features=[{"type": "numeric-input", "style": "buttons"}])


def heading(text, icon, **kw):
    return {"type": "heading", "heading": text, "icon": icon, "heading_style": "title", **kw}


def confirm_script(entity, name, icon, text):
    return tile(
        entity,
        name=name,
        icon=icon,
        tap_action={
            "action": "perform-action",
            "perform_action": "script.turn_on",
            "target": {"entity_id": entity},
            "confirmation": {"text": text},
        },
        icon_tap_action={"action": "none"},
    )


PLAN_MD = """\
{% set s = states('input_select.climate_season') %}
{% set on = is_state('input_boolean.climate_schedule_enabled', 'on') %}
**Schedule:** {{ 'running' if on else 'OFF (HA is not touching the thermostats)' }}
· **Season:** {{ s }}{{ ' (auto)' if is_state('input_boolean.climate_season_auto', 'on') else ' (manual)' }}

| | Main floor | Upstairs |
|---|---|---|
| Now | {{ states('sensor.main_floor_current_temperature') | round(1) }}°F, {{ state_attr('climate.main_floor', 'hvac_action') }} | {{ states('sensor.upstairs_current_temperature') | round(1) }}°F, {{ state_attr('climate.upstairs', 'hvac_action') }} |
| Target | {% if is_state('climate.main_floor', 'heat_cool') %}{{ state_attr('climate.main_floor', 'target_temp_low') }}–{{ state_attr('climate.main_floor', 'target_temp_high') }}{% else %}{{ states('climate.main_floor') }} {{ state_attr('climate.main_floor', 'temperature') }}{% endif %} | {% if is_state('climate.upstairs', 'heat_cool') %}{{ state_attr('climate.upstairs', 'target_temp_low') }}–{{ state_attr('climate.upstairs', 'target_temp_high') }}{% else %}{{ states('climate.upstairs') }} {{ state_attr('climate.upstairs', 'temperature') }}{% endif %} |
| Block | {{ 'weekday daytime' if is_state('schedule.climate_main_floor_day', 'on') else 'comfort' }} | {{ 'weekday daytime' if is_state('schedule.climate_upstairs_day', 'on') else 'comfort' }} |
| Adjust | {% if is_state('timer.climate_override_main_floor', 'active') %}{{ '%+d' | format(states('input_number.climate_override_offset_main_floor') | int) }}°F until {{ as_timestamp(state_attr('timer.climate_override_main_floor', 'finishes_at')) | timestamp_custom('%-I:%M %p') }}{% else %}none{% endif %} | {% if is_state('timer.climate_override_upstairs', 'active') %}{{ '%+d' | format(states('input_number.climate_override_offset_upstairs') | int) }}°F until {{ as_timestamp(state_attr('timer.climate_override_upstairs', 'finishes_at')) | timestamp_custom('%-I:%M %p') }}{% else %}none{% endif %} |
| Next change | {{ as_timestamp(state_attr('schedule.climate_main_floor_day', 'next_event')) | timestamp_custom('%a %-I:%M %p') if state_attr('schedule.climate_main_floor_day', 'next_event') else '—' }} | {{ as_timestamp(state_attr('schedule.climate_upstairs_day', 'next_event')) | timestamp_custom('%a %-I:%M %p') if state_attr('schedule.climate_upstairs_day', 'next_event') else '—' }} |

**Forecast highs (next 3 days):** {{ state_attr('sensor.climate_forecast_avg_high', 'highs') | join(', ') }}°F,
avg {{ states('sensor.climate_forecast_avg_high') }}°F.
Heat below {{ states('input_number.climate_heat_below') | int }}, Cool above {{ states('input_number.climate_cool_above') | int }}; checked daily at 5:05.
"""


EFFICIENCY_MD = """**Furnace hours per heating degree day** is the building's efficiency number: how long
the furnace ran per degree the day averaged below 65°F. Lower is better. It only shows
on days with at least 3 HDD. Compare it week to week, or before and after a change.
"""

def adjust_card(zone):
    # One card per floor: shows "now -> with the adjustment"; tap starts or ends it.
    sensor = f"sensor.{zone}_adjust_preview"
    return {
        "type": "custom:mushroom-template-card",
        "entity": sensor,
        "primary": f"{{{{ state_attr('{sensor}', 'title') }}}}",
        "secondary": f"{{{{ state_attr('{sensor}', 'detail') }}}}",
        "icon": f"{{{{ state_attr('{sensor}', 'card_icon') }}}}",
        "icon_color": f"{{{{ state_attr('{sensor}', 'card_color') }}}}",
        "multiline_secondary": True,
        "tap_action": {"action": "perform-action",
                       "perform_action": "script.climate_override_toggle",
                       "data": {"zone": zone}},
        "hold_action": {"action": "more-info"},
        "grid_options": {"columns": 12},
    }


def adjust_cards():
    cards = [heading("Adjust temporarily", "mdi:thermometer-plus")]
    for zone in ("main_floor", "upstairs"):
        cards += [
            adjust_card(zone),
            number(f"input_number.climate_override_offset_{zone}", "Change by"),
            number(f"input_number.climate_override_hours_{zone}", "For"),
        ]
    return cards


ADJUST_SECTION = {"type": "grid", "cards": adjust_cards()}


HOME_CARDS = [
    tile(
        "input_select.climate_season",
        name="Season",
        features=[{"type": "select-options"}],
        grid_options={"columns": 12},
    ),
    heading(
        "Schedule details",
        "mdi:chevron-right",
        heading_style="subtitle",
        tap_action={"action": "navigate", "navigation_path": f"/{DASHBOARD}/climate"},
    ),
]

CLIMATE_VIEW = {
    "type": "sections",
    "title": "Climate",
    "path": "climate",
    "icon": "mdi:sun-snowflake-variant",
    "max_columns": 3,
    "badges": [
        {"type": "entity", "entity": "input_select.climate_season"},
        {"type": "entity", "entity": "sensor.climate_forecast_avg_high"},
        {"type": "entity", "entity": "sensor.main_floor_current_temperature"},
        {"type": "entity", "entity": "sensor.upstairs_current_temperature"},
    ],
    "sections": [
        {"type": "grid", "cards": [
            heading("Right now", "mdi:thermostat"),
            {"type": "markdown", "content": PLAN_MD},
            tile("climate.main_floor", features=[{"type": "target-temperature"}]),
            tile("climate.upstairs", features=[{"type": "target-temperature"}]),
        ]},
        ADJUST_SECTION,
        {"type": "grid", "cards": [
            heading("Schedule", "mdi:calendar-clock"),
            tile("input_boolean.climate_schedule_enabled", name="Schedule enabled"),
            tile("input_boolean.climate_season_auto", name="Auto season"),
            tile("input_select.climate_season", name="Season",
                 features=[{"type": "select-options"}], grid_options={"columns": 12}),
            tile("schedule.climate_main_floor_day", name="Main floor daytime"),
            tile("schedule.climate_upstairs_day", name="Upstairs daytime"),
            heading(
                "Settings",
                "mdi:cog",
                heading_style="subtitle",
                tap_action={"action": "navigate",
                            "navigation_path": f"/{DASHBOARD}/climate-settings"},
            ),
        ]},
        {"type": "grid", "cards": [
            heading("Runtime today", "mdi:timer-outline"),
            tile("sensor.furnace_heating_today", name="Furnace"),
            tile("sensor.ac_cooling_today", name="AC"),
            tile("sensor.main_floor_heat_call_today", name="Main heat call"),
            tile("sensor.upstairs_heat_call_today", name="Upstairs heat call"),
            tile("sensor.main_floor_cool_call_today", name="Main cool call"),
            tile("sensor.upstairs_cool_call_today", name="Upstairs cool call"),
            tile("sensor.blower_today", name="Blower"),
            tile("sensor.furnace_starts_last_hour", name="Furnace starts (1 h)"),
        ]},
        {"type": "grid", "cards": [
            heading("Efficiency", "mdi:chart-bell-curve-cumulative"),
            tile("sensor.outdoor_temperature", name="Outdoor"),
            tile("sensor.heating_degree_days_today", name="Heating degree days today"),
            tile("sensor.furnace_hours_per_hdd_yesterday", name="Furnace h per HDD (yesterday)",
                 grid_options={"columns": 12}),
            {"type": "markdown", "content": EFFICIENCY_MD},
        ]},
        {"type": "grid", "cards": [
            heading("Maintenance", "mdi:wrench-clock"),
            tile("binary_sensor.filter_change_due", name="Filter change due"),
            tile("input_datetime.climate_filter_changed", name="Filter last changed"),
            tile("sensor.filter_blower_hours_used", name="Blower hours on filter"),
            tile("sensor.filter_days_used", name="Days on filter"),
            confirm_script("script.climate_filter_changed", "Filter changed today",
                           "mdi:air-filter",
                           "Mark the filter as changed today and restart its hour count?"),
        ]},
        {"type": "grid", "column_span": 2, "cards": [
            heading("History", "mdi:chart-line"),
            {"type": "history-graph", "title": "Indoor temperature", "hours_to_show": 72,
             "entities": ["sensor.main_floor_current_temperature",
                          "sensor.upstairs_current_temperature"],
             "grid_options": {"columns": "full"}},
            {"type": "history-graph", "title": "Thermostats", "hours_to_show": 72,
             "entities": ["climate.main_floor", "climate.upstairs"],
             "grid_options": {"columns": "full"}},
        ]},
        {"type": "grid", "column_span": 2, "cards": [
            heading("Daily totals (kept long-term)", "mdi:chart-bar"),
            {"type": "statistics-graph", "title": "Furnace hours and heating degree days per day",
             "chart_type": "bar", "period": "day", "days_to_show": 30, "stat_types": ["change"],
             "entities": ["sensor.furnace_heat_hours_total", "sensor.heating_degree_days_total"],
             "grid_options": {"columns": "full"}},
            {"type": "statistics-graph", "title": "Zone heat calls per day (hours)",
             "chart_type": "bar", "period": "day", "days_to_show": 30, "stat_types": ["change"],
             "entities": ["sensor.main_floor_heat_call_hours_total",
                          "sensor.upstairs_heat_call_hours_total"],
             "grid_options": {"columns": "full"}},
        ]},
    ],
}

SETTINGS_VIEW = {
    "type": "sections",
    "title": "Climate settings",
    "path": "climate-settings",
    "icon": "mdi:cog",
    "subview": True,
    "back_path": f"/{DASHBOARD}/climate",
    "max_columns": 3,
    "sections": [
        {"type": "grid", "cards": [
            heading("Heat season", "mdi:fire"),
            number("input_number.climate_heat_comfort", "Comfort"),
            number("input_number.climate_heat_day", "Weekday daytime"),
            heading("Cool season", "mdi:snowflake"),
            number("input_number.climate_cool_comfort", "Comfort"),
            number("input_number.climate_cool_day", "Weekday daytime"),
        ]},
        {"type": "grid", "cards": [
            heading("Shoulder season", "mdi:sun-snowflake-variant"),
            number("input_number.climate_shoulder_heat_comfort", "Heat below (comfort)"),
            number("input_number.climate_shoulder_heat_day", "Heat below (daytime)"),
            number("input_number.climate_shoulder_cool", "Cool above"),
            number("input_number.climate_min_delta", "Min heat/cool gap"),
        ]},
        {"type": "grid", "cards": [
            heading("Season switching", "mdi:weather-partly-cloudy"),
            number("input_number.climate_heat_below", "Heat when avg high below"),
            number("input_number.climate_heat_exit_above", "Leave Heat above"),
            number("input_number.climate_cool_above", "Cool when avg high above"),
            number("input_number.climate_cool_exit_below", "Leave Cool below"),
        ]},
        {"type": "grid", "cards": [
            heading("Alarms", "mdi:alarm-light-outline"),
            tile("input_boolean.climate_alarms_enabled", name="Alarms enabled",
                 grid_options={"columns": 12}),
            number("input_number.climate_fault_minutes", "No-progress after (min)"),
            number("input_number.climate_short_cycle_max", "Max starts per hour"),
            number("input_number.climate_alarm_low", "Any floor below"),
            number("input_number.climate_alarm_high", "Any floor above"),
            {"type": "tile", "entity": "script.climate_alert", "name": "Send test alert",
             "icon": "mdi:bell-ring-outline", "icon_tap_action": {"action": "none"},
             "tap_action": {"action": "perform-action", "perform_action": "script.climate_alert",
                            "data": {"title": "HVAC test alert",
                                     "message": "Test from the Climate tab. If you can read this, HVAC alarms reach this phone."},
                            "confirmation": {"text": "Send a test alert to both phones?"}}},
        ]},
        {"type": "grid", "cards": [
            heading("Filter", "mdi:air-filter"),
            number("input_number.climate_filter_max_hours", "Filter life (hours)"),
            number("input_number.climate_filter_max_days", "Filter life (days)"),
        ]},
        {"type": "grid", "cards": [
            heading("Restore", "mdi:backup-restore"),
            confirm_script(
                "script.climate_restore_baseline", "Restore 2026-10-19 baseline",
                "mdi:backup-restore",
                "Turn the schedule OFF and set both thermostats back to heat_cool 67/72?"),
            confirm_script(
                "script.climate_reset_settings_to_defaults", "Reset settings to defaults",
                "mdi:restore",
                "Reset every temperature and threshold on this page to the defaults?"),
        ]},
    ],
}


def ours(card):
    # Matched by content, not an extra key: unknown keys break the visual editor.
    return card in HOME_CARDS or (
        card.get("type") == "heading" and card.get("heading") == "Schedule details"
    ) or str(card.get("entity", "")).startswith(("input_select.climate_", "input_boolean.climate_",
                                                    "sensor.climate_"))


def patch(cfg):
    views = cfg["views"]
    home = next(v for v in views if v.get("path") == "home")
    section = next(
        s for s in home["sections"]
        if any(c.get("type") == "heading" and c.get("heading") == "Climate" for c in s.get("cards", []))
    )
    section["cards"] = [c for c in section["cards"] if not ours(c)] + HOME_CARDS
    home["sections"] = [s for s in home["sections"]
                        if (s.get("cards") or [{}])[0].get("heading") != "Adjust temporarily"]
    at = home["sections"].index(section) + 1
    home["sections"].insert(at, ADJUST_SECTION)

    views[:] = [v for v in views if v.get("path") not in ("climate", "climate-settings")]
    after = next((i for i, v in enumerate(views) if v.get("path") == "house"), len(views) - 1)
    views[after + 1:after + 1] = [CLIMATE_VIEW, SETTINGS_VIEW]
    return cfg


async def main():
    restore = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--restore" else None
    async with aiohttp.ClientSession() as s, s.ws_connect("http://127.0.0.1:8123/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["HA_TOKEN"]})
        if (await ws.receive_json())["type"] != "auth_ok":
            sys.exit("auth failed")
        if restore:
            cfg = json.load(open(restore))
        else:
            await ws.send_json({"id": 1, "type": "lovelace/config", "url_path": DASHBOARD})
            cfg = patch((await ws.receive_json())["result"])
        await ws.send_json({"id": 2, "type": "lovelace/config/save", "url_path": DASHBOARD, "config": cfg})
        r = await ws.receive_json()
        if not r.get("success"):
            sys.exit(f"save failed: {r}")
        print("saved", DASHBOARD, "views:", [v.get("path") for v in cfg["views"]])


asyncio.run(main())
