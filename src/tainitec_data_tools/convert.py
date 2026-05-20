"""High-level conversion entry point."""

from __future__ import annotations

from pathlib import Path

from tainitec_data_tools.dat import load_dat
from tainitec_data_tools.edf import write_edf_plus


def dat_to_edf(
    dat_path: str | Path,
    edf_path: str | Path,
    **load_kwargs,
) -> None:
    """Convert a TAINILIVE .dat recording to an EDF+ file.

    Any keyword arguments are forwarded to :func:`load_dat`, so callers can
    skip the YAML sidecar (``use_yaml=False``), override individual parameters
    (e.g. ``decimation=18``), or both.
    """
    recording = load_dat(dat_path, **load_kwargs)
    write_edf_plus(recording, edf_path)
