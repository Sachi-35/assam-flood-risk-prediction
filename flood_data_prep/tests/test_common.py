import pandas as pd

from floodprep.common import build_name_lookup, match_name, match_series, normalize_name


def test_normalize():
    assert normalize_name("Kamrup (M)") == "kamrupm"
    assert normalize_name("Dhemaji District") == "dhemaji"


def test_alias_and_fuzzy():
    lk = build_name_lookup(["Sivasagar", "Lakhimpur", "Morigaon"], {"Sivasagar": ["Sibsagar"], "Morigaon": ["Marigaon"]})
    assert match_name("Sibsagar", lk) == "Sivasagar"
    assert match_name("MARIGAON", lk) == "Morigaon"
    assert match_name("Lakhimpurr", lk) == "Lakhimpur"      # typo, fuzzy
    assert match_name("Nalbari", lk) is None                # must not be force-matched


def test_match_series_reports_unmatched():
    lk = build_name_lookup(["Dhemaji"], None)
    mapped, unmatched = match_series(pd.Series(["Dhemaji", "Cachar"]), lk)
    assert mapped.iloc[0] == "Dhemaji" and pd.isna(mapped.iloc[1]) and unmatched == ["Cachar"]
