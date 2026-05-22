"""Read TAINILIVE .dat recordings and their (optional) sidecar files."""

from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

# TAINILIVE hardware nominal RF sample rate. The configuration.yaml typically
# emits a rounded/truncated version of this (e.g. 19525, 19531) which is wrong
# at the third decimal place. We always use the hardware-true value.
TAINI_NOMINAL_SAMPLE_FREQUENCY = 19531.25

# Defaults for a standard TAINILIVE 16-channel transmitter. Used when no
# configuration.yaml sidecar is available, or to fill gaps in a partial one.
DEFAULTS = {
    "no_channels": 16,
    "bit_depth": 12,
    "mvolt_range": 13.0,
    "lost_data_symbol": 32767,
    # Prefilter cutoffs vary with decimation; we don't claim a default.
    # The YAML supplies them when present, otherwise we leave them blank
    # unless the caller passes explicit prefilt_hp/prefilt_lp kwargs.
    "prefilt_hp": None,
    "prefilt_lp": None,
    "transmitter_alias": "",
    "transmitter_id": "",
}

_SYNC_LINE = re.compile(r"(\d+)\s+SYNC_(\d+)")

# Signal scaling conventions:
#   "unipolar" — raw 0..2^bit_depth-1 maps to 0..mvolt_range mV (ADC midpoint
#                at +mvolt_range/2). Matches native TAINILIVE EDF exports and
#                any pipeline calibrated to them. This is the default.
#   "bipolar"  — the same signal shifted so the ADC midpoint sits at 0 V,
#                giving a ±mvolt_range/2 mV range. Zero-mean, but differs from
#                native files by a constant +mvolt_range/2 offset.
SCALINGS = ("unipolar", "bipolar")


@dataclass
class Recording:
    signals_uv: np.ndarray  # shape (n_channels, n_samples), float64, microvolts
    sample_frequency: float  # Hz (post-decimation), hardware-true (non-integer)
    event_samples: list[int] = field(default_factory=list)  # raw sample indices
    event_values: list[int] = field(default_factory=list)
    mvolt_range: float = DEFAULTS["mvolt_range"]
    scaling: str = "unipolar"
    transmitter_alias: str = DEFAULTS["transmitter_alias"]
    transmitter_id: str = DEFAULTS["transmitter_id"]
    prefilt_hp: float | None = None
    prefilt_lp: float | None = None
    start_datetime: datetime | None = None

    @property
    def event_times(self) -> list[float]:
        """Event times in seconds, computed at the true (non-integer) rate."""
        return [s / self.sample_frequency for s in self.event_samples]


def _find_transmitter(config: dict, dat_path: Path) -> dict | None:
    """Pick the YAML transmitter entry matching this .dat by filename.

    Returns None if no entry matches. Caller decides whether that's fatal.
    """
    dat_name = dat_path.name
    for tx in config.get("transmitters", []):
        dest = tx.get("output_destination", "")
        if dest and os.path.basename(dest) == dat_name:
            return tx
    return None


def _sidecar_paths(dat_path: Path) -> tuple[Path, Path]:
    """Compute .sync and _configuration.yaml paths for a .dat file.

    Don't use Path.with_suffix — TAINILIVE filenames contain dots in their
    transmitter aliases (e.g. ``b2c3.1_8986``) which trip Path's suffix parser.
    """
    if dat_path.suffix.lower() != ".dat":
        raise ValueError(f"Expected a .dat file, got {dat_path.name!r}")
    base_name = dat_path.name[: -len(dat_path.suffix)]
    return (
        dat_path.parent / f"{base_name}.sync",
        dat_path.parent / f"{base_name}_configuration.yaml",
    )


def load_dat(
    dat_path: str | Path,
    *,
    use_yaml: bool = True,
    use_sync: bool = True,
    no_channels: int | None = None,
    bit_depth: int | None = None,
    mvolt_range: float | None = None,
    decimation: int | None = None,
    nominal_sample_frequency: float = TAINI_NOMINAL_SAMPLE_FREQUENCY,
    lost_data_symbol: int | None = None,
    prefilt_hp: float | None = None,
    prefilt_lp: float | None = None,
    start_datetime: datetime | None = None,
    transmitter_alias: str | None = None,
    transmitter_id: str | None = None,
    scaling: str = "unipolar",
) -> Recording:
    """Load a TAINILIVE .dat recording.

    Sidecar files (``<stem>.sync`` and ``<stem>_configuration.yaml``) are used
    when present, but neither is required: any value the YAML would supply can
    instead be passed as a keyword argument or fall back to a sensible default
    for a standard 16-channel TAINILIVE transmitter.

    ``nominal_sample_frequency`` is treated as a hardware constant — the YAML
    value is ignored (the YAML typically reports a rounded value). Pass an
    explicit kwarg if you need a different rate for non-standard hardware.

    ``decimation`` has no default and must be supplied via the YAML, the kwarg,
    or explicitly — there's no safe guess.

    ``scaling`` selects the signal convention (see :data:`SCALINGS`). The
    default ``"unipolar"`` matches native TAINILIVE EDF exports.
    """
    if scaling not in SCALINGS:
        raise ValueError(f"scaling must be one of {SCALINGS}, got {scaling!r}")
    dat_path = Path(dat_path)
    sync_path, config_path = _sidecar_paths(dat_path)

    # Layer 1: defaults
    params = dict(DEFAULTS)
    params["nominal_sample_frequency"] = nominal_sample_frequency
    params["decimation"] = None
    params["start_datetime"] = None

    # Layer 2: YAML (if found and enabled)
    if use_yaml and config_path.exists():
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        tx = _find_transmitter(config, dat_path)
        if tx is None:
            raise ValueError(
                f"No transmitter in {config_path.name} matches {dat_path.name!r}. "
                f"Available: {[os.path.basename(t.get('output_destination', '')) for t in config.get('transmitters', []) ]}"
            )
        rec_meta = config.get("recording", {})
        for src, dst in (
            ("no_channels", "no_channels"),
            ("bit_depth", "bit_depth"),
            ("mvolt_range", "mvolt_range"),
            ("decimation", "decimation"),
            ("prefilt_hp", "prefilt_hp"),
            ("prefilt_lp", "prefilt_lp"),
            ("alias", "transmitter_alias"),
            ("id", "transmitter_id"),
        ):
            if src in tx and tx[src] is not None:
                params[dst] = tx[src]
        if "lost_data_symbol" in rec_meta:
            params["lost_data_symbol"] = rec_meta["lost_data_symbol"]
        if "start_datetime" in rec_meta:
            sd = rec_meta["start_datetime"]
            if isinstance(sd, datetime):
                params["start_datetime"] = sd
            elif isinstance(sd, str):
                try:
                    params["start_datetime"] = datetime.fromisoformat(sd)
                except ValueError:
                    pass
        # Warn if YAML's nominal sample rate disagrees with our hardware value.
        yaml_nominal = tx.get("nominal_sample_frequency")
        if yaml_nominal and float(yaml_nominal) != nominal_sample_frequency:
            warnings.warn(
                f"YAML reports nominal_sample_frequency={yaml_nominal} but "
                f"using hardware-true {nominal_sample_frequency} Hz instead",
                stacklevel=2,
            )

    # Layer 3: explicit kwargs (highest precedence)
    overrides = {
        "no_channels": no_channels,
        "bit_depth": bit_depth,
        "mvolt_range": mvolt_range,
        "decimation": decimation,
        "lost_data_symbol": lost_data_symbol,
        "prefilt_hp": prefilt_hp,
        "prefilt_lp": prefilt_lp,
        "transmitter_alias": transmitter_alias,
        "transmitter_id": transmitter_id,
        "start_datetime": start_datetime,
    }
    for k, v in overrides.items():
        if v is not None:
            params[k] = v

    if params["decimation"] is None:
        raise ValueError(
            "decimation is required but was not provided by YAML or kwargs. "
            "Pass decimation=<int> (typical TAINILIVE value: 18)."
        )

    sample_frequency = params["nominal_sample_frequency"] / params["decimation"]
    no_channels_v = int(params["no_channels"])
    bit_depth_v = int(params["bit_depth"])
    mvolt_range_v = float(params["mvolt_range"])
    lost_symbol_v = int(params["lost_data_symbol"])

    # TAINILIVE stores 12-bit offset-binary ADC values sign-extended to int16.
    # ``mvolt_range`` is the full peak-to-peak swing in mV, so 1 LSB =
    # mvolt_range / (2^bit_depth - 1). For "unipolar" (native), raw maps
    # directly to 0..mvolt_range. For "bipolar", we subtract the midpoint
    # (2^(bit_depth-1) = 0 V baseline) giving ±mvolt_range/2.
    midpoint = 1 << (bit_depth_v - 1)
    uv_per_lsb = (mvolt_range_v * 1000.0) / ((1 << bit_depth_v) - 1)
    offset = midpoint if scaling == "bipolar" else 0

    raw = np.fromfile(dat_path, dtype="<i2")
    if raw.size % no_channels_v != 0:
        raw = raw[: (raw.size // no_channels_v) * no_channels_v]
    frames = raw.reshape(-1, no_channels_v).T
    lost_mask = frames == lost_symbol_v
    signals_uv = (frames.astype(np.float64) - offset) * uv_per_lsb
    signals_uv[lost_mask] = 0.0

    event_samples: list[int] = []
    event_values: list[int] = []
    if use_sync and sync_path.exists():
        with open(sync_path, "r") as f:
            for line in f:
                m = _SYNC_LINE.search(line)
                if m:
                    event_samples.append(int(m.group(1)))
                    event_values.append(int(m.group(2)))

    return Recording(
        signals_uv=signals_uv,
        sample_frequency=sample_frequency,
        event_samples=event_samples,
        event_values=event_values,
        mvolt_range=mvolt_range_v,
        scaling=scaling,
        transmitter_alias=str(params["transmitter_alias"] or ""),
        transmitter_id=str(params["transmitter_id"] or ""),
        prefilt_hp=params["prefilt_hp"],
        prefilt_lp=params["prefilt_lp"],
        start_datetime=params["start_datetime"],
    )
