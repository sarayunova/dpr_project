from datetime import date
from pathlib import Path

import pytest

from app.parser import DPRParseError, parse_dpr_text

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "docs" / "03_sample_documents"


def _load(name: str) -> str:
    return (SAMPLES_DIR / name).read_text(encoding="utf-8")


def _well(report, well_name):
    return next(w for w in report.wells if w.well_name == well_name)


# ---------------------------------------------------------------------------
# Parsing correctness — docs/10_acceptance_criteria.md §"Parsing correctness"
# ---------------------------------------------------------------------------


def test_sample_dpr_has_exactly_four_wells():
    report = parse_dpr_text(_load("sample_dpr.txt"))
    assert [w.well_name for w in report.wells] == [
        "NG-2000-4",
        "NG-2000-6",
        "ARMCUE-1",
        "E-1400-13",
    ]
    assert report.asset_name == "Assam Asset + RO"
    assert report.report_date == date(2026, 4, 2)


def test_ng_2000_4_total_days():
    report = parse_dpr_text(_load("sample_dpr.txt"))
    well = _well(report, "NG-2000-4")
    assert well.tot_days_planned == 190
    assert well.tot_days_actual == 155


def test_ng_2000_4_cost():
    report = parse_dpr_text(_load("sample_dpr.txt"))
    well = _well(report, "NG-2000-4")
    assert well.cost_planned_inr == 886323863.0
    assert well.cost_actual_inr == 960346238.0


def test_ng_2000_4_phase_table():
    report = parse_dpr_text(_load("sample_dpr.txt"))
    well = _well(report, "NG-2000-4")
    assert len(well.phases) == 4
    phase2 = well.phases[1]
    assert phase2.phase_no == 2
    assert phase2.casing_size == '13 3/8"'
    assert phase2.depth_planned == 2400.0
    assert phase2.depth_actual == 2404.0


def test_armcue_1_blank_planned_cost_not_coerced_to_zero():
    report = parse_dpr_text(_load("sample_dpr.txt"))
    well = _well(report, "ARMCUE-1")
    assert well.cost_planned_inr is None
    assert well.cost_actual_inr == 378925607.0


def test_e_1400_13_survives_mid_block_page_break_banner():
    report = parse_dpr_text(_load("sample_dpr.txt"))
    well = _well(report, "E-1400-13")
    assert len(well.phases) == 3
    # These fields only appear in the second half of the block, after the
    # repeated SAP page banner — confirms the banner was stripped correctly
    # without truncating the well.
    assert well.cost_planned_inr is None
    assert well.cost_actual_inr == 373789219.0


# ---------------------------------------------------------------------------
# Multi-day timeline — docs/10_acceptance_criteria.md §"Multi-day timeline"
# ---------------------------------------------------------------------------


def test_ng_2000_4_day_over_day_progression():
    day1 = _well(parse_dpr_text(_load("sample_dpr.txt")), "NG-2000-4")
    day2 = _well(parse_dpr_text(_load("sample_dpr_assam_ro_day2.txt")), "NG-2000-4")

    assert day1.present_depth == 3612.0
    assert day2.present_depth == 3616.0

    assert day1.tot_days_actual == 155
    assert day2.tot_days_actual == 156
    assert day1.tot_days_planned == day2.tot_days_planned == 190

    # Cost can legitimately stay flat for a day even as depth/days move.
    assert day1.cost_planned_inr == day2.cost_planned_inr == 886323863.0
    assert day1.cost_actual_inr == day2.cost_actual_inr == 960346238.0


def test_day2_report_is_full_thirteen_well_report():
    # 2 wells under ON LAND EXPLORATORY WELLS + 11 under ON LAND DEVELOPMENT
    # WELLS — sequence numbers reset per category, so the source PDF's
    # highest sequence number ("11.NG-1500-6") is not the well count.
    report = parse_dpr_text(_load("sample_dpr_assam_ro_day2.txt"))
    assert len(report.wells) == 13
    assert report.report_date == date(2026, 4, 3)


# ---------------------------------------------------------------------------
# Multi-asset parsing — docs/10_acceptance_criteria.md §"Multi-asset parsing"
# ---------------------------------------------------------------------------


def test_assam_arakan_three_wells_and_asset_name():
    report = parse_dpr_text(_load("sample_dpr_assam_arakan.txt"))
    assert report.asset_name == "Assam & Assam Arakan Basin, Jorhat"
    assert [w.well_name for w in report.wells] == ["E-760-10", "E-1400-24", "E-760-9U"]


def test_e_760_10_zero_phase_rows_and_all_blank_fields():
    report = parse_dpr_text(_load("sample_dpr_assam_arakan.txt"))
    well = _well(report, "E-760-10")
    assert well.sequence_no == 0
    assert well.mode == "O"
    assert well.phases == []
    assert well.target_depth is None
    assert well.present_depth is None
    assert well.tot_days_planned is None
    assert well.cost_planned_inr is None
    assert well.cost_actual_inr is None


def test_tripura_six_wells_and_workover_category():
    report = parse_dpr_text(_load("sample_dpr_tripura.txt"))
    assert report.asset_name == "Tripura Asset"
    assert len(report.wells) == 6
    workover_well = _well(report, "E-1400-M2")
    assert workover_well.category == "WORKOVER WELLS"
    assert workover_well.well_type == "VE"
    assert workover_well.mode == "W"


def test_wo_p_a_line_wrap_still_parses():
    report = parse_dpr_text(_load("sample_dpr_tripura.txt"))
    well = _well(report, "E-1400-M2")
    assert well.wo_days_planned == 45
    assert well.wo_days_actual == 40


def test_missing_phase_number_token_inferred_by_position():
    report = parse_dpr_text(_load("sample_dpr_tripura.txt"))
    well = _well(report, "NG-2000-3")
    assert len(well.phases) == 4
    assert [p.phase_no for p in well.phases] == [1, 2, 3, 4]
    assert well.phases[0].casing_size == '20"'


def test_fractionless_casing_size_parses():
    report = parse_dpr_text(_load("sample_dpr_tripura.txt"))
    well = _well(report, "NG-2000-2")
    assert well.phases[3].casing_size == '7"'


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_raises_on_text_with_no_banner():
    with pytest.raises(DPRParseError):
        parse_dpr_text("not a real DPR file")
