"""Command-line entry point: ``dat2edf INPUT.dat OUTPUT.edf``."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from tainitec_data_tools.convert import dat_to_edf
from tainitec_data_tools.dat import TAINI_NOMINAL_SAMPLE_FREQUENCY


def _parse_datetime(value: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Invalid datetime {value!r}; expected ISO format like '2025-04-01 10:35:32'"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dat2edf",
        description=(
            "Convert a TAINILIVE .dat recording to EDF+. If a matching "
            "_configuration.yaml is found alongside the .dat it is used; "
            "otherwise defaults for a standard 16-channel TAINILIVE "
            "transmitter are assumed and --decimation must be supplied."
        ),
    )
    parser.add_argument("input", help="Path to the input .dat file")
    parser.add_argument("output", help="Path to write the output .edf file")

    parser.add_argument(
        "--no-yaml",
        action="store_true",
        help="Ignore any _configuration.yaml sidecar.",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Ignore any .sync sidecar (no events in output).",
    )
    parser.add_argument("--channels", type=int, help="Number of channels (default: 16)")
    parser.add_argument("--bit-depth", type=int, help="ADC bit depth (default: 12)")
    parser.add_argument(
        "--mvolt-range",
        type=float,
        help="Peak ADC range in mV (default: 13)",
    )
    parser.add_argument(
        "--decimation",
        type=int,
        help="Decimation factor. Required if no YAML is found.",
    )
    parser.add_argument(
        "--nominal-rate",
        type=float,
        default=TAINI_NOMINAL_SAMPLE_FREQUENCY,
        help=f"Pre-decimation RF sample rate in Hz (default: {TAINI_NOMINAL_SAMPLE_FREQUENCY})",
    )
    parser.add_argument(
        "--lost-data-symbol",
        type=int,
        help="Sentinel value for lost samples (default: 32767)",
    )
    parser.add_argument(
        "--prefilt-hp",
        type=float,
        help="High-pass cutoff of the analog prefilter in Hz (decimation-dependent; "
        "left blank in EDF when not provided)",
    )
    parser.add_argument(
        "--prefilt-lp",
        type=float,
        help="Low-pass cutoff of the analog prefilter in Hz (decimation-dependent; "
        "left blank in EDF when not provided)",
    )
    parser.add_argument("--alias", help="Transmitter alias for EDF Equipment field")
    parser.add_argument(
        "--transmitter-id",
        help="Transmitter numeric ID for EDF Transducer field (e.g. 1023)",
    )
    parser.add_argument(
        "--start",
        type=_parse_datetime,
        help="Recording start datetime (default: now if YAML absent)",
    )

    args = parser.parse_args(argv)

    dat_to_edf(
        args.input,
        args.output,
        use_yaml=not args.no_yaml,
        use_sync=not args.no_sync,
        no_channels=args.channels,
        bit_depth=args.bit_depth,
        mvolt_range=args.mvolt_range,
        decimation=args.decimation,
        nominal_sample_frequency=args.nominal_rate,
        lost_data_symbol=args.lost_data_symbol,
        prefilt_hp=args.prefilt_hp,
        prefilt_lp=args.prefilt_lp,
        transmitter_alias=args.alias,
        transmitter_id=args.transmitter_id,
        start_datetime=args.start,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
