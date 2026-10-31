#!/usr/bin/env python
"""Step 6a (OPTIONAL, label source): download ASDMA daily flood-report PDFs and parse the district-wise
'Population and Crop Area affected' table into data/raw/labels/asdma_affected.csv.

    python scripts/06a_fetch_asdma_reports.py --start 2019-05-01 --end 2023-10-31

Only the monsoon season is worth fetching (reports exist when floods are active).
Parsing is best-effort: spot-check several dates against the PDFs (see src/floodprep/asdma.py).
Add --parse-only to re-parse already downloaded PDFs without touching the network.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodprep import asdma
from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config

log = get_logger("06a_asdma")


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--parse-only", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)
    labels_dir = ensure_dir(cfg["paths"]["raw"] / "labels")
    pdf_dir = ensure_dir(labels_dir / "asdma_pdfs")

    if not args.parse_only:
        start = date.fromisoformat(args.start or cfg["project"]["start_date"])
        end = date.fromisoformat(args.end or cfg["project"]["end_date"])
        files = asdma.download_reports(start, end, pdf_dir, log=log.info)
        log.info(f"{len(files)} PDFs available in {pdf_dir}")

    df = asdma.parse_folder(pdf_dir, log=log.info)
    if df.empty:
        sys.exit("Nothing parsed. If PDFs exist, the layout may differ from what asdma.py expects.")
    out = labels_dir / "asdma_affected.csv"
    df.to_csv(out, index=False)
    log.info(f"Parsed {df['date'].nunique()} report days, {len(df)} district rows -> {out}")
    log.info("Distinct district spellings found: " + ", ".join(sorted(df["district"].unique())))


if __name__ == "__main__":
    main()
