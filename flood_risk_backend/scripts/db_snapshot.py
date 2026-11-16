"""Safe SQLite snapshot + health report. Standard library only; NEVER modifies the database it inspects.

Commands
  report  integrity_check, foreign-key orphan check and per-table row counts (read-only).
  backup  consistent copy via SQLite's online backup API, then verifies the copy (integrity + identical row counts).

What it guarantees
  * The source file is opened with `mode=ro`; no write, no PRAGMA that changes state, no schema change.
  * Foreign-key ENFORCEMENT is never enabled. Orphans are found with `PRAGMA foreign_key_check`, which only reads.
  * A backup never overwrites an existing file and never targets the source file itself.
  * The backup is written to a temporary name and renamed only after it passed verification.

Exit codes: 0 = all checks clean, 1 = problem found (integrity failure, orphans, backup verification mismatch), 2 = usage/IO error.

Usage
  python scripts/db_snapshot.py report --db flood_risk.db [--json]
  python scripts/db_snapshot.py backup --db flood_risk.db [--backup-dir backups] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

ORPHAN_SAMPLE = 10


class SnapshotError(Exception):
    """Usage / IO problem (exit code 2)."""


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def open_readonly(db_path: str) -> sqlite3.Connection:
    if not os.path.isfile(db_path):
        raise SnapshotError(f"database file not found: {db_path}")
    uri = "file:" + os.path.abspath(db_path).replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()     # fails early if not an SQLite file
    except sqlite3.DatabaseError as e:
        raise SnapshotError(f"{db_path} is not a readable SQLite database: {e}") from e
    return con


def table_names(con: sqlite3.Connection) -> list[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    return [r[0] for r in rows]


def row_counts(con: sqlite3.Connection) -> dict[str, int]:
    return {t: con.execute(f"SELECT count(*) FROM {_q(t)}").fetchone()[0] for t in table_names(con)}


def integrity(con: sqlite3.Connection) -> list[str]:
    """Messages of PRAGMA integrity_check; ['ok'] when healthy."""
    return [r[0] for r in con.execute("PRAGMA integrity_check").fetchall()]


def foreign_key_violations(con: sqlite3.Connection) -> dict:
    """Orphan rows according to the FOREIGN KEY clauses declared in the schema. Read-only; enforcement is not switched on."""
    rows = con.execute("PRAGMA foreign_key_check").fetchall()          # (table, rowid, parent, fk index)
    by: dict[tuple[str, str], list] = {}
    for table, rowid, parent, _ in rows:
        by.setdefault((table, parent), []).append(rowid)
    return {
        "total": len(rows),
        "groups": [{"table": t, "parent_table": p, "orphan_rows": len(ids), "sample_rowids": ids[:ORPHAN_SAMPLE]}
                   for (t, p), ids in sorted(by.items())],
    }


def build_report(db_path: str) -> dict:
    con = open_readonly(db_path)
    try:
        integ = integrity(con)
        fk = foreign_key_violations(con)
        counts = row_counts(con)
        declared = {t: len(con.execute(f"PRAGMA foreign_key_list({_q(t)})").fetchall()) for t in counts}
    finally:
        con.close()
    return {
        "database": os.path.abspath(db_path),
        "size_bytes": os.path.getsize(db_path),
        "integrity_ok": integ == ["ok"],
        "integrity_messages": integ,
        "foreign_key_enforcement_enabled_by_this_tool": False,
        "foreign_keys_declared_per_table": declared,
        "orphans": fk,
        "tables": counts,
        "total_rows": sum(counts.values()),
        "clean": integ == ["ok"] and fk["total"] == 0,
    }


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(db_path: str, backup_dir: str, label: str | None = None) -> dict:
    """Copy `db_path` into `backup_dir` with SQLite's backup API and verify the copy. Never touches the source or existing backups."""
    src_abs = os.path.abspath(db_path)
    if not os.path.isfile(src_abs):
        raise SnapshotError(f"database file not found: {db_path}")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base = os.path.splitext(os.path.basename(src_abs))[0]
    name = f"{base}{'_' + label if label else ''}_{stamp}.db"
    dest = os.path.abspath(os.path.join(backup_dir, name))
    if dest == src_abs or os.path.exists(dest):
        raise SnapshotError(f"refusing to write backup over an existing file: {dest}")
    tmp = dest + ".partial"
    if os.path.exists(tmp):
        raise SnapshotError(f"leftover partial backup exists, remove it first: {tmp}")

    src = open_readonly(src_abs)
    dst = None
    try:
        src_counts = row_counts(src)
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        dst.commit()
        dst.close()
        dst = None
        chk = open_readonly(tmp)
        try:
            dst_integ, dst_counts = integrity(chk), row_counts(chk)
        finally:
            chk.close()
        if dst_integ != ["ok"] or dst_counts != src_counts:
            raise SnapshotError(f"backup verification failed (integrity={dst_integ}, counts equal={dst_counts == src_counts}); "
                                f"partial copy kept for inspection at {tmp}")
        os.replace(tmp, dest)
    except SnapshotError:
        raise
    except Exception:
        if dst is not None:
            dst.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    finally:
        src.close()
    return {"source": src_abs, "backup": dest, "size_bytes": os.path.getsize(dest), "sha256": sha256_file(dest),
            "integrity_ok": True, "tables": dst_counts, "total_rows": sum(dst_counts.values()),
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def format_report(r: dict) -> str:
    out = [f"database : {r['database']}", f"size     : {r['size_bytes']:,} bytes",
           f"integrity: {'OK' if r['integrity_ok'] else 'FAILED -> ' + '; '.join(r['integrity_messages'][:5])}",
           "foreign-key enforcement: not enabled by this tool (check is read-only)"]
    o = r["orphans"]
    if o["total"] == 0:
        out.append("orphans  : none found")
    else:
        out.append(f"orphans  : {o['total']} row(s) reference a missing parent")
        out += [f"   {g['table']} -> {g['parent_table']}: {g['orphan_rows']} row(s), sample rowids {g['sample_rowids']}" for g in o["groups"]]
    out.append(f"tables   : {len(r['tables'])}, {r['total_rows']:,} rows")
    w = max((len(t) for t in r["tables"]), default=5)
    out += [f"   {t:<{w}}  {n:>10,}" for t, n in r["tables"].items()]
    out.append("RESULT   : " + ("clean" if r["clean"] else "PROBLEMS FOUND (nothing was changed)"))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only SQLite report and verified backup. Never modifies the source database.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, h in (("report", "integrity, orphan and row-count report (read-only)"), ("backup", "verified backup copy, then report on it")):
        p = sub.add_parser(name, help=h)
        p.add_argument("--db", required=True, help="path to the SQLite file")
        p.add_argument("--json", action="store_true", help="machine-readable output")
        if name == "backup":
            p.add_argument("--backup-dir", default="backups", help="directory for the copy (default: ./backups)")
            p.add_argument("--label", help="optional text added to the backup file name")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "report":
            r = build_report(a.db)
            print(json.dumps(r, indent=2) if a.json else format_report(r))
            return 0 if r["clean"] else 1
        b = create_backup(a.db, a.backup_dir, a.label)
        r = build_report(b["backup"])
        r["backup_info"] = b
        print(json.dumps(r, indent=2) if a.json else f"backup   : {b['backup']}\nsha256   : {b['sha256']}\n" + format_report(r))
        return 0 if r["clean"] else 1
    except SnapshotError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
