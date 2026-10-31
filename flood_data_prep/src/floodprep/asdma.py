"""Download and parse ASDMA (DRIMS Assam) daily flood-report PDFs.

Observed layout of a 2024 report: a table "Population and Crop Area affected" with columns
    District | Male | Female | Children | Total Population | Total Crop Area (In Hect.) | details
and a closing `Total` row. Rows come out of pdfplumber text roughly as
    "Barpeta 62447 45316 31636 139399 1571.5 (Barpeta | Population Affected: 608 | ..."

BEST-EFFORT PARSER: report layouts change between years and wrapped district names ("Karbi\\nAnglong")
are handled heuristically. ALWAYS spot-check a few dates by eye. The built-in cross-check (district rows
must sum to the report's own Total row) is returned so mismatches are visible.
"""
from __future__ import annotations

import re
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

URL_TMPL = "https://www.asdma.gov.in/pdf/flood_report/{year}/Daily_Flood_Report_{dd}.{mm}.{year}.pdf"

ROW_RE = re.compile(
    r"^(?P<district>[A-Za-z][A-Za-z .()'&/-]*?)\s+"
    r"(?P<male>\d+)\s+(?P<female>\d+)\s+(?P<children>\d+)\s+(?P<total>\d+)\s+(?P<crop>\d+(?:\.\d+)?)\b"
)
HEADER_WORDS = {"district", "male", "female", "children", "total", "population", "crop", "area", "in", "hect", "and",
                "details", "affected", "drims", "assam", "disaster", "reporting", "information", "management", "system"}
SECTION_START = re.compile(r"population\s+and\s+crop\s+area", re.I)
SECTION_END = re.compile(r"relief\s+(camps?|centres?)|inmates|human\s+lives|animals\s+affected|houses\s+damaged", re.I)


def report_url(d: date) -> str:
    return URL_TMPL.format(year=d.year, dd=f"{d.day:02d}", mm=f"{d.month:02d}")


def download_reports(start: date, end: date, out_dir: Path, sleep_s: float = 0.5, log=print) -> list[Path]:
    """Download every daily PDF in [start, end]. Missing days (HTTP 404) are skipped silently."""
    import requests

    out_dir.mkdir(parents=True, exist_ok=True)
    got = []
    d = start
    while d <= end:
        dest = out_dir / f"Daily_Flood_Report_{d:%d.%m.%Y}.pdf"
        if not dest.exists():
            try:
                r = requests.get(report_url(d), timeout=60)
                if r.status_code == 200 and r.content[:4] == b"%PDF":
                    dest.write_bytes(r.content)
                    got.append(dest)
                elif r.status_code != 404:
                    log(f"{d}: HTTP {r.status_code}")
            except requests.RequestException as e:
                log(f"{d}: {e}")
            time.sleep(sleep_s)
        else:
            got.append(dest)
        d += timedelta(days=1)
    return got


def parse_text(text: str) -> tuple[list[dict], dict | None]:
    """Parse the extracted text of one report. Returns (district rows, report Total row or None)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rows, total_row, in_section, pending = [], None, False, ""
    for ln in lines:
        if not in_section:
            if SECTION_START.search(ln):
                in_section = True
            continue
        if SECTION_END.search(ln) and not ROW_RE.match(ln):
            break
        m = ROW_RE.match(ln)
        if m:
            name = (pending + " " + m.group("district")).strip() if pending else m.group("district").strip()
            rec = {
                "district": name,
                "affected_male": int(m.group("male")),
                "affected_female": int(m.group("female")),
                "affected_children": int(m.group("children")),
                "affected_population": int(m.group("total")),
                "crop_area_ha": float(m.group("crop")),
            }
            if name.lower().endswith("total") and name.lower().replace("total", "").strip() == "":
                total_row = rec
            else:
                rows.append(rec)
            pending = ""
        else:
            words = re.findall(r"[A-Za-z]+", ln)
            alpha_only = ln.replace(" ", "").isalpha() or re.fullmatch(r"[A-Za-z .()'&/-]+", ln)
            if alpha_only and words and not all(w.lower() in HEADER_WORDS for w in words):
                pending = ln  # first half of a wrapped district name
            else:
                pending = ""
    return rows, total_row


def parse_pdf(pdf_path: Path) -> tuple[pd.DataFrame, bool | None]:
    """Parse one PDF -> (DataFrame[district, date, affected_population, ...], sum_check_ok)."""
    import pdfplumber

    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", pdf_path.name)
    if not m:
        raise ValueError(f"Cannot read date from filename {pdf_path.name}")
    d = pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1)))
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    rows, total = parse_text(text)
    df = pd.DataFrame(rows)
    if df.empty:
        return df, None
    df.insert(1, "date", d)
    ok = None if total is None else int(df["affected_population"].sum()) == total["affected_population"]
    return df, ok


def parse_folder(pdf_dir: Path, log=print) -> pd.DataFrame:
    frames, bad = [], []
    for pdf in sorted(Path(pdf_dir).glob("Daily_Flood_Report_*.pdf")):
        try:
            df, ok = parse_pdf(pdf)
        except Exception as e:  # noqa: BLE001
            log(f"{pdf.name}: could not parse ({e})")
            continue
        if df.empty:
            log(f"{pdf.name}: no district table found")
            continue
        if ok is False:
            bad.append(pdf.name)
        frames.append(df)
    if bad:
        log(f"WARNING: district rows do not sum to the report Total in {len(bad)} files, e.g. {bad[:5]}. Inspect them.")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
