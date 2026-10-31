# Phase-response project

Goal: for ADC1, the 1PPS rises are centered precisely on the UTC second, plus only the delay of the analog
anti-aliasing filter (the firmware already corrects for the sinc3 window center and 0.254 ms DRDY overhead).
ADC1 currently has no analog filter, so the target there is an offset of about 0. ADC2-4 have a 2nd-order RC at
48.25 Hz per stage, fully passive (no buffer), stage-2 impedance 10x stage 1 (the report's default model; it fits the
observed edge shape better than a buffered one).
ADCs 2-4 run on independent internal clocks and are expected to be inconsistent (several ms of offset and scatter);
that gets fixed later with an external clock for all ADCs, so track them but don't chase them yet.

## Setup
- Hardware: ordinary aspen, TCXO, newest firmware; analog inputs fed by 1PPS from a PA6H GPS module.
- Firmware source: `~/Work/aspen-firmware` (timing code: `src/adc_timing.h`, `src/sample_retimer.h`). Don't edit
  firmware unless asked; propose the change and the test that will show it worked.
- Channel map (default CONFIG.TXT): HDF=ADC1, EHZ=ADC2, EHN=ADC3, EHE=ADC4.

## Test data
- One folder per run in this directory: `YYYY-MM-DD_FW<version>_<setup note>`, e.g. `2026-10-30_FW0860_deck_PPS`.
  Put the CONFIG.TXT used in the folder. The build string is the `#Firmware` line of the logs (a folder can mix builds
  if the logger was reflashed; `pps_phase.py` lists them).
- Data folders are the user's; never delete or rename them. Write analysis output to the scratchpad, or to
  `<run folder>/analysis/` only when the user wants it kept.
- `RESULTS.md` is the running table, one row per run: update it after each analyzed run.

## Workflow for each new firmware build
1. Phase check: the `aspen-phase-response` skill (run `--self-test` first), then `pps_report.py` to write
   `phase_response_report.pdf` into the test folder. Look at the pages, and report ADC1 offset median and std in ms.
2. Regression check: the `aspen-log-review` skill on the same folder (sample timing, GPS cycling, drift, I2C,
   data continuity). A phase improvement that breaks any of these isn't progress.
3. Regression comparison: `pps_compare.py <previous folder> <new folder>` (same sample rate and rig), and compare to the
   previous row(s) in RESULTS.md, state what changed in the firmware between the builds
   (`git -C ~/Work/aspen-firmware log`), and add the row.
4. Say plainly if a run is too short or has too few GPS-locked pulses to conclude anything.

## Conventions
- Offsets in ms, sign as in the skill (negative = recorded step later than the second). Always give n and std with a
  median.
- Python: use the `gemdev` conda env. Keep reusable analysis code in the skill's `scripts/pps_phase.py`, not in
  ad-hoc copies here; one-off exploration goes in the scratchpad.
