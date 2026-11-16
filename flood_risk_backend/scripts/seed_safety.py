"""Stdlib-only helpers for scripts/seed_db.py: the protected --reset guard and the existing/incoming/resulting count table."""
from __future__ import annotations

import os
import sqlite3


class ResetRefused(Exception):
    """--reset was refused; nothing was dropped."""


def _row_counts_readonly(db_file: str) -> dict[str, int]:
    uri = "file:" + os.path.abspath(db_file).replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: con.execute('SELECT count(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0] for t in names}
    finally:
        con.close()


def check_reset_allowed(db_file: str | None, confirm_path: str | None) -> None:
    """Raise ResetRefused unless ALL hold: a SQLite file, the exact path typed again via --confirm-reset, and the database holds NO rows
    in any table. A database with data is treated as a real database and is never reset by this script."""
    if not db_file:
        raise ResetRefused("--reset only works on a SQLite file database (not in-memory or server databases).")
    if not confirm_path or os.path.abspath(confirm_path) != os.path.abspath(db_file):
        raise ResetRefused(f"--reset needs --confirm-reset with the exact database path: --confirm-reset {db_file}")
    if not os.path.exists(db_file):
        return                                                       # nothing to drop
    try:
        counts = _row_counts_readonly(db_file)
    except sqlite3.DatabaseError as e:
        raise ResetRefused(f"cannot inspect {db_file} ({e}); reset refused.") from e
    total = sum(counts.values())
    if total:
        held = ", ".join(f"{t}={n}" for t, n in sorted(counts.items()) if n)
        raise ResetRefused(f"{db_file} holds {total:,} row(s) ({held}); it is treated as a REAL database and will not be reset. "
                           "To start clean, move or rename the file and run a normal seed: it creates a fresh database.")


def format_count_table(before: dict[str, int], incoming: dict[str, int | None], after: dict[str, int], modes: dict[str, str]) -> str:
    """incoming[table] is None when the source file was absent (table untouched)."""
    rows = [("table", "existing", "incoming", "resulting", "action")]
    for t in before:
        inc = incoming.get(t)
        action = "SKIPPED (no source file; table unchanged)" if inc is None else modes.get(t, "replaced")
        rows.append((t, f"{before[t]:,}", "-" if inc is None else f"{inc:,}", f"{after.get(t, before[t]):,}", action))
    w = [max(len(r[i]) for r in rows) for i in range(4)]
    return "\n".join(f"  {r[0]:<{w[0]}}  {r[1]:>{w[1]}}  {r[2]:>{w[2]}}  {r[3]:>{w[3]}}  {r[4]}" for r in rows)
