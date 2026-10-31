from floodprep.asdma import parse_text, report_url

SAMPLE = """DRIMS Assam
Disaster Reporting and Information Management System
Population and Crop Area affected
District Male Female Children Total Population Total Crop Area (In Hect.) Population and Crop Area Details
Barpeta 62447 45316 31636 139399 1571.5 (Barpeta | Population Affected: 608 | Crop Area: 0)
Karbi
Anglong 100 200 300 600 12 (Karbi Anglong | Population Affected: 600 | Crop Area: 12)
Dhemaji 35166 32716 23238 91120 2336.62
Total 97713 78232 55174 231119 3920.12
Relief camps / centres opened
District Total Relief Camp
Barpeta 5 1
"""


def test_parse_rows_and_total():
    rows, total = parse_text(SAMPLE)
    names = [r["district"] for r in rows]
    assert names == ["Barpeta", "Karbi Anglong", "Dhemaji"]
    assert total["affected_population"] == 231119
    assert sum(r["affected_population"] for r in rows) == total["affected_population"]   # sum check works


def test_stops_at_next_section():
    rows, _ = parse_text(SAMPLE)
    assert len(rows) == 3          # the relief-camp rows are not picked up


def test_report_url():
    from datetime import date
    assert report_url(date(2024, 7, 5)).endswith("2024/Daily_Flood_Report_05.07.2024.pdf")
