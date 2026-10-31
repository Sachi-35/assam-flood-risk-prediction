#!/usr/bin/env python
"""Run the whole pipeline in order.   python scripts/run_pipeline.py [--config X] [--skip-download] [--no-gauge]

Step 02 (rainfall download) only runs with --download; you already have rainfall files.
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script, *extra):
    cmd = [sys.executable, str(HERE / script), *extra]
    print(f"\n=== {' '.join(Path(c).name if i < 2 else c for i, c in enumerate(cmd))}")
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--download", action="store_true", help="also run step 02 (download CHIRPS/IMD); not needed if you have the files")
    ap.add_argument("--skip-download", action="store_true", help="(kept for compatibility; download is off by default)")
    ap.add_argument("--no-gauge", action="store_true", help="(gauge data is optional; absent data is skipped automatically)")
    ap.add_argument("--no-compare", action="store_true", help="skip step 10 (offline model comparison; seasonal mode only)")
    ap.add_argument("--reference-dir", default=None, help="backend data/ folder for the export diff")
    a = ap.parse_args()
    c = ["--config", a.config] if a.config else []

    run("00_inspect_inputs.py", *c)
    run("01_prepare_boundaries.py", *c)
    if a.download:
        run("02_download_rainfall.py", *c)
    run("03_extract_rainfall.py", *c)
    run("04_process_gauge.py", *c, *(["--skip"] if a.no_gauge else []))
    run("05_extract_static.py", *c)
    run("06_prepare_labels.py", *c)
    run("07_build_features.py", *c)
    run("11_reference_period_check.py", *c)
    run("08_quality_report.py", *c)
    run("09_export_for_backend.py", *c, *(["--reference-dir", a.reference_dir] if a.reference_dir else []))
    if not a.no_compare:
        run("10_compare_models.py", *c)
    print("\nPipeline finished. Read reports/data_quality.md before training anything.")


if __name__ == "__main__":
    main()
