# tainitec-data-tools

Convert TAINILIVE `.dat` recordings into EDF+ files.

## Install

Requires Python 3.9 or newer. Create a virtual environment, activate it, then
install:

```sh
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install .
```

All other dependencies (numpy, pyEDFlib, PyYAML) install automatically. Verify
with:

```sh
dat2edf --help
```

## Quick start

```sh
# Typical case: .dat plus matching .sync and _configuration.yaml in the same dir
dat2edf recording.dat recording.edf

# When you only have the .dat (and optionally .sync), no YAML:
dat2edf --no-yaml --decimation 18 recording.dat recording.edf

# Fully manual override:
dat2edf --no-yaml --decimation 18 --channels 16 --bit-depth 12 \
        --mvolt-range 13 --alias my_transmitter \
        --start "2025-04-01 10:35:32" \
        --prefilt-hp 0.35 --prefilt-lp 500 \
        recording.dat recording.edf
```

Sidecar files, when used, must share the `.dat` basename:

- `recording.dat`
- `recording.sync`
- `recording_configuration.yaml`

## What's in the output EDF+

- 16-bit EDF+ with one signal per channel, labelled `EEG 0`...`EEG N-1`.
- Signals are in **millivolts (mV)** in a bipolar range `±mvolt_range / 2 mV`
  (e.g. ±6.5 mV for the default 13 mV peak-to-peak ADC), centred so the
  ADC midpoint corresponds to 0 V — i.e. the signal is zero-mean relative
  to the ADC baseline, not offset like the native EDF export.
- Lost-data samples (sentinel `32767`) are written as `0 mV`.
- `.sync` events become instantaneous EDF+ annotations of the form
  `SYNC_<value>`, aligned to the exact sample index in the EDF (no drift
  relative to the brain signal, regardless of recording length).
- Transducer field: `TAINI <id>` when the transmitter ID is known (from
  YAML or `--transmitter-id`), blank otherwise.
- Equipment field: `TAINILIVE_<alias>`. Start datetime from the YAML if
  available, otherwise from `--start` or the current time.
- Prefilter field is filled from the YAML or `--prefilt-*` flags. It is left
  blank when neither is supplied — cutoffs vary with decimation, so no
  default is assumed.

The EDF sample rate is the nearest integer to `nominal / decimation` Hz
(e.g. `19531.25 / 18 → 1085 Hz` for the standard setup).

## All CLI options

```
--no-yaml                       ignore any _configuration.yaml sidecar
--no-sync                       ignore any .sync sidecar
--channels N                    default 16
--bit-depth N                   default 12
--mvolt-range mV                default 13
--decimation N                  required when --no-yaml
--nominal-rate Hz               default 19531.25 (hardware constant)
--lost-data-symbol N            default 32767
--prefilt-hp Hz                 analog prefilter HP cutoff
--prefilt-lp Hz                 analog prefilter LP cutoff
--alias NAME                    transmitter alias for EDF Equipment field
--transmitter-id N              transmitter numeric ID for EDF Transducer field
--start "YYYY-MM-DD HH:MM:SS"   recording start datetime
```

When YAML is present its values are used; explicit flags override either the
YAML or the built-in defaults. `--nominal-rate` defaults to TAINILIVE's
hardware-true 19531.25 Hz — the YAML's value for this field is ignored even
when present (the YAML reports a rounded value).

## Library use

```python
from tainitec_data_tools import dat_to_edf

# With sidecars
dat_to_edf("recording.dat", "recording.edf")

# Without configuration.yaml
dat_to_edf("recording.dat", "recording.edf", use_yaml=False, decimation=18)
```

## Troubleshooting

> `ValueError: decimation is required but was not provided by YAML or kwargs`

You ran with `--no-yaml` (or the `.dat` has no sidecar yaml) but did not pass
`--decimation`. The decimation factor is recording-specific and cannot be
inferred from the `.dat` alone. Pass it explicitly, e.g. `--decimation 18`.

> `ValueError: No transmitter in <yaml> matches <filename>`

The YAML next to your `.dat` lists multiple transmitters and none of their
`output_destination` filenames match the `.dat` filename — usually because
the `.dat` was renamed or moved away from its original folder. Either fix the
filename or run with `--no-yaml --decimation 18` (plus any other relevant
flags).

> `UserWarning: YAML reports nominal_sample_frequency=19525 but using
> hardware-true 19531.25 Hz instead`

Expected. The TAINILIVE YAML records a rounded value for the RF sample rate;
the true hardware rate is 19531.25 Hz, which is what the tool uses. Pass
`--nominal-rate` only if you actually have non-standard hardware.

## Development

This repo has no `flake.nix`. If you use Nix, a generic Python devshell is
available from [`nix-dev`](https://github.com/stuartbowyer/nix-dev):

```sh
nix develop github:stuartbowyer/nix-dev#python311
pytest
```

Otherwise, a plain venv works:

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
