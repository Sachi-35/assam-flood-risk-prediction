"""ALLOW_ML_VULNERABILITY=false (default): the main vulnerability stays the empirical district history, and no model is even loaded.
Temporary database only; the legacy script is exercised against it, never against a real database."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from sqlalchemy.orm import sessionmaker  # noqa: E402

import compute_assessments as CA  # noqa: E402
from app.models import District, FloodLabel, Vulnerability  # noqa: E402
from tests.api_fixtures import POLY, build_db  # noqa: E402
import json  # noqa: E402


def _db(tmp_path):
    eng = build_db(tmp_path / "f.db", with_data=False)
    s = sessionmaker(bind=eng)()
    s.add(District(id=1, name="D1", state="Assam", geometry=json.dumps(POLY)))
    s.add(FloodLabel(district_id=1, year=2020, status="reported", impact_class="moderate"))
    s.add(FloodLabel(district_id=1, year=2021, status="reported", impact_class="high"))
    s.commit()
    return eng, s


def test_legacy_compute_uses_empirical_history_and_never_loads_a_model_by_default(tmp_path, monkeypatch):
    eng, s = _db(tmp_path)
    loaded = []
    monkeypatch.setattr(CA, "read_metadata", lambda: {"vulnerability_source": "ml_model", "model_version": "x"})   # metadata CLAIMS an ML model
    monkeypatch.setattr(CA, "get_model_bundle", lambda: loaded.append(True))
    monkeypatch.setattr(CA.settings, "ALLOW_ML_VULNERABILITY", False)
    CA.compute_vulnerabilities(s)
    assert loaded == []                                                       # the model bundle was never even requested
    v = s.get(Vulnerability, 1)
    assert v.source == "district_history" and v.risk_class == "high" and v.proba is None and v.model_version is None
    s.close()
    eng.dispose()


def test_model_is_consulted_only_when_explicitly_allowed(tmp_path, monkeypatch):
    eng, s = _db(tmp_path)
    loaded = []
    monkeypatch.setattr(CA, "read_metadata", lambda: {"vulnerability_source": "ml_model", "model_version": "x"})
    monkeypatch.setattr(CA, "get_model_bundle", lambda: loaded.append(True))            # returns None: no model exists
    monkeypatch.setattr(CA.settings, "ALLOW_ML_VULNERABILITY", True)
    CA.compute_vulnerabilities(s)
    assert loaded == [True]
    assert s.get(Vulnerability, 1).source == "district_history"               # no bundle -> still the empirical fallback, never a default class
    s.close()
    eng.dispose()
