import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import box

from floodprep.zonal import unit_scale, zonal_mean, zone_weights


def _ds(values=None, units="mm/day", lats=None):
    lats = np.array([26.0, 26.5, 27.0]) if lats is None else lats
    lons = np.array([94.0, 94.5, 95.0])
    t = pd.date_range("2020-01-01", periods=2)
    v = np.ones((2, 3, 3)) if values is None else values
    return xr.Dataset({"precip": (("time", "lat", "lon"), v, {"units": units})}, coords={"time": t, "lat": lats, "lon": lons})


def test_weights_are_area_fractions():
    # zone = exactly one 0.5-degree cell centred on (94.5, 26.5): weight 1 on that cell
    r, c, w, cov = zone_weights(np.array([94.0, 94.5, 95.0]), np.array([26.0, 26.5, 27.0]), box(94.25, 26.25, 94.75, 26.75))
    assert len(w) == 1 and abs(w[0] - 1.0) < 1e-9 and cov > 0.99


def test_small_zone_between_cell_centres_still_gets_data():
    ds = _ds(np.arange(18, dtype=float).reshape(2, 3, 3))
    out, info, _ = zonal_mean(ds, {"z": box(94.3, 26.3, 94.4, 26.4)})
    assert info["z"]["status"] == "ok" and out["rain_mm"].notna().all()


def test_zone_outside_grid_is_nan_not_nearest_cell():
    out, info, _ = zonal_mean(_ds(), {"far": box(100, 30, 101, 31)})
    assert info["far"]["status"] == "outside" and out["rain_mm"].isna().all()


def test_fill_values_and_partial_nan():
    v = np.ones((2, 3, 3)); v[0, 1, 1] = -9999.0
    out, _, _ = zonal_mean(_ds(v), {"z": box(94.0, 26.0, 95.0, 27.0)})
    assert out["rain_mm"].between(0, 5).all()           # fill code ignored, mean of remaining cells = 1


def test_units_metres_are_converted():
    assert unit_scale(_ds(units="m")["precip"])[0] == 1000.0
    assert unit_scale(_ds(units="kg m-2 s-1")["precip"])[0] == 86400.0


def test_descending_latitudes_work():
    out, info, _ = zonal_mean(_ds(lats=np.array([27.0, 26.5, 26.0])), {"z": box(94.2, 26.2, 94.8, 26.8)})
    assert info["z"]["status"] == "ok"
