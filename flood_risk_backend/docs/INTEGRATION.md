# Integrating this backend into your original project (safe procedure)

Principle: **never run anything new against your real database first.** Work on copies, read-only checks first, keep the original folder until you are satisfied.

1. **Freeze the original.** Copy your whole original project folder (including the real `flood_risk.db`) to a safe place, e.g. `project_ORIGINAL_backup/`. Do not edit that copy.
2. **Work in a new folder.** Unzip the delivery into a *new* folder (`flood_risk_backend_new/`). Do not unzip over the original.
3. **Install and run the tests on the new folder only.**
   `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt && python -m pytest tests -q`
   Fix nothing yet; send any failure to the author of this delivery. (The delivery's DB/API tests had never been run before you do this.)
4. **Make a working copy of the real database** (never use the original file for rehearsals):
   `cp /path/to/original/flood_risk.db /tmp/flood_risk_COPY.db`, then take a verified snapshot of the copy
   `python scripts/db_snapshot.py backup --db /tmp/flood_risk_COPY.db --backup-dir /tmp/backups`.
5. **Rehearse every script against the copy** with `--database /tmp/flood_risk_COPY.db` (or `DATABASE_URL=sqlite:////tmp/flood_risk_COPY.db`):
   `python scripts/db_snapshot.py report --db /tmp/flood_risk_COPY.db` (look at integrity and orphans) →
   `python scripts/validate_data.py --data-dir data --db /tmp/flood_risk_COPY.db` →
   `python scripts/seed_db.py --database /tmp/flood_risk_COPY.db --dry-run` →
   `python scripts/assess_safe.py --database /tmp/flood_risk_COPY.db --start … --end …` (dry-run) → `python scripts/import_imd_rainfall.py --database /tmp/flood_risk_COPY.db --dry-run`.
   Compare the printed counts with what you expect (for example 33 districts, 165 label rows).
6. **Start the API against the copy** (`DATABASE_URL=sqlite:////tmp/flood_risk_COPY.db uvicorn app.main:app`), open `/health/ready` and `/docs`, and point the unchanged frontend at it. Check the map, the history chart and the ML page.
7. **Only then touch the real database**, in this order, each preceded by an automatic verified backup (do not pass `--no-backup`):
   `seed_db.py` (if the data files changed) → `assess_safe.py --apply` → `import_imd_rainfall.py`. Never run `compute_assessments.py` or `seed_db.py --reset` on it.
8. **Set `DATABASE_URL` explicitly with an absolute path** (or rely on the default `<project root>/flood_risk.db`). Do not use a relative SQLite path.
9. Keep `ALLOW_ML_VULNERABILITY=false`. Do not run `ml/scripts/evaluate_models.py` or `scripts/train_model.py` (they would write `ml/reports/*` / `models_artifacts/*`).
10. If anything looks wrong, stop the API and restore from the snapshot in `backups/`, or return to `project_ORIGINAL_backup/`.

Files you may copy from this delivery into an existing project one at a time instead of replacing it wholesale: the new scripts, `app/errors.py`, `app/services/db_health.py`, `app/services/ml_reports.py`,
and the modified routes/main. The route files, `app/main.py` and `app/config.py` depend on each other, so copy them together.
