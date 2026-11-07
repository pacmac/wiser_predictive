# predictive — SPEC (draft for approval, 2026-11-07)

Task: `predictive-integration`. History: `../inventory/docs/HANDOVER.md`, mcpp project `ha-inventory`, task `predictive-heating-rework` (notes 13-20).

## GOAL
Every Wiser room stays above its minimum. Heat is called while the room is still ABOVE the minimum, so stored fabric heat is never lost.
Success test: over several days the reading never touches the minimum line, and `heat_needed` is on while the reading is still above it.
Lounge is the gate (not passive, minimum = its target, 12.5 now). Passive rooms: minimum = thermostat LOW (12.0). Watch bed_3 next.

## FORM
Custom integration, domain `wiser_predictive`, in this repo. Installed by hand into `/config/custom_components/` on the box while developing; HACS later (already installed on the box).
Replaces the YAML predictor (`pac_predictive_heat`, `predictive_lounge`, automation Predictive Heating). Replaces Boost on Demand only after days of charts prove it (Peter, 2026-11-06).

## LAYOUT
```
custom_components/wiser_predictive/
  model.py          pure Python, NO homeassistant imports: fit, time_to_minimum, lead, decision
  const.py
  hub.py            HA-side hub lookups: hub name, hub device, rooms of a hub
  manifest.json
  __init__.py  config_flow.py  sensor.py  binary_sensor.py  translations/en.json
tests/              pytest on model.py; fixtures cut from the archived history
deploy.py           copy the integration to the box: dry run by default, --go copies, --restart separate
docs/SPEC.md
```
Only files in this layout are in scope.

## SKELETON FIRST (Peter, 2026-11-07)
Approved with a priority change: the integration must be visible inside HA before the model exists, because until now the whole thing has been invisible. The first build is the shell:
- Appears in Settings > Devices & services as "Wiser Predictive", one device, set up by a config flow, settings editable afterwards (options flow).
- `margin` sensors per room are REAL (current reading minus the room's minimum), computed by `model.py`.
- `time_to_minimum` sensors and `heat_needed` exist but report `unknown` until the model is built. They never report a made-up value, and `heat_needed` never reports off while it cannot know.
- Installing it is a box change: `deploy.py` dry run first, `--go` copies files only, `--restart` (HA core restart, needed once for a new integration) only on Peter's go-ahead. The deploy backs up anything it overwrites and writes an apply row for the ledger.

## MODEL (model.py)
Inputs per room: reading series (time, °C), minimum, outside temperature series.
1. Fit over a window of at least 90 minutes (a shorter window is noise: the lounge sensor steps 0.1 °C). Candidate forms: linear, and Newton cooling `dT/dt = -k (T - To)`. The replay chooses between them, not opinion.
2. `time_to_minimum` = time until the fitted curve reaches the minimum; unknown if the fit is rising, flat or the window is short.
3. `lead` = measured boost heat-up time (8-28 min, median 11-13) plus a fixed buffer. The buffer is derived from the replay, not guessed.
4. `heat_needed` is on when `time_to_minimum <= lead`, OR the margin is already below the buffer. Off when heating is on or the room is boosted/overridden (episode over). Hysteresis so a flickering reading does not flap it.

## ENTITIES
Per room: `sensor.<room>_time_to_minimum` (min), `sensor.<room>_margin` (°C above minimum).
One `binary_sensor.heat_needed`, attributes: room that triggered, time_to_minimum, lead.

## CONFIG (config flow, editable in the HA UI)
Outside sensor, rooms, buffer, announce target, heating-state sensor.

## HUB (Peter, 2026-11-07)
A house can have more than one Wiser hub (here two: `03E34F` has all the rooms; `05C5D8` has the boiler channels only). Each hub is its own `wiser` config entry, and each room device is linked to its hub (`via_device`).
- Setup: no `wiser` entry, abort with a reason. Exactly one hub, it is selected automatically and the hub step is skipped. More than one, the user selects the hub first; rooms are then discovered from that hub only.
- One Wiser Predictive entry per hub (unique id = the hub's config entry id).
- The selected hub is SHOWN: in the entry title ("Wiser Predictive (Wiser HeatHub (03E34F))"), as the device's "connected via" hub, and as a diagnostic `Hub` sensor on the device.
- A hub with no rooms is refused at the rooms step ("no rooms found on this hub").
- The hub cannot be changed in the options form (it would orphan the entities); remove and add again.
- Entries made before this (version 0.1.0, no hub) are not migrated: remove and add again.

## NOTHING HARD-CODED (Peter, 2026-11-07)
The integration must work in any house with a Wiser system. No entity id, room name, hub name or site name of this house appears in the code or as a default.
- The HUB is selected, never assumed (see HUB below).
- Rooms are DISCOVERED from the selected hub: climate entities of that hub's `wiser` config entry that carry `is_passive` (Wiser rooms do; the hot water channel does not). The user can untick any. Room names come from the entity's own `name`, falling back to `friendly_name`, then the entity id.
- Outside sensor: NO default. The user picks a temperature sensor. (In this house the garage roofspace sensor fits best, r 0.88 with the forecast, lags 2 h, about 1.4 °C warm; that is this house's choice at setup, not code.)
- Heating-state sensor: offered from the selected hub's own device, chosen by the user. (In this house it is Hub A `sensor.wiser_heating`, NOT `_channel_1`, which is Hub B.)
- Minimum per room comes from the climate attributes (`target_temp_low`, else `temperature`), never a number in code.
- `deploy.py` is a development tool: the ssh command comes from the environment (`HA_SSH`), not from the repo.
- House facts live in this spec's notes and the handover, not in `custom_components/`.

## STAGE 1 (the only stage in this spec)
Announce only: `script.speak`, target `both` (uk + sg), cooldown 120 min. NO `climate.set_temperature`, no change to Boost on Demand.
Later stages (raise the lounge target; retire Boost on Demand) need their own spec and Peter's go-ahead.

## TESTS AND PROOF
- Unit tests on `model.py` with synthetic series (falling, rising, flat, short window, flicker).
- Replay of the archived history (`../inventory/archive/predictive-*.json`, merged from 2026-10-27; git-ignored there, so cut a small fixture into `tests/`). Report per episode: lead achieved, minimum touched yes/no, false alarms.
- A change is closed only on a test that ran red then green.

## OUT OF SCOPE
Any box change (needs a dry run, backup, ledger row, Peter's go-ahead). The Wiser integration. The soil-sensor area fix. The `ha-inventory` repo.

## DECIDED (Peter, 2026-11-07)
- Repo: GitHub `pacmac/wiser_predictive`, public.
- Domain and package: `wiser_predictive`, following the repo name. It replaces the draft name `predictive_heating`. Directory is `custom_components/wiser_predictive/`.

## OPEN FOR PETER
- Lead buffer: derived from the replay (proposed default, used unless Peter gives a number).
