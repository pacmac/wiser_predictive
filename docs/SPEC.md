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
  manifest.json
  __init__.py  config_flow.py  sensor.py  binary_sensor.py  strings.json
tests/              pytest on model.py; fixtures cut from the archived history
docs/SPEC.md
```
Only files in this layout are in scope.

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
Outside sensor (default `sensor.ewelink_th01_temperature`, garage roofspace, r 0.88 with forecast, lags 2 h, about 1.4 °C warm), rooms (`climate.wiser_*`), buffer, announce target.
Wiser heating state: `sensor.wiser_heating` (Hub A; NOT `_channel_1`, which is Hub B).

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
