# predictive — SPEC (draft for approval, 2026-11-07)

Task: `predictive-integration`. History: `../inventory/docs/HANDOVER.md`, mcpp project `ha-inventory`, task `predictive-heating-rework` (notes 13-20).

## GOAL
Every Wiser room stays above its minimum. Heat is called while the room is still ABOVE the minimum, so stored fabric heat is never lost.
Success test: over several days the reading never touches the minimum line, and `heat_needed` is on while the reading is still above it.
Boost on Demand only stops the boiler cycling. It does not solve the real problem: by the time the boiler calls, the thermal mass (the fabric) has already fallen to a level that would have kicked in before Boost on Demand did, and that stored heat is expensive to win back (Peter, 2026-11-07). So "reaches the minimum" is already too late; the predictor's job is to act on the thermal mass before that.
Lounge is the gate (not passive, minimum = its target, 12.5 now). Passive rooms: minimum = thermostat LOW (12.0). Watch bed_3 next.

## FORM
Custom integration, domain `wiser_predictive`, in this repo. Installed by hand into `/config/custom_components/` on the box while developing; HACS later (already installed on the box).
Replaces the YAML predictor (`pac_predictive_heat`, `predictive_lounge`, automation Predictive Heating).
It REPLACES Boost on Demand and does NOT work with it (Peter, 2026-11-07, restating 2026-11-06): no input, trigger, condition or state of that automation is ever read or relied on, and nothing is designed to complement it. Boost on Demand stays untouched, and active, only until days of charts prove the predictor; then it is retired. A room's own Wiser `is_boosted`/`is_override` flags are Wiser state, not Boost on Demand, and may be read.

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
replay.py           development tool: runs archived history through model.py; --fetch pulls one sensor's history (read-only)
data/               fetched sensor history for the replay (git-ignored)
docs/SPEC.md
docs/HANDOVER.md    session handover (written by /handover)
```
Only files in this layout are in scope.

## SKELETON FIRST (Peter, 2026-11-07)
Approved with a priority change: the integration must be visible inside HA before the model exists, because until now the whole thing has been invisible. The first build is the shell:
- Appears in Settings > Devices & services as "Wiser Predictive", one device, set up by a config flow, settings editable afterwards (options flow).
- `margin` sensors per room are REAL (current reading minus the room's minimum), computed by `model.py`.
- `time_to_minimum` sensors and `heat_needed` exist but report `unknown` until the model is built. They never report a made-up value, and `heat_needed` never reports off while it cannot know.
- Installing it is a box change: `deploy.py` dry run first, `--go` copies files only, `--restart` (HA core restart, needed once for a new integration) only on Peter's go-ahead. The deploy backs up anything it overwrites and writes an apply row for the ledger.

## MODEL (model.py)
DECIDED (AFK, 2026-11-07, from the replay): the MARGIN RULE. The time-to-minimum fits (linear, Newton) are built and tested but SHELVED: on the lounge's 9 touches they said 32-50 min too late at 30 min ahead, worst 150+, so no buffer can be derived from them. They stay in `model.py`; no entity uses them.
Per room, each time its state changes:
1. `margin` = reading minus the room's minimum.
2. `heat_needed` is ON when `margin <= trigger`, OFF when `margin >= trigger + 0.2`, and keeps its state in between (hysteresis).
3. A room that is being heated, boosted or overridden (`is_heating`, `is_boosted`, `is_override`, Wiser's own flags) is OFF: the episode is over.
4. Unknown margin gives unknown, never off.
Derived numbers (replay, 8 days, 9 touches of the lounge minimum): trigger 0.1 °C = one sensor step, the only offset of 0.1-0.4 that caught all 9 touches (13 fires, 4 false alarms, warning 11-120 min, median 71); the 0.2 °C hysteresis = two sensor steps, so a one-step flicker cannot flap it. NO cooldown: with the hysteresis, consecutive fires are never closer than 65 min. Known weakness: two of the 9 touches had warning under 20 min (11 min: a fast fall; 18 min: a target raise). Boost heat-up to +0.3 °C is 6-14 min for a single boost (every boost flag lasts 14-15 min) and 25-28 min when boosts are chained, so those two warnings can be too short.
The thermal-mass options (time near the minimum plus outside temperature; cumulative degree-hours) are NOT built and remain open for testing against the replay.

## ENTITIES
Per room: `sensor.<room>_time_to_minimum` (min), `sensor.<room>_margin` (°C above minimum).
One `binary_sensor.heat_needed`: ON if any room is on; OFF if at least one room is known and none is on; unknown only when every room is unknown (a room with a flat battery must not make it unknown for good). Attributes: per room margin and state, and the rooms that are on.

## CONFIG (config flow, editable in the HA UI)
Hub, rooms, outside sensor (OPTIONAL: the margin rule does not use it; kept for later signals), `trigger_margin` (default 0.1 °C, one sensor step), `announce_script` (optional script entity), `announce_data` (optional object merged into the script's variables, e.g. target and chime for a house with several sites). With no announce script nothing is announced.

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
Announce only. When a room turns ON (never at startup), call the configured `announce_script` with variables `message` ("<room> is <margin> °C above its minimum") plus the user's `announce_data`. In this house that script is `script.speak` with `{target: both, chime: true}`; that is the user's configuration, not code. No cooldown (see MODEL). NO `climate.set_temperature`, no change to Boost on Demand.
Later stages (raise the lounge target; retire Boost on Demand) need their own spec and Peter's go-ahead.

## TESTS AND PROOF
- Unit tests on `model.py` with synthetic series (falling, rising, flat, short window, flicker).
- Replay of the archived history (`../inventory/archive/predictive-*.json`, merged from 2026-10-27; git-ignored there, so cut a small fixture into `tests/`). Report per episode: lead achieved, minimum touched yes/no, false alarms.
- A change is closed only on a test that ran red then green.
- HA-side code (`config_flow.py`, `sensor.py`, `binary_sensor.py`, `hub.py`) runs under a real Home Assistant: `tests/ha/` with pytest-homeassistant-custom-component in a venv (`python -m pytest tests/ha -q -o asyncio_mode=auto`). It is skipped when the harness is not installed. The harness version (2026.2.3 on 2026-11-07) may lag the box (2026.10.4), so code that depends on a newer API (`via_device_id`) is chosen at run time and the newer branch is covered only by a unit test of the choice.

## OUT OF SCOPE
Any box change (needs a dry run, backup, ledger row, Peter's go-ahead). The Wiser integration. The soil-sensor area fix. The `ha-inventory` repo.

## DECIDED (Peter, 2026-11-07)
- Repo: GitHub `pacmac/wiser_predictive`, public.
- Domain and package: `wiser_predictive`, following the repo name. It replaces the draft name `predictive_heating`. Directory is `custom_components/wiser_predictive/`.

## OPEN FOR PETER
- Lead buffer: derived from the replay (proposed default, used unless Peter gives a number).
