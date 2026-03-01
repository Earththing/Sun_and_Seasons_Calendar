"""Tests for the viz/render_day module.

All tests are skipped automatically if the [viz] optional dependencies
(matplotlib, cartopy, numpy) are not installed.

Integration tests that actually compute a grid are marked ``slow`` and
are excluded from the default CI run:
    pytest -m "not slow"
"""

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Skip the entire module if viz deps are absent
pytest.importorskip("matplotlib")
pytest.importorskip("cartopy")
numpy = pytest.importorskip("numpy")

# Make the project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from viz.render_day import (
    REGIONS, GridSpec, parse_args, resolve_output_path,
    compute_grid_for_date, _resolve_vmin_vmax, _default_ref_date,
    _sample_annual_data, _percentile_vmin_vmax, _daylight_cmap_settings,
)


# ---------------------------------------------------------------------------
# Region definition structure
# ---------------------------------------------------------------------------

REQUIRED_REGION_KEYS = {
    "description", "lat_range", "lon_range",
    "state_filter", "make_proj", "extent",
    "vmin", "vmax",
}


class TestRegionDefinitions:
    def test_all_required_regions_present(self):
        assert "lower48" in REGIONS
        assert "alaska" in REGIONS
        assert "hawaii" in REGIONS

    @pytest.mark.parametrize("region_key", list(REGIONS))
    def test_required_keys_present(self, region_key):
        missing = REQUIRED_REGION_KEYS - REGIONS[region_key].keys()
        assert not missing, f"Region '{region_key}' missing keys: {missing}"

    @pytest.mark.parametrize("region_key", list(REGIONS))
    def test_lat_range_valid(self, region_key):
        lo, hi = REGIONS[region_key]["lat_range"]
        assert -90 <= lo < hi <= 90

    @pytest.mark.parametrize("region_key", list(REGIONS))
    def test_lon_range_valid(self, region_key):
        lo, hi = REGIONS[region_key]["lon_range"]
        assert -180 <= lo < hi <= 180

    @pytest.mark.parametrize("region_key", list(REGIONS))
    def test_vmin_less_than_vmax(self, region_key):
        cfg = REGIONS[region_key]
        assert cfg["vmin"] < cfg["vmax"]

    @pytest.mark.parametrize("region_key", list(REGIONS))
    def test_extent_four_elements(self, region_key):
        extent = REGIONS[region_key]["extent"]
        assert len(extent) == 4

    @pytest.mark.parametrize("region_key", list(REGIONS))
    def test_make_proj_returns_crs(self, region_key):
        import cartopy.crs as ccrs
        proj = REGIONS[region_key]["make_proj"]()
        assert isinstance(proj, ccrs.CRS)

    def test_state_filter_lower48_excludes_alaska(self):
        f = REGIONS["lower48"]["state_filter"]
        assert not f({"admin": "United States of America", "name": "Alaska"})

    def test_state_filter_lower48_excludes_hawaii(self):
        f = REGIONS["lower48"]["state_filter"]
        assert not f({"admin": "United States of America", "name": "Hawaii"})

    def test_state_filter_lower48_includes_california(self):
        f = REGIONS["lower48"]["state_filter"]
        assert f({"admin": "United States of America", "name": "California"})

    def test_state_filter_lower48_excludes_canada(self):
        f = REGIONS["lower48"]["state_filter"]
        assert not f({"admin": "Canada", "name": "Ontario"})

    def test_state_filter_alaska_includes_alaska(self):
        f = REGIONS["alaska"]["state_filter"]
        assert f({"admin": "United States of America", "name": "Alaska"})

    def test_state_filter_alaska_excludes_california(self):
        f = REGIONS["alaska"]["state_filter"]
        assert not f({"admin": "United States of America", "name": "California"})

    def test_state_filter_hawaii_includes_hawaii(self):
        f = REGIONS["hawaii"]["state_filter"]
        assert f({"admin": "United States of America", "name": "Hawaii"})

    def test_state_filter_hawaii_excludes_alaska(self):
        f = REGIONS["hawaii"]["state_filter"]
        assert not f({"admin": "United States of America", "name": "Alaska"})

    def test_alaska_vmin_is_zero(self):
        # Alaska has polar night in winter
        assert REGIONS["alaska"]["vmin"] == 0.0

    def test_alaska_vmax_is_24(self):
        # Alaska has polar day in summer
        assert REGIONS["alaska"]["vmax"] == 24.0


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_date_required(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_date_parsed_correctly(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.date == "2026-06-08"

    def test_default_region_is_lower48(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.region == "lower48"

    def test_region_alaska(self):
        args = parse_args(["--date", "2026-06-08", "--region", "alaska"])
        assert args.region == "alaska"

    def test_region_hawaii(self):
        args = parse_args(["--date", "2026-06-08", "--region", "hawaii"])
        assert args.region == "hawaii"

    def test_invalid_region_exits(self):
        with pytest.raises(SystemExit):
            parse_args(["--date", "2026-06-08", "--region", "europe"])

    def test_default_step(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.step == 0.25

    def test_custom_step(self):
        args = parse_args(["--date", "2026-06-08", "--step", "0.5"])
        assert args.step == 0.5

    def test_default_out(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.out == "viz/frames/"

    def test_no_show_flag(self):
        args = parse_args(["--date", "2026-06-08", "--no-show"])
        assert args.no_show is True

    def test_no_show_default_false(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.no_show is False

    def test_dpi_default(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.dpi == 150

    def test_custom_dpi(self):
        args = parse_args(["--date", "2026-06-08", "--dpi", "96"])
        assert args.dpi == 96

    def test_overwrite_default_false(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.overwrite is False

    def test_overwrite_flag(self):
        args = parse_args(["--date", "2026-06-08", "--overwrite"])
        assert args.overwrite is True


class TestParseArgsBatch:
    def test_year_arg(self):
        args = parse_args(["--year", "2026"])
        assert args.year == 2026
        assert args.date is None
        assert args.start is None

    def test_year_is_int(self):
        args = parse_args(["--year", "2026"])
        assert isinstance(args.year, int)

    def test_start_end_args(self):
        args = parse_args(["--start", "2026-01-01", "--end", "2026-03-31"])
        assert args.start == "2026-01-01"
        assert args.end == "2026-03-31"
        assert args.date is None
        assert args.year is None

    def test_date_and_year_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            parse_args(["--date", "2026-06-08", "--year", "2026"])

    def test_date_and_start_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            parse_args(["--date", "2026-06-08", "--start", "2026-01-01"])

    def test_year_and_start_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            parse_args(["--year", "2026", "--start", "2026-01-01"])

    def test_no_mode_exits(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_year_with_region(self):
        args = parse_args(["--year", "2026", "--region", "alaska"])
        assert args.year == 2026
        assert args.region == "alaska"

    def test_start_end_with_region_all(self):
        args = parse_args(["--start", "2026-06-01", "--end", "2026-06-30", "--region", "all"])
        assert args.start == "2026-06-01"
        assert args.region == "all"


# ---------------------------------------------------------------------------
# GridSpec unit tests (no slow deps needed — just data structure logic)
# ---------------------------------------------------------------------------

class TestComputeGridForDate:
    def test_empty_points_returns_all_nan(self):
        """An empty spec (no land points) should return a grid of all NaN."""
        spec = GridSpec(
            region_key="lower48",
            step=1.0,
            lats=numpy.array([25.0, 26.0]),
            lons=numpy.array([-100.0, -99.0]),
            points=[],
        )
        grid = compute_grid_for_date(spec, date(2026, 6, 8))
        assert numpy.all(numpy.isnan(grid))
        assert grid.shape == (2, 2)

    def test_grid_shape_matches_spec(self):
        spec = GridSpec(
            region_key="lower48",
            step=1.0,
            lats=numpy.arange(24.0, 51.0, 1.0),
            lons=numpy.arange(-125.0, -65.0, 1.0),
            points=[],
        )
        grid = compute_grid_for_date(spec, date(2026, 6, 8))
        assert grid.shape == (len(spec.lats), len(spec.lons))


# ---------------------------------------------------------------------------
# Color scale resolution
# ---------------------------------------------------------------------------

class TestResolveVminVmax:
    def test_region_lower48_uses_region_values(self):
        vmin, vmax = _resolve_vmin_vmax("region", "lower48")
        assert vmin == REGIONS["lower48"]["vmin"]
        assert vmax == REGIONS["lower48"]["vmax"]

    def test_region_alaska_uses_region_values(self):
        vmin, vmax = _resolve_vmin_vmax("region", "alaska")
        assert vmin == REGIONS["alaska"]["vmin"]   # 0.0
        assert vmax == REGIONS["alaska"]["vmax"]   # 24.0

    def test_year_scale_always_returns_0_24(self):
        for region in REGIONS:
            vmin, vmax = _resolve_vmin_vmax("year", region)
            assert vmin == 0.0
            assert vmax == 24.0

    def test_day_scale_uses_grid_data(self):
        grid = numpy.array([[9.5, 10.0], [14.75, numpy.nan]])
        vmin, vmax = _resolve_vmin_vmax("day", "lower48", grid=grid)
        # Should be rounded to nearest ¼ hour
        assert vmin <= 9.5
        assert vmax >= 14.75
        assert 0.0 <= vmin < vmax <= 24.0

    def test_day_scale_no_grid_falls_back_to_0_24(self):
        vmin, vmax = _resolve_vmin_vmax("day", "lower48", grid=None)
        assert vmin == 0.0
        assert vmax == 24.0

    def test_day_scale_all_nan_falls_back_to_0_24(self):
        grid = numpy.full((3, 3), numpy.nan)
        vmin, vmax = _resolve_vmin_vmax("day", "lower48", grid=grid)
        assert vmin == 0.0
        assert vmax == 24.0

    def test_explicit_vmin_vmax_overrides_scale(self):
        vmin, vmax = _resolve_vmin_vmax("region", "lower48", vmin_arg=11.0, vmax_arg=15.0)
        assert vmin == 11.0
        assert vmax == 15.0

    def test_explicit_vmin_vmax_overrides_year_scale(self):
        vmin, vmax = _resolve_vmin_vmax("year", "alaska", vmin_arg=5.0, vmax_arg=20.0)
        assert vmin == 5.0
        assert vmax == 20.0

    def test_only_vmin_without_vmax_uses_scale(self):
        # If only one of vmin/vmax is given, fall through to scale logic
        vmin, vmax = _resolve_vmin_vmax("year", "lower48", vmin_arg=5.0, vmax_arg=None)
        assert vmin == 0.0   # year scale
        assert vmax == 24.0

    def test_reference_scale_uses_grid_data(self):
        grid = numpy.array([[13.5, 14.0], [15.5, numpy.nan]])
        vmin, vmax = _resolve_vmin_vmax("reference", "lower48", grid=grid)
        assert vmin <= 13.5
        assert vmax >= 15.5
        assert 0.0 <= vmin < vmax <= 24.0

    def test_reference_scale_explicit_override(self):
        vmin, vmax = _resolve_vmin_vmax("reference", "lower48", vmin_arg=12.0, vmax_arg=16.0)
        assert vmin == 12.0
        assert vmax == 16.0


class TestDefaultRefDate:
    def test_returns_june_21_of_middle_year(self):
        dates = [date(2026, 1, 1) + timedelta(days=n) for n in range(365)]
        ref = _default_ref_date(dates)
        assert ref == date(2026, 6, 21)

    def test_single_date_list(self):
        ref = _default_ref_date([date(2026, 3, 15)])
        assert ref == date(2026, 6, 21)

    def test_year_preserved(self):
        ref = _default_ref_date([date(2030, 6, 21)])
        assert ref.year == 2030


class TestParseArgsScale:
    def test_scale_default_is_region(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.scale == "region"

    def test_scale_year(self):
        args = parse_args(["--date", "2026-06-08", "--scale", "year"])
        assert args.scale == "year"

    def test_scale_day(self):
        args = parse_args(["--date", "2026-06-08", "--scale", "day"])
        assert args.scale == "day"

    def test_invalid_scale_exits(self):
        with pytest.raises(SystemExit):
            parse_args(["--date", "2026-06-08", "--scale", "custom"])

    def test_vmin_vmax_parsed_as_float(self):
        args = parse_args(["--date", "2026-06-08", "--vmin", "10", "--vmax", "16.5"])
        assert args.vmin == 10.0
        assert args.vmax == 16.5

    def test_vmin_vmax_default_none(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.vmin is None
        assert args.vmax is None

    def test_scale_with_batch_year(self):
        args = parse_args(["--year", "2026", "--scale", "year"])
        assert args.year == 2026
        assert args.scale == "year"

    def test_scale_reference(self):
        args = parse_args(["--date", "2026-06-08", "--scale", "reference"])
        assert args.scale == "reference"

    def test_ref_date_arg(self):
        args = parse_args(["--date", "2026-06-08", "--scale", "reference",
                           "--ref-date", "2026-06-21"])
        assert args.ref_date == "2026-06-21"

    def test_ref_date_default_none(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.ref_date is None

    def test_reference_scale_with_batch(self):
        args = parse_args(["--year", "2026", "--scale", "reference",
                           "--ref-date", "2026-06-21"])
        assert args.year == 2026
        assert args.scale == "reference"
        assert args.ref_date == "2026-06-21"

    def test_scale_percentile(self):
        args = parse_args(["--date", "2026-06-08", "--scale", "percentile"])
        assert args.scale == "percentile"

    def test_clip_pct_default(self):
        args = parse_args(["--date", "2026-06-08"])
        assert args.clip_pct == 5.0

    def test_clip_pct_custom(self):
        args = parse_args(["--date", "2026-06-08", "--scale", "percentile",
                           "--clip-pct", "10"])
        assert args.clip_pct == 10.0

    def test_percentile_scale_with_batch_year(self):
        args = parse_args(["--year", "2026", "--scale", "percentile",
                           "--clip-pct", "3"])
        assert args.year == 2026
        assert args.scale == "percentile"
        assert args.clip_pct == 3.0


class TestPercentileVminVmax:
    """Tests for _percentile_vmin_vmax()."""

    def test_basic_clip(self):
        # 100 values 0–99 h.  5% clip should remove the bottom 5 and top 5.
        vals = numpy.arange(100.0)
        vmin, vmax = _percentile_vmin_vmax(vals, 5.0)
        # np.percentile(arange(100), 5) = 4.95 → rounded down to 4.75
        # np.percentile(arange(100), 95) = 94.05 → clamped to 24.0
        assert 0.0 <= vmin < vmax <= 24.0

    def test_symmetric_data_gives_same_result_at_50pct(self):
        vals = numpy.array([10.0, 12.0, 14.0])
        vmin, vmax = _percentile_vmin_vmax(vals, 0.0)
        assert vmin <= 10.0
        assert vmax >= 14.0

    def test_empty_array_returns_fallback(self):
        vmin, vmax = _percentile_vmin_vmax(numpy.array([]), 5.0)
        assert vmin == 0.0
        assert vmax == 24.0

    def test_result_clamped_to_0_24(self):
        # Values beyond physical range should be clamped
        vals = numpy.array([0.0, 0.1, 25.0, 30.0])
        vmin, vmax = _percentile_vmin_vmax(vals, 1.0)
        assert vmin >= 0.0
        assert vmax <= 24.0

    def test_result_rounded_to_quarter_hour(self):
        # Any result should be a multiple of 0.25
        vals = numpy.linspace(9.0, 16.0, 200)
        vmin, vmax = _percentile_vmin_vmax(vals, 5.0)
        assert round(vmin * 4) == round(vmin * 4)    # always true, but checks float
        assert abs(vmin * 4 - round(vmin * 4)) < 1e-9
        assert abs(vmax * 4 - round(vmax * 4)) < 1e-9

    def test_zero_pct_clip_covers_full_data_range(self):
        vals = numpy.array([9.5, 12.0, 15.75])
        vmin, vmax = _percentile_vmin_vmax(vals, 0.0)
        assert vmin <= 9.5
        assert vmax >= 15.75

    def test_tighter_clip_gives_narrower_window(self):
        vals = numpy.linspace(8.0, 16.5, 500)
        vmin5,  vmax5  = _percentile_vmin_vmax(vals, 5.0)
        vmin10, vmax10 = _percentile_vmin_vmax(vals, 10.0)
        assert vmin10 >= vmin5     # 10 % clip has higher vmin
        assert vmax10 <= vmax5     # 10 % clip has lower vmax
        assert (vmax10 - vmin10) < (vmax5 - vmin5)


class TestSampleAnnualData:
    """Tests for _sample_annual_data() using a mocked GridSpec."""

    def _make_mock_spec(self, lats_shape=(10, 5)):
        """Return a GridSpec-like mock whose compute_grid_for_date returns a fixed grid."""
        spec = MagicMock(spec=GridSpec)
        spec.lats = numpy.linspace(24.0, 50.0, lats_shape[0])
        spec.lons = numpy.linspace(-125.0, -66.0, lats_shape[1])
        spec.points = [(0, 0, MagicMock(), MagicMock())]
        return spec

    def test_returns_ndarray(self):
        spec = self._make_mock_spec()
        with patch("viz.render_day.compute_grid_for_date") as mock_cgfd:
            mock_cgfd.return_value = numpy.full((10, 5), 12.0)
            result = _sample_annual_data(spec, 2026)
        assert isinstance(result, numpy.ndarray)

    def test_samples_12_months(self):
        spec = self._make_mock_spec()
        call_dates = []
        def capture(s, d):
            call_dates.append(d)
            return numpy.full((10, 5), 12.0)
        with patch("viz.render_day.compute_grid_for_date", side_effect=capture):
            _sample_annual_data(spec, 2026)
        assert len(call_dates) == 12
        assert all(d.day == 21 for d in call_dates)
        assert [d.month for d in call_dates] == list(range(1, 13))

    def test_all_nan_grid_gives_empty_result(self):
        spec = self._make_mock_spec()
        with patch("viz.render_day.compute_grid_for_date") as mock_cgfd:
            mock_cgfd.return_value = numpy.full((10, 5), numpy.nan)
            result = _sample_annual_data(spec, 2026)
        assert result.size == 0

    def test_concatenates_all_monthly_values(self):
        spec = self._make_mock_spec((2, 2))
        # Each month returns a 2×2 grid with 4 valid values
        with patch("viz.render_day.compute_grid_for_date") as mock_cgfd:
            mock_cgfd.return_value = numpy.array([[10.0, 12.0], [14.0, 16.0]])
            result = _sample_annual_data(spec, 2026)
        # 12 months × 4 valid values = 48 total
        assert result.size == 48


class TestDaylightCmapSettings:
    """Tests for _daylight_cmap_settings() — polar-night/polar-day sentinels."""

    # --- vmin / effective_vmin behaviour ---

    def test_vmin_zero_raised_to_0_25(self):
        _, eff_vmin, _, _ = _daylight_cmap_settings(0.0, 16.5)
        assert eff_vmin == 0.25

    def test_vmin_above_threshold_unchanged(self):
        _, eff_vmin, _, _ = _daylight_cmap_settings(8.0, 16.5)
        assert eff_vmin == 8.0

    def test_vmin_exactly_0_25_unchanged(self):
        _, eff_vmin, _, _ = _daylight_cmap_settings(0.25, 16.5)
        assert eff_vmin == 0.25

    def test_vmin_small_positive_raised(self):
        _, eff_vmin, _, _ = _daylight_cmap_settings(0.1, 16.5)
        assert eff_vmin == 0.25

    # --- vmax / effective_vmax behaviour ---

    def test_vmax_24_lowered_to_23_75(self):
        _, _, eff_vmax, _ = _daylight_cmap_settings(0.0, 24.0)
        assert eff_vmax == 23.75

    def test_vmax_below_24_unchanged(self):
        _, _, eff_vmax, _ = _daylight_cmap_settings(8.0, 16.5)
        assert eff_vmax == 16.5

    def test_vmax_exactly_23_75_unchanged(self):
        _, _, eff_vmax, _ = _daylight_cmap_settings(8.0, 23.75)
        assert eff_vmax == 23.75

    # --- extend string ---

    def test_extend_both_when_vmin_0_vmax_24(self):
        # Alaska year scale — polar night AND polar day both possible
        _, _, _, extend = _daylight_cmap_settings(0.0, 24.0)
        assert extend == "both"

    def test_extend_min_when_only_vmin_0(self):
        _, _, _, extend = _daylight_cmap_settings(0.0, 16.5)
        assert extend == "min"

    def test_extend_neither_for_lower48_region(self):
        # Lower 48 region: vmin=8.0, vmax=16.5 — neither sentinel is reachable
        _, _, _, extend = _daylight_cmap_settings(8.0, 16.5)
        assert extend == "neither"

    def test_extend_max_when_only_vmax_24(self):
        _, _, _, extend = _daylight_cmap_settings(0.25, 24.0)
        assert extend == "max"

    # --- colormap under/over colours ---

    def test_cmap_under_is_black(self):
        cmap, _, _, _ = _daylight_cmap_settings(0.0, 24.0)
        import matplotlib.colors as mcolors
        under = cmap.get_under()
        rgb = mcolors.to_rgb(under)
        assert rgb == (0.0, 0.0, 0.0), f"Expected black under-color, got {under}"

    def test_cmap_over_is_white(self):
        cmap, _, _, _ = _daylight_cmap_settings(0.0, 24.0)
        import matplotlib.colors as mcolors
        over = cmap.get_over()
        rgb = mcolors.to_rgb(over)
        assert rgb == (1.0, 1.0, 1.0), f"Expected white over-color, got {over}"


# ---------------------------------------------------------------------------
# Output path resolution (YYYYMMDD format)
# ---------------------------------------------------------------------------

class TestResolveOutputPath:
    def test_directory_trailing_slash_gives_yyyymmdd(self, tmp_path):
        out = resolve_output_path(str(tmp_path) + "/", date(2026, 6, 8))
        assert out.name == "20260608.png"
        assert out.parent == tmp_path

    def test_directory_no_suffix_gives_yyyymmdd(self, tmp_path):
        out = resolve_output_path(str(tmp_path), date(2026, 6, 8))
        assert out.name == "20260608.png"

    def test_explicit_filename_used_as_is(self, tmp_path):
        target = tmp_path / "custom_name.png"
        out = resolve_output_path(str(target), date(2026, 6, 8))
        assert out.name == "custom_name.png"

    def test_yyyymmdd_is_zero_padded(self, tmp_path):
        out = resolve_output_path(str(tmp_path) + "/", date(2026, 1, 5))
        assert out.name == "20260105.png"

    def test_different_dates_give_different_names(self, tmp_path):
        out1 = resolve_output_path(str(tmp_path) + "/", date(2026, 1, 1))
        out2 = resolve_output_path(str(tmp_path) + "/", date(2026, 12, 31))
        assert out1.name == "20260101.png"
        assert out2.name == "20261231.png"

    def test_names_sort_chronologically(self, tmp_path):
        dates = [date(2026, 6, 1), date(2026, 1, 1), date(2026, 12, 31)]
        names = [
            resolve_output_path(str(tmp_path) + "/", d).name for d in dates
        ]
        assert sorted(names) == ["20260101.png", "20260601.png", "20261231.png"]

    def test_directory_is_created_if_missing(self, tmp_path):
        new_dir = tmp_path / "subdir" / "frames"
        resolve_output_path(str(new_dir) + "/", date(2026, 6, 8))
        assert new_dir.exists()


# ---------------------------------------------------------------------------
# Integration tests — actually compute a small grid for each region
# These are slow and require internet on first run (shapefile download).
# Run with:  pytest -m slow
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestSunsetPastMidnightEdgeCase:
    """Fairbanks AK in summer: sunset wraps past midnight, Astral returns
    the previous day's tail-end sunset.  render_day must correct this."""

    def test_fairbanks_june_solstice_not_zero(self):
        from viz.render_day import build_land_mask, compute_daylight_grid

        mask = build_land_mask("alaska")
        # Use 1-degree step centered on Fairbanks area (~64-65 N)
        lats, lons, grid = compute_daylight_grid(
            "alaska", date(2026, 6, 21), step=1.0, land_mask=mask
        )
        # Find Fairbanks latitude row (~64-65 N)
        fairbanks_lat_idx = numpy.argmin(numpy.abs(lats - 64.8))
        row = grid[fairbanks_lat_idx, :]
        valid_in_row = row[~numpy.isnan(row)]
        if valid_in_row.size > 0:
            assert valid_in_row.min() > 15.0, (
                f"Fairbanks row min = {valid_in_row.min():.2f}h; "
                "expected > 15h on June solstice (sunset-past-midnight bug?)"
            )


@pytest.mark.slow
class TestIntegrationLower48:
    def test_grid_has_valid_us_points(self):
        from viz.render_day import build_land_mask, compute_daylight_grid

        mask = build_land_mask("lower48")
        lats, lons, grid = compute_daylight_grid(
            "lower48", date(2026, 6, 8), step=2.0, land_mask=mask
        )
        valid = grid[~numpy.isnan(grid)]
        assert valid.size > 0, "Expected valid US land points"
        assert valid.min() >= 0
        assert valid.max() <= 24

    def test_day_length_increases_northward_in_june(self):
        from viz.render_day import build_land_mask, compute_daylight_grid

        mask = build_land_mask("lower48")
        lats, lons, grid = compute_daylight_grid(
            "lower48", date(2026, 6, 8), step=2.0, land_mask=mask
        )
        # Mean daylight should be longer in northern rows than southern rows
        lat_means = numpy.nanmean(grid, axis=1)  # mean per latitude row
        valid_rows = ~numpy.isnan(lat_means)
        if valid_rows.sum() >= 2:
            # Find a southern and northern index with data
            valid_indices = numpy.where(valid_rows)[0]
            south_idx = valid_indices[0]
            north_idx = valid_indices[-1]
            assert lat_means[north_idx] > lat_means[south_idx], (
                f"Expected more daylight in the north on June 8 "
                f"({lat_means[north_idx]:.2f}h > {lat_means[south_idx]:.2f}h)"
            )


@pytest.mark.slow
class TestIntegrationAlaska:
    def test_alaska_grid_has_land_points(self):
        from viz.render_day import build_land_mask, compute_daylight_grid

        mask = build_land_mask("alaska")
        lats, lons, grid = compute_daylight_grid(
            "alaska", date(2026, 6, 21), step=2.0, land_mask=mask
        )
        valid = grid[~numpy.isnan(grid)]
        assert valid.size > 0, "Expected Alaska land points"

    def test_alaska_summer_solstice_long_days(self):
        """Interior Alaska gets ~21 h of daylight near summer solstice."""
        from viz.render_day import build_land_mask, compute_daylight_grid

        mask = build_land_mask("alaska")
        lats, lons, grid = compute_daylight_grid(
            "alaska", date(2026, 6, 21), step=2.0, land_mask=mask
        )
        valid = grid[~numpy.isnan(grid)]
        # On summer solstice, Fairbanks (~64 N) gets ~21.8 h; some points polar day
        assert valid.max() >= 20.0, (
            f"Expected Alaska June solstice max >= 20h, got {valid.max():.2f}h"
        )

    def test_alaska_winter_solstice_short_days(self):
        """Northern Alaska sees polar night (0 h) in winter."""
        from viz.render_day import build_land_mask, compute_daylight_grid

        mask = build_land_mask("alaska")
        lats, lons, grid = compute_daylight_grid(
            "alaska", date(2026, 12, 21), step=2.0, land_mask=mask
        )
        valid = grid[~numpy.isnan(grid)]
        assert valid.min() <= 3.0, (
            f"Expected very short days in Alaska in December, got min {valid.min():.2f}h"
        )


@pytest.mark.slow
class TestIntegrationHawaii:
    def test_hawaii_grid_has_land_points(self):
        from viz.render_day import build_land_mask, compute_daylight_grid

        mask = build_land_mask("hawaii")
        lats, lons, grid = compute_daylight_grid(
            "hawaii", date(2026, 6, 8), step=0.5, land_mask=mask
        )
        valid = grid[~numpy.isnan(grid)]
        assert valid.size > 0, "Expected Hawaii land points"

    def test_hawaii_day_length_in_tropical_range(self):
        """Hawaii (tropical) should have 11–14 h daylight year-round."""
        from viz.render_day import build_land_mask, compute_daylight_grid

        mask = build_land_mask("hawaii")
        # Test a summer and winter date
        for d in [date(2026, 6, 21), date(2026, 12, 21)]:
            lats, lons, grid = compute_daylight_grid(
                "hawaii", d, step=0.5, land_mask=mask
            )
            valid = grid[~numpy.isnan(grid)]
            assert valid.size > 0
            assert valid.min() >= 10.0, f"Hawaii {d}: min {valid.min():.2f}h < 10h"
            assert valid.max() <= 15.0, f"Hawaii {d}: max {valid.max():.2f}h > 15h"
