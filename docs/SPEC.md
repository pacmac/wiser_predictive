# wiser_predictive — SPEC v2 (DRAFT for approval, 2026-11-07)

Replaces SPEC v1 (in git history). v1 built a margin threshold ("heat needed when the reading is within 0.1 °C of the minimum") and called it predictive. Peter: that is an automation he can write in one line; it is a white elephant. This spec is what he asked for. Task: `predictive-integration`.

## GOAL
Predictive heating: use the inside and outside temperature AND THE RATE OF CHANGE of both, plus the weather forecast, to decide if and when to demand heat BEFORE a room falls so low that recovering it wastes energy (the fabric has cooled). It replaces Boost on Demand, which only stops short cycling.
It must be possible to LOOK at it: see a cold front coming in, see the room curves bend down faster, and see the action taken. Without that nobody can tell whether it is doing anything or whether the logic is right (Peter, 2026-11-07). **The visualisation is a first-class deliverable, not a later nicety. A stage is not done until its chart has been looked at.**

## HOW THE HEATING WORKS (facts Peter gave; verify before relying on them)
- Wiser rooms are mostly PASSIVE: they take free heat whenever water is circulating and the room is below its HIGH. One room (here the lounge) is ACTIVE and is the one that demands heat. Not every room can be passive; someone has to call.
- Whether a passive room below its LOW calls for heat by itself is DISPUTED (Peter believes yes; Wiser forum reports say no). It has never been tested here: no passive room came within 0.7 °C of its LOW in 8 days. The predictor must not depend on it: the active room is the lever.
- Boost on Demand exists to stop short cycling: the thermostats sit on the valves, warm up quickly, and the firmware gives no usable hysteresis. The predictor must therefore decide WHEN to start a heat call and HOW LONG to hold it (long runs, no cycling), so it replaces that job too.
- The room reading comes from valve-mounted iTRVs and is biased by the radiator: the lounge's two iTRVs read 17.9 and 19.1 at the same moment; the room figure (18.5) is a mix. A reading taken while the radiator is hot is not the room air. The model must learn cooling only from periods when the valves are closed, and treat heat-on readings separately. A separate air sensor away from the radiator would be better; that is Peter's hardware decision.
- Wiser publishes per-room and per-channel heating demand (%, the "LTS" sensors). The predictor's own demand is expressed the same way so the two can be drawn on one axis and compared.

## WHAT IT DECIDES
Per room, continuously: given the room's measured temperature and rate, the outside temperature and its forecast ramp, how long until the room reaches its minimum if nothing is done (`time_to_minimum`), how long a heat call needs to take effect and to recover (`lead`: dead time + recovery), and therefore the latest safe moment to demand heat. Across rooms: demand heat when the earliest room says so; the others take the free heat. Output is a planned demand over the next 24 h, not just a yes/no now.

## MODEL
Per room, first order (RC): `dT/dt = (T_out(t) − T) / τ + g·u(t)`, with `u` the heat supplied (0 with the valves closed). `T_out(t)` is the measured outside temperature now and the hourly forecast ahead, so a cold front (a steep falling ramp) shortens `time_to_minimum`. Learned per room from history:
- `τ`, the cooling time constant: from valves-closed periods only.
- `g` and the dead time: from heat-up periods (boosts and boiler runs).
- the sensor's radiator bias while heating (see above).
Every number is fitted or derived from the data, and the derivation is recorded beside it. No default entity ids, no house values in code.
The minimum for a passive room is its LOW. The active room has no LOW: its minimum is a number the user sets in the options form (no default), because its target follows the schedule (lounge: 19.0, then 17.0, overnight 12.5–13.0).
The v1 cooling fits (`predict_linear`, `predict_newton`) were a weak test: one outside value, a short window, a biased sensor. They are a starting point only.
Honesty rule: it reports `unknown` when it cannot know (not enough cooling history, no forecast), never a made-up value, and it shows its confidence.

## VISUALISATION (critical)
One chart per room (the active room first), x-axis from 3 days back to 24 h ahead, with a "now" line, panels sharing the axis:
1. **Temperature.** Measured room temperature (and each iTRV), the room's minimum as a line, the predicted curve for the next 24 h (dashed, with an uncertainty band), and, faint, the prediction made 6 h ago against what happened (so accuracy is visible).
2. **Outside.** Measured outside temperature and the forecast (dashed) on the same time axis; the cold front is the steep part.
3. **Rate of change.** dT/dt in °C/h for the room and for the outside, on their own axis. The rate matters as much as the temperature.
4. **Demand.** Wiser's actual heating demand (%) for the room and the predictor's planned demand (%) on one axis, with shaded heat calls.
5. **Decision trace.** `time_to_minimum` and `lead` over time, so the moment the logic fires is the moment the first falls below the second. Each action is marked on the chart with its reason in words ("forecast outside falling 1.4 °C/h, lounge reaches its minimum in 2 h 10 min, heat call needs 45 min").
THE CHART AND ITS SUMMARY ARE PART OF THE INTEGRATION (Peter, 2026-11-07: "these stats / charts should be part of the integration"). It is a sidebar panel registered by the integration itself ("Predictive Heating"), so it needs no HACS card, works in any house, and shows live data. It reads the recorder history, the weather forecast and the model's own output through Home Assistant, using the viewer's own login. Nothing about it is specific to one house: the rooms and sensors come from the config entry.
What it shows is deliberately little (Peter: the first four-panel version was "information overload"): a summary in words at the top (inside now and over the window, outside now and over the window, how often and when the heating came on, and from stage 1 what the predictor says and why), then two panels on one time axis, inside and outside, with the heating periods shaded and labelled, and, from stage 1, the predicted curve and the moment heat is called. Anything more (rates, valve sensors, demand) appears only when the model uses it, and is explained in words when it does.
`chart.py` and `chart_template.html` are the development preview of the same page, built from `replay.py --fetch` history, so the design can be looked at before it is installed. The panel is built from that template, not a second design.
Acceptance: Peter looks at the chart on the Home Assistant sidebar and can say whether the logic fired when it should.

## AI LAYER (optional, later)
The real-time decision is the deterministic model: it must not wait on an API call or fail when the internet does. A Claude script is used for periodic review: it reads the model's fitted parameters, the log of what was predicted against what happened and the forecast, then explains misses, flags a bad fit, and proposes parameter changes that Peter approves. It is never in the control loop.

## WHAT IS KEPT FROM v1
The framework: hub selection (auto if one, user picks if several), room discovery from the selected hub, config and options flow, device and entity setup, `deploy.py` (dry run, backup, hash check, separate restart), the HA test harness, `replay.py` and its archive loading, the boost and schedule-step handling in `MinimumMemory`. Nothing is hard-coded for one house.
**Scrapped or replaced:** the margin threshold as the decision; "Heat needed within 0.1 °C" and the announcement keyed to it; the `time_to_minimum` placeholders (removed already).

## STAGES
0. Replay chart preview (read-only, nothing on the box). Done as a preview; Peter found the first version unreadable and the second is cut to inside, outside and heating.
1. The panel in the integration, with the stage 0 content live from the recorder and the forecast: summary in words, inside and outside panels, heating shaded. No model yet. Needs a deploy and a restart (Peter's go-ahead). Gate: Peter looks at it in the Home Assistant sidebar.
2. Model fitted and measured in the replay against the history (more fetched with `--fetch`), then its predicted curve, the call moment and the reason in words added to the panel, and published as entities (planned demand). Announce only; no thermostat changes. Gate: lead and accuracy shown on the chart, and Peter looks at it live for several days.
3. Act on the active room (a boost or setpoint through its lever), replacing Boost on Demand. Needs its own go-ahead and a plan to retire Boost on Demand.

## OUT OF SCOPE
Any box change without a dry run, backup, ledger row and Peter's go-ahead. The Wiser integration itself. The `ha-inventory` repo.

## OPEN FOR PETER
- (Decided: the chart is a panel bundled in the integration; see VISUALISATION.)
- The active room's minimum: a number you set. What is the lounge's?
- A separate air sensor in the lounge (off the radiator) would give the model an honest signal; worth adding?
- Outside source: `weather.forecast_home` (forecast and current) rather than a local sensor; the box entry's outside sensor currently points at a sensor named "Plant Dryer Temperature". Confirm.
