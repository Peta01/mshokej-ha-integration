# MS Hokej Integration

HACS-ready Home Assistant custom integration for the MS hockey project.

## What it does

- keeps its own stored copy of tournament results in Home Assistant storage
- refreshes using the same policy as `ms2026\agent.py`
  - `LIVE` match -> poll every 60s
  - before the next scheduled match -> wake up `pre_match_buffer` seconds early
  - no upcoming match -> poll every hour
- exposes a snapshot sensor usable by the companion Lovelace card
- adds a manual refresh button

## Included entities

- `sensor.ms_hokej_snapshot`
- `sensor.ms_hokej_next_match`
- `sensor.ms_hokej_favorite_team_position`
- `sensor.ms_hokej_refresh_mode`
- `button.ms_hokej_refresh`

## Install locally

1. Copy `custom_components\mshokej` into your Home Assistant `config\custom_components\`.
2. Restart Home Assistant.
3. Add the integration from **Settings -> Devices & Services**.
4. Install the companion card from the `ha_mshokej_card` folder.

## Repo split

This folder is prepared so it can be pushed as a standalone HACS integration repository.
The original Python project remains separate in `ms2026\`.
