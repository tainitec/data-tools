"""Round-trip tests: synthesise tiny TAINILIVE recordings, convert, read back."""

from __future__ import annotations

import numpy as np
import pyedflib
import pytest
import yaml

from tainitec_data_tools import dat_to_edf
from tainitec_data_tools.dat import (
    TAINI_NOMINAL_SAMPLE_FREQUENCY,
    load_dat,
)


N_CHANNELS = 16
BIT_DEPTH = 12
MVOLT_RANGE = 13
DECIMATION = 18
NOMINAL_SF = TAINI_NOMINAL_SAMPLE_FREQUENCY
SF = NOMINAL_SF / DECIMATION  # ~1085.07 Hz
MIDPOINT = 1 << (BIT_DEPTH - 1)


def _write_synthetic_dat(dat_path, n_samples_per_channel):
    """Channel k holds raw value midpoint + k*10, with two lost samples on ch0."""
    frames = np.full((n_samples_per_channel, N_CHANNELS), MIDPOINT, dtype="<i2")
    for ch in range(N_CHANNELS):
        frames[:, ch] = MIDPOINT + ch * 10
    frames[100, 0] = 32767
    frames[200, 0] = 32767
    frames.tofile(dat_path)


def _write_synthetic_yaml(yaml_path, dat_name):
    config = {
        "transmitters": [
            {
                "id": 9999,
                "alias": "test",
                "output_destination": f"/somewhere/{dat_name}",
                "decimation": DECIMATION,
                "nominal_sample_frequency": 19525,  # intentionally wrong; we override
                "no_channels": N_CHANNELS,
                "bit_depth": BIT_DEPTH,
                "mvolt_range": MVOLT_RANGE,
                "prefilt_lp": 500,
                "prefilt_hp": 0.35,
            }
        ],
        "recording": {
            "start_datetime": "2025-01-01 12:00:00",
            "lost_data_symbol": 32767,
        },
    }
    yaml_path.write_text(yaml.safe_dump(config))


def _write_synthetic_sync(sync_path):
    sync_path.write_text("# header\n0 SYNC_0\n543 SYNC_1\n1086 SYNC_0\n")


@pytest.fixture
def with_yaml(tmp_path):
    dat = tmp_path / "TAINI_TEST_0000.dat"
    n = int(SF * 4)  # ~4 seconds
    _write_synthetic_dat(dat, n)
    _write_synthetic_yaml(tmp_path / "TAINI_TEST_0000_configuration.yaml", dat.name)
    _write_synthetic_sync(tmp_path / "TAINI_TEST_0000.sync")
    return dat, n


@pytest.fixture
def no_yaml(tmp_path):
    dat = tmp_path / "TAINI_TEST_0000.dat"
    n = int(SF * 4)
    _write_synthetic_dat(dat, n)
    _write_synthetic_sync(tmp_path / "TAINI_TEST_0000.sync")
    return dat, n


# mvolt_range is peak-to-peak, so 1 LSB = mvolt_range / (2^bit_depth - 1).
UV_PER_LSB = (MVOLT_RANGE * 1000.0) / ((1 << BIT_DEPTH) - 1)


def test_dat_deinterlaces_unipolar_default(with_yaml):
    """Default scaling is unipolar: raw maps directly (no midpoint subtraction)."""
    dat, _ = with_yaml
    rec = load_dat(dat)
    assert rec.scaling == "unipolar"
    assert rec.signals_uv.shape[0] == N_CHANNELS
    assert rec.sample_frequency == pytest.approx(SF)
    for ch in range(N_CHANNELS):
        # raw value is midpoint + ch*10, mapped directly to uV.
        np.testing.assert_allclose(
            rec.signals_uv[ch, 50], (MIDPOINT + ch * 10) * UV_PER_LSB
        )
    assert rec.signals_uv[0, 100] == 0.0
    assert rec.signals_uv[0, 200] == 0.0


def test_dat_deinterlaces_bipolar_centers(with_yaml):
    """Bipolar scaling subtracts the midpoint, so the baseline is 0 uV."""
    dat, _ = with_yaml
    rec = load_dat(dat, scaling="bipolar")
    assert rec.scaling == "bipolar"
    for ch in range(N_CHANNELS):
        np.testing.assert_allclose(rec.signals_uv[ch, 50], ch * 10 * UV_PER_LSB)
    assert rec.signals_uv[0, 100] == 0.0


def test_invalid_scaling_rejected(with_yaml):
    dat, _ = with_yaml
    with pytest.raises(ValueError, match="scaling"):
        load_dat(dat, scaling="nonsense")


def test_yaml_nominal_sample_rate_is_overridden(with_yaml):
    """Even though the YAML says 19525, the hardware-true 19531.25 wins."""
    dat, _ = with_yaml
    with pytest.warns(UserWarning, match="nominal_sample_frequency"):
        rec = load_dat(dat)
    assert rec.sample_frequency == pytest.approx(NOMINAL_SF / DECIMATION)


def test_sync_events_parsed(with_yaml):
    dat, _ = with_yaml
    rec = load_dat(dat)
    assert rec.event_values == [0, 1, 0]
    assert rec.event_samples == [0, 543, 1086]
    # event_times property is derived using the hardware-true rate.
    np.testing.assert_allclose(
        rec.event_times,
        [0 / SF, 543 / SF, 1086 / SF],
    )


def test_edf_annotations_align_with_sample_indices(with_yaml, tmp_path):
    """Every SYNC annotation must land on the exact integer EDF sample index
    of its original .sync sample number — no rate-rounding drift."""
    dat, _ = with_yaml
    out = tmp_path / "out.edf"
    dat_to_edf(dat, out)
    r = pyedflib.EdfReader(str(out))
    try:
        edf_sf = r.getSampleFrequency(0)
        onsets, _, labels = r.readAnnotations()
        sync_onsets = [
            float(o) for o, l in zip(onsets, labels) if l.startswith("SYNC_")
        ]
        # Original .sync sample numbers were 0, 543, 1086.
        expected_idx = [0, 543, 1086]
        recovered_idx = [round(o * edf_sf) for o in sync_onsets]
        assert recovered_idx == expected_idx
    finally:
        r.close()


def test_load_dat_without_yaml_requires_decimation(no_yaml):
    dat, _ = no_yaml
    with pytest.raises(ValueError, match="decimation"):
        load_dat(dat)


def test_load_dat_without_yaml_uses_defaults_plus_decimation(no_yaml):
    dat, _ = no_yaml
    rec = load_dat(dat, decimation=DECIMATION)
    assert rec.signals_uv.shape[0] == N_CHANNELS
    assert rec.sample_frequency == pytest.approx(SF)
    # Defaults filled in
    assert rec.mvolt_range == 13.0
    # Prefilter values vary with decimation, so we don't claim a default —
    # they stay None unless YAML provides them or the caller passes kwargs.
    assert rec.prefilt_hp is None
    assert rec.prefilt_lp is None
    # Sync still found and parsed
    assert rec.event_values == [0, 1, 0]


def test_load_dat_without_yaml_accepts_explicit_prefilters(no_yaml):
    dat, _ = no_yaml
    rec = load_dat(dat, decimation=DECIMATION, prefilt_hp=0.35, prefilt_lp=500.0)
    assert rec.prefilt_hp == 0.35
    assert rec.prefilt_lp == 500.0


def test_explicit_kwargs_override_yaml(with_yaml):
    dat, _ = with_yaml
    rec = load_dat(dat, mvolt_range=26.0, transmitter_alias="custom")
    assert rec.mvolt_range == 26.0
    assert rec.transmitter_alias == "custom"


def test_dat_to_edf_with_yaml(with_yaml, tmp_path):
    dat, _ = with_yaml
    out = tmp_path / "out.edf"
    dat_to_edf(dat, out)
    r = pyedflib.EdfReader(str(out))
    try:
        assert r.signals_in_file == N_CHANNELS
        assert r.getSampleFrequency(0) == pytest.approx(round(SF))
        # EDF unit is mV to match native TAINILIVE exports.
        assert r.getPhysicalDimension(0).strip() == "mV"
        # Default unipolar range is 0..mvolt_range (matches native exports).
        assert r.getPhysicalMaximum(0) == pytest.approx(MVOLT_RANGE)
        assert r.getPhysicalMinimum(0) == pytest.approx(0.0)
        # Channel labels: 'EEG <ch>' (zero-indexed), matching native exports.
        assert r.getLabel(0).strip() == "EEG 0"
        assert r.getLabel(N_CHANNELS - 1).strip() == f"EEG {N_CHANNELS - 1}"
        # Transducer carries the transmitter ID from the YAML.
        assert r.getTransducer(0).strip() == "TAINI 9999"
        _, _, labels = r.readAnnotations()
        assert [l for l in labels if l.startswith("SYNC_")] == [
            "SYNC_0",
            "SYNC_1",
            "SYNC_0",
        ]
    finally:
        r.close()


def test_dat_to_edf_bipolar_range(with_yaml, tmp_path):
    dat, _ = with_yaml
    out = tmp_path / "out.edf"
    dat_to_edf(dat, out, scaling="bipolar")
    r = pyedflib.EdfReader(str(out))
    try:
        # Bipolar range is ±mvolt_range/2 since mvolt_range is peak-to-peak.
        assert r.getPhysicalMaximum(0) == pytest.approx(MVOLT_RANGE / 2)
        assert r.getPhysicalMinimum(0) == pytest.approx(-MVOLT_RANGE / 2)
    finally:
        r.close()


def test_dat_to_edf_without_yaml(no_yaml, tmp_path):
    dat, _ = no_yaml
    out = tmp_path / "out.edf"
    dat_to_edf(dat, out, decimation=DECIMATION)
    r = pyedflib.EdfReader(str(out))
    try:
        assert r.signals_in_file == N_CHANNELS
        assert r.getSampleFrequency(0) == pytest.approx(round(SF))
        # No YAML → start_datetime falls back to "now"; just confirm it exists.
        assert r.getStartdatetime() is not None
        # Without YAML or --transmitter-id, transducer is blank.
        assert r.getTransducer(0).strip() == ""
    finally:
        r.close()


def test_dat_to_edf_explicit_transmitter_id(no_yaml, tmp_path):
    dat, _ = no_yaml
    out = tmp_path / "out.edf"
    dat_to_edf(dat, out, decimation=DECIMATION, transmitter_id="1024")
    r = pyedflib.EdfReader(str(out))
    try:
        assert r.getTransducer(0).strip() == "TAINI 1024"
    finally:
        r.close()
