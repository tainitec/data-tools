"""Write TAINILIVE recordings out as EDF+ files."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pyedflib

from tainitec_data_tools.dat import Recording


def write_edf_plus(recording: Recording, edf_path: str | Path) -> None:
    """Write a Recording to disk as an EDF+ file.

    Signals are stored in millivolts (mV) with 16-bit digital encoding, in a
    bipolar range of ±mvolt_range mV centred on 0 V. Sync events are written
    as instantaneous EDF+ annotations of the form ``SYNC_<value>``, aligned
    to the integer EDF sample index of their original .sync sample number.

    EDF requires an integer number of samples per record; TAINILIVE's
    decimated rate (e.g. 19531.25/18 ≈ 1085.07 Hz) is not integer, so the
    rate is rounded to the nearest integer for EDF storage.
    """
    edf_path = Path(edf_path)
    signals_uv = recording.signals_uv
    n_channels, n_samples = signals_uv.shape

    prefilter_str = ""
    if recording.prefilt_hp is not None and recording.prefilt_lp is not None:
        prefilter_str = f"HP:{recording.prefilt_hp}Hz LP:{recording.prefilt_lp}Hz"

    start_dt = recording.start_datetime or datetime.now()

    # EDF unit is mV (matches native TAINILIVE exports). Internal Recording
    # holds uV, so divide by 1000 when serialising. The ADC's mvolt_range
    # is peak-to-peak, so the bipolar range is half that on each side.
    phys_max = recording.mvolt_range / 2.0
    phys_min = -phys_max
    edf_sample_frequency = int(round(recording.sample_frequency))

    transducer_str = (
        f"TAINI {recording.transmitter_id}" if recording.transmitter_id else ""
    )

    n_records_approx = max(1, math.ceil(n_samples / edf_sample_frequency))
    events_per_record = len(recording.event_samples) / n_records_approx
    n_annot_signals = max(1, min(64, math.ceil(events_per_record) + 1))

    writer = pyedflib.EdfWriter(
        str(edf_path),
        n_channels=n_channels,
        file_type=pyedflib.FILETYPE_EDFPLUS,
    )
    try:
        writer.set_number_of_annotation_signals(n_annot_signals)
        writer.setStartdatetime(start_dt)
        alias = recording.transmitter_alias or "unknown"
        writer.setEquipment(f"TAINILIVE_{alias}".replace(" ", "_").strip("_"))

        headers = [
            {
                "label": f"EEG {ch}",
                "dimension": "mV",
                "sample_frequency": edf_sample_frequency,
                "physical_min": phys_min,
                "physical_max": phys_max,
                "digital_min": -32768,
                "digital_max": 32767,
                "transducer": transducer_str,
                "prefilter": prefilter_str,
            }
            for ch in range(n_channels)
        ]
        writer.setSignalHeaders(headers)
        # Compute annotation times against the integer EDF sample rate so each
        # annotation lands on the exact EDF sample index of its original .sync
        # sample number. (Annotations must be queued *before* writeSamples;
        # pyedflib drops anything queued after.)
        for s, v in zip(recording.event_samples, recording.event_values):
            writer.writeAnnotation(s / edf_sample_frequency, -1, f"SYNC_{v}")
        writer.writeSamples(
            [np.ascontiguousarray(s / 1000.0) for s in signals_uv]
        )
    finally:
        writer.close()
