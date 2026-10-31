"""Shared helpers: config loading, logging, district-name matching."""
from __future__ import annotations

import difflib
import logging
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    return logger


def load_config(path: str | Path | None = None) -> dict:
    """Load YAML config and resolve all paths against the project root."""
    path = Path(path) if path else DEFAULT_CONFIG
    cfg = yaml.safe_load(path.read_text())
    root = Path(cfg.get("project_root") or path.resolve().parent.parent)
    cfg["_root"] = root

    def resolve(p):
        p = Path(p)
        return p if p.is_absolute() else root / p

    cfg["paths"] = {k: resolve(v) for k, v in cfg["paths"].items()}
    bf = cfg["districts"].get("boundary_file")
    if bf:
        cfg["districts"]["boundary_file"] = resolve(bf)
    li = cfg.get("labels", {}).get("input_dir")
    if li:
        cfg["labels"]["input_dir"] = resolve(li)
    up = cfg.get("rainfall", {}).get("upstream", {})
    if up.get("geometry_file"):
        up["geometry_file"] = resolve(up["geometry_file"])
    return cfg


def ensure_dir(p: Path) -> Path:
    Path(p).mkdir(parents=True, exist_ok=True)
    return Path(p)


def add_config_arg(parser):
    parser.add_argument("--config", default=None, help="Path to config.yaml (default: config/config.yaml)")
    return parser


# ---------------------------------------------------------------------------
# District-name handling (spellings differ across sources: Sivasagar/Sibsagar ...)
# ---------------------------------------------------------------------------
def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def normalize_name(s: str) -> str:
    s = str(s).lower().replace("&", "and")
    s = re.sub(r"\bdistrict\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def build_name_lookup(canonical: list[str], aliases: dict | None = None) -> dict[str, str]:
    """normalized spelling -> canonical name."""
    lookup = {normalize_name(c): c for c in canonical}
    for canon, alts in (aliases or {}).items():
        if canon in canonical:
            for a in alts:
                lookup[normalize_name(a)] = canon
    return lookup


def match_name(name, lookup: dict[str, str], cutoff: float = 0.88) -> str | None:
    """Exact (normalized) match first, then a strict fuzzy match. None if no match."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    key = normalize_name(name)
    if key in lookup:
        return lookup[key]
    close = difflib.get_close_matches(key, list(lookup), n=1, cutoff=cutoff)
    return lookup[close[0]] if close else None


def match_series(names: pd.Series, lookup: dict[str, str], cutoff: float = 0.88):
    """Map a Series of raw names -> canonical; returns (mapped Series, sorted list of unmatched raw names)."""
    uniq = {n: match_name(n, lookup, cutoff) for n in names.dropna().unique()}
    unmatched = sorted(n for n, v in uniq.items() if v is None)
    return names.map(uniq), unmatched
