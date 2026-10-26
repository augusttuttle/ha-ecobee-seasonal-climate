# Seasonal thermostat control

Home Assistant runs the schedule for both ecobees (`climate.main_floor` and
`climate.upstairs`, connected locally over HomeKit). Everything lives in one package file,
[ha/packages/climate_seasonal.yaml](ha/packages/climate_seasonal.yaml).

Built with help from Claude Code.

## How it works

| Season | Mode | Comfort (wake, evening, sleep, weekends) | Weekday daytime |
|---|---|---|---|
| Heat | heat | 72 | 72 |
| Shoulder | heat_cool | heat below 72, cool above 75* | heat below 72, cool above 75 |
| Cool | cool | 72 | 72 |

\* Cooling has to sit at least the ecobee's Heat/Cool Min Delta above heating. Both
ecobees were set to 3 °F on 2026-10-20 (Installation Settings → Thresholds), and
`input_number.climate_min_delta` is 3 to match. **Keep the two equal.** If HA sends a
range narrower than the ecobee allows, the ecobee spreads it out around the middle
(72/75 became 71/76 while the ecobees were still at 5 °F). **HomeKit keeps reporting the
requested values, so HA never finds out.** Check the thermostats themselves after
changing either setting.

- **Weekday daytime:** main floor 08:30 to 16:00. Upstairs 08:30 to 12:00, so the
  upstairs is back at comfort for the afternoon. Since 2026-10-26 the daytime targets equal
  comfort (72/75), so these windows change nothing. They stay so a daytime setback can
  come back by lowering "Weekday daytime" in Climate settings.
- **Season:** when `input_boolean.climate_season_auto` is on, HA checks the average
  forecast high for the next 3 days at 05:05 each morning:
  - It switches to Heat below 62 °F and comes back out above 68 °F.
  - It switches to Cool above 80 °F and comes back out below 74 °F.

  Because the switch-in and switch-out temperatures differ, one odd day won't flip the
  season. You can also turn auto off and pick the season by hand.
- **Manual changes:** if you change a thermostat by hand, the change stays until the next
  time block or season change.
- **Temporary adjust:** "Adjust temporarily" on the Home view has one card per floor.
  - The card shows the floor's current range and what it will become, for example
    "Upstairs · 72–75 → 74–77°F". Below it are "Change by" (up to ±6 °F) and "For" (0.5 to
    12 hours).
  - Tap the card to start. While it runs, the card shows the end time and the range it
    will return to, and tapping it again ends the adjustment early.
  - Both targets move together, so the heat/cool gap stays the same. A time-block or
    season change during the adjustment keeps the offset on top of the new targets.
  - The timers survive an HA restart. The card text comes from
    `sensor.<floor>_adjust_preview`.
  - From an automation or the companion app, call `script.climate_override_start` with
    `zone` (`main_floor`, `upstairs` or `both`) and optionally `offset` and `hours`.
  - It only works while the schedule is enabled.
- **Measurements:** the forecast average high (`sensor.climate_forecast_avg_high`) and
  the heating and cooling hours each floor ran today.

All temperatures and thresholds are `input_number` helpers you can change in the UI.
`script.climate_reset_settings_to_defaults` sets them back to the values above.

## Restore points

Take these before the first install:

| Layer | What | How to go back |
|---|---|---|
| Thermostats | The pre-install state. `script.climate_restore_baseline` holds heat_cool 67/72, fan auto, mode home; edit it to match yours | Run `script.climate_restore_baseline` |
| ecobee device | Schedule, Comfort Settings, Hold Action (HA can't read these over HomeKit) | Screenshots from the ecobee app |
| HA full backup | Settings → System → Backups → Create backup | Restore it from the same page |
| configuration.yaml | `setup-ha-once.sh` saves `configuration.yaml.bak-20261019-thermo` | Copy back and restart HA |
| Dashboard | The dashboard config as JSON (the object holding `views`) | `./apply-dashboard.sh --restore <file>` |

**Turning it all off:** run `script.climate_restore_baseline`. It turns off
`input_boolean.climate_schedule_enabled` and puts both thermostats back to the baseline.

## Monitoring (alarms, history, maintenance)

[ha/packages/climate_monitoring.yaml](ha/packages/climate_monitoring.yaml) is separate from
the schedule. The plant is one gas furnace with AC and dampers for two zones. Each ecobee
reports its own zone's call, and the furnace runs while either zone calls.

**Alarms** go to `notify.climate_alerts` as time-sensitive notifications and to HA's
notification list. `input_boolean.climate_alarms_enabled` turns all of them off at once.

| Alarm | Fires when | Default |
|---|---|---|
| No progress | A zone has called for heat or cooling for N minutes and its temperature moved less than 0.5 °F the right way (furnace lockout, flame sensor, stuck damper, frozen coil) | 45 min |
| Temperature limits | Any floor below the low limit or above the high limit for 10 min, at any time | 62 / 82 °F |
| Thermostat offline | A thermostat is unavailable in HA for 15 min | |
| Short cycling | The furnace or AC starts more than N times in an hour (one alert per hour at most) | 6 |

**History that lasts.** HA's database keeps detailed history for only 10 days. These are
running totals, which HA keeps permanently as long-term statistics:

- Furnace, AC and blower hours, plus heat and cool call hours per zone
- Heating and cooling degree days (base 65 °F, outdoor temperature from met.no)

Daily meters reset at midnight and keep the previous day in their `last_period`
attribute. `sensor.furnace_hours_per_hdd_yesterday` is the efficiency number: furnace
hours per heating degree day.

**Maintenance:**
- The filter is due at 300 blower hours or 90 days, whichever comes first. A reminder
  goes out at 9:00 each day once it's due.
- Run `script.climate_filter_changed` after changing the filter. It's the "Filter changed
  today" button on the Climate tab.
- A reminder to book the furnace tune-up goes out every September 1.

**Limits:**
- HomeKit doesn't report fan-only running, so blower hours count heating, cooling and
  `fan_mode: on`, but not the ecobee's own fan-circulation minutes.
- The thermostats report what they were *asked* for, which isn't always what they run
  (see the min delta note above).

`script.climate_monitoring_defaults` resets the alarm and filter settings. The main
"reset settings to defaults" script calls it too.

## Dashboard

[ha/dashboard/apply_climate_dashboard.py](ha/dashboard/apply_climate_dashboard.py) adds
the climate cards to the Home Hub dashboard:

- **Home view, Climate section:** a season picker and a link to the Climate tab, below
  the two thermostat tiles (those aren't the script's, so it leaves them alone).
- **Climate tab:** what you check day to day. That's the current plan, the schedule
  switches, runtime today, efficiency, filter status with a "Filter changed today"
  button, 72 hours of history and 30 days of daily totals.
- **Climate settings:** a subview (no tab of its own) opened from the "Settings" link
  on the Climate tab. It holds every temperature and threshold, the alarm settings with
  a "Send test alert" button, the filter-life limits and the two restore buttons.

Every button asks before it runs.

Run `./apply-dashboard.sh` after changing the script. Re-running it replaces its own
cards and leaves everything else alone.

To put the dashboard back the way it was before this project, run
`./apply-dashboard.sh --restore <file>` with the copy saved under "Restore points".

## Setup

The scripts run on a laptop and reach Home Assistant over ssh, on the Docker host
that runs the HA container.

- Set `HA_HOST` to the ssh target, for example `export HA_HOST=user@nas`.
- `HA_CONTAINER` is the container name. The default,
  `ix-home-assistant-home-assistant-1`, is what the TrueNAS SCALE app uses.
- `SSH` defaults to `ssh`. On Windows, set it to
  `/c/Windows/System32/OpenSSH/ssh.exe` if Git's ssh can't reach your key agent.
- Put a Home Assistant long-lived access token in `~/.ha_token` on the Docker host.
- The dashboard script edits the dashboard named in `DASHBOARD` at the top of
  [apply_climate_dashboard.py](ha/dashboard/apply_climate_dashboard.py) (`home-hub`).
- Alerts go to `notify.climate_alerts`. Define it as a notify group of your phones in
  `configuration.yaml`:

  ```yaml
  notify:
    - name: climate_alerts
      platform: group
      services:
        - service: mobile_app_your_phone
  ```

## Deploying

`./deploy.sh` (Git Bash) copies the package into HA, checks the config, and reloads. If
the check fails, it puts the previous file back. After the reload it also scans HA's log
for automations that failed validation. HA's config check misses some of these, then
silently disables the automation. A YAML key named `off`, which YAML reads as false,
disabled the whole schedule once this way. If it finds one, it prints the error and
exits with code 2. The first deploy also needs this at the
top of `configuration.yaml`, followed by one HA restart:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

## Before turning it on (ecobee app, both thermostats)

1. Screenshot the Schedule, Comfort Settings and Settings → Preferences.
2. Set Hold Action to "Until I change it". Otherwise the ecobee's own schedule undoes HA's changes.
3. Set every schedule period to Home, and turn off Smart Home/Away and Follow Me.
4. Set Heat/Cool Min Delta to 3 °F (Installation Settings → Thresholds). The reset
   defaults assume 3. If you use a different value, set `input_number.climate_min_delta`
   to match.

Then run `script.climate_reset_settings_to_defaults`, set the season, turn on
`input_boolean.climate_season_auto`, and turn on `input_boolean.climate_schedule_enabled`.
