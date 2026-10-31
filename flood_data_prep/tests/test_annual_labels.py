import numpy as np
import pandas as pd
import pytest

from floodprep import annual_labels as AL

DIST = pd.DataFrame({"district_id": ["a", "b", "c"], "district_name": ["Alpha", "Beta", "Gamma"], "pop_total": [1e5, 2e5, 1e5]})
CFG = {"annual": {"duplicate_policy": "max", "absent_district_policy": "unknown", "exclude_quality_flags": []}}


def rows(*recs):
    df = pd.DataFrame(recs, columns=["district", "year", "affected_population"])
    return df


def test_discover_files_excludes_summaries_and_separates_other_versions(tmp_path):
    for n in ["seasonal_flood_labels_all_years.csv", "seasonal_flood_labels_2019_2023_provisional.csv", "annual_dataset_summary.csv",
              "annual_dataset_summary_2019_2023_provisional.csv", "seasonal_flood_labels_2023.csv"]:
        (tmp_path / n).write_text("x\n")
    auth, others, excl = AL.discover_files(tmp_path, ["seasonal_flood_labels_all_years.csv"], ["*summary*"])
    assert [p.name for p in auth] == ["seasonal_flood_labels_all_years.csv"]
    assert {p.name for p in excl} == {"annual_dataset_summary.csv", "annual_dataset_summary_2019_2023_provisional.csv"}
    assert {p.name for p in others} == {"seasonal_flood_labels_2019_2023_provisional.csv", "seasonal_flood_labels_2023.csv"}
    with pytest.raises(FileNotFoundError, match="Available"):
        AL.discover_files(tmp_path, ["nope.csv"], ["*summary*"])


def test_load_file_without_date_column_and_non_annual_rows_ignored(tmp_path):
    (tmp_path / "l.csv").write_text(
        "year,district,period_start,period_end,affected_population,label_granularity,quality_flag\n"
        "2021,Alpha,2021-05-01,2021-10-31,\"1,500\",seasonal,ok\n"
        "2021,Beta,2021-06-10,2021-06-11,10,daily,ok\n"
        "2021,Gamma,,,5,,ok\n")
    r, info = AL.load_annual_file(tmp_path / "l.csv", ["seasonal", "annual"])
    assert set(r["district"]) == {"Alpha", "Gamma"} and info["non_annual_rows"] == 1                 # daily row not used
    assert r.set_index("district").loc["Alpha", "affected_population"] == 1500                       # thousands separator
    assert r["year"].tolist() == [2021, 2021]


def test_provisional_layout_year_column(tmp_path):
    (tmp_path / "p.csv").write_text("district,affected_population,date,year\nAlpha,10,2019-11-01,2019\n")
    r, _ = AL.load_annual_file(tmp_path / "p.csv", ["seasonal"])
    assert r["year"].iloc[0] == 2019


def test_absent_is_unknown_by_default_and_zero_on_request():
    lab, _ = AL.build_annual_labels(rows(("Alpha", 2020, 50)), DIST, CFG, None, None, [2020, 2021])
    s = lab.set_index(["district_id", "year"])
    assert s.loc[("a", 2020), "label_status"] == "reported" and s.loc[("b", 2020), "label_status"] == "unknown"
    assert np.isnan(s.loc[("b", 2020), "affected_population"])
    cfg0 = {"annual": {**CFG["annual"], "absent_district_policy": "zero"}}
    lab0, _ = AL.build_annual_labels(rows(("Alpha", 2020, 50)), DIST, cfg0, None, None, [2020])
    assert lab0.set_index(["district_id", "year"]).loc[("b", 2020), "affected_population"] == 0


def test_duplicates_max_and_merge_sum():
    r = rows(("Alpha", 2020, 50), ("Alpha", 2020, 70), ("Child", 2020, 5), ("Ghost", 2020, 9))
    lab, info = AL.build_annual_labels(r, DIST, CFG, None, {"Child": "Alpha"}, [2020])
    assert lab.set_index(["district_id", "year"]).loc[("a", 2020), "affected_population"] == 75      # max(50,70) + child 5
    assert info["duplicate_keys"] == 1 and info["unmatched"] == {"Ghost": 1} and info["merged"] == {"Child": "Alpha"}


def test_years_outside_range_ignored():
    lab, _ = AL.build_annual_labels(rows(("Alpha", 1999, 50)), DIST, CFG, None, None, [2020])
    assert lab["affected_population"].isna().all()


def test_metric_pct_vs_absolute():
    lab = pd.DataFrame({"district_id": ["a", "b"], "affected_population": [1000.0, 1000.0]})
    out, m = AL.add_metric(lab.copy(), DIST, "auto")
    assert m == "affected_pct" and out["metric_value"].tolist() == [1.0, 0.5]
    out, m = AL.add_metric(lab.copy(), DIST.drop(columns="pop_total"), "auto")
    assert m == "affected_population"


def test_thresholds_from_training_values_only_and_zero_stays_low():
    t = AL.derive_thresholds([0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [0.4, 0.7, 0.9])
    assert t[0] > 0 and t[0] < t[1] < t[2]
    cls = AL.classify(pd.Series([0.0, 100.0, np.nan]), t)
    assert cls.iloc[0] == 0 and cls.iloc[1] == 3 and np.isnan(cls.iloc[2])
    with pytest.raises(ValueError):
        AL.derive_thresholds([1, 2, 3], [0.4, 0.7, 0.9])


def _write(tmp_path, body):
    (tmp_path / "l.csv").write_text(body)
    return tmp_path / "l.csv"


def test_unrecognised_granularity_with_season_length_period_is_kept_and_reported(tmp_path):
    """Regression: the real file's label_granularity was not in the configured list, every row was silently dropped (years {} / NaN / NaT)."""
    p = _write(tmp_path, "year,district,period_start,period_end,affected_population,label_granularity,quality_flag\n"
                         "2023,Bajali,2023-05-01,2023-10-31,285575,seasonal_aggregate,ok\n"
                         "2023,Barpeta,2023-05-01,2023-10-31,\"1,000\",Season total,ok\n"
                         "2023,Nalbari,2023-06-10,2023-06-11,5,daily,ok\n")
    r, info = AL.load_annual_file(p, ["seasonal", "annual"])
    assert sorted(r["district"]) == ["Bajali", "Barpeta"] and r["year"].tolist() == [2023, 2023]
    assert r["affected_population"].max() == 285575 and r["period_start"].notna().all()
    assert info["non_annual_rows"] == 1 and info["granularity_values"]["seasonal_aggregate"] == 1
    r2, i2 = AL.load_annual_file(p, ["annual"])                                   # kept by period length only, and said so
    assert len(r2) == 2 and i2["kept_by"]["period_length_only"] == 2


def test_all_rows_discarded_is_an_error_not_silence(tmp_path):
    p = _write(tmp_path, "year,district,affected_population,label_granularity\n2023,Alpha,5,weird\n")
    with pytest.raises(ValueError, match="all 1 rows were discarded"):
        AL.load_annual_file(p, ["seasonal"])


def test_invalid_values_are_reported(tmp_path):
    p = _write(tmp_path, "year,district,affected_population,label_granularity\n2023,Alpha,5,seasonal\n2023,Beta,n/a,seasonal\nxx,Gamma,3,seasonal\n")
    r, info = AL.load_annual_file(p, ["seasonal"])
    assert len(r) == 1 and info["bad_year_or_value"] == 2 and len(info["invalid_rows"]) == 2


def test_provenance_and_audit_frames():
    r = pd.DataFrame({"district": ["Alpha", "Alpha", "Child"], "year": [2020] * 3, "affected_population": [50, 70, 5],
                      "source_pdf": ["a.pdf", "b.pdf", "c.pdf"], "source_page": ["1", "2", "3"]})
    lab, info = AL.build_annual_labels(r, DIST, CFG, None, {"Child": "Alpha"}, [2020])
    row = lab[(lab.district_id == "a") & (lab.year == 2020)].iloc[0]
    assert row["source_pdf"] == "a.pdf;b.pdf;c.pdf" and row["affected_population"] == 75
    assert len(info["duplicate_detail"]) == 2 and set(info["name_map"]["name_in_file"]) == {"Alpha", "Child"}
