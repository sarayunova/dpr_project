"""Deterministic parsing of ONGC-style Drilling Progress Report (DPR) text.

No database or LLM involved here — see docs/02_data_dictionary.md §A for
the field-by-field source of truth this module implements, and
docs/03_sample_documents/ for the real DPR text this was built and tested
against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class ParsedPhase:
    phase_no: int
    casing_size: str
    depth_planned: Optional[float]
    depth_actual: Optional[float]
    days_planned: Optional[int]
    days_actual: Optional[int]
    hole_top: Optional[str]


@dataclass
class ParsedWell:
    sequence_no: int
    well_name: str
    location_code: str
    category: Optional[str]
    well_type: Optional[str]
    mode: Optional[str]
    target_depth: Optional[float]
    present_depth: Optional[float]
    day_meterage: Optional[float]
    rb_start: Optional[date]
    dr_start: Optional[date]
    pt_start: Optional[date]
    crep_outcyl_planned: Optional[int]
    crep_outcyl_actual: Optional[int]
    rb_days_planned: Optional[int]
    rb_days_actual: Optional[int]
    dr_days_planned: Optional[int]
    dr_days_actual: Optional[int]
    pt_days_planned: Optional[int]
    pt_days_actual: Optional[int]
    tot_days_planned: Optional[int]
    tot_days_actual: Optional[int]
    wo_days_planned: Optional[int]
    wo_days_actual: Optional[int]
    la_no: Optional[str]
    a_kick: Optional[str]
    mud_weight: Optional[float]
    mud_viscosity: Optional[float]
    lot_depth: Optional[float]
    lot_value: Optional[float]
    litho: Optional[str]
    obj_no: Optional[str]
    obj_name: Optional[str]
    obj_days: Optional[int]
    obj_interval: Optional[str]
    cost_planned_inr: Optional[float]
    cost_actual_inr: Optional[float]
    nl1: Optional[str]
    status_text: Optional[str]
    cluster: Optional[str]
    oper_narrative: str
    phases: list[ParsedPhase] = field(default_factory=list)


@dataclass
class ParsedReport:
    asset_name: str
    report_date: date
    wells: list[ParsedWell] = field(default_factory=list)


class DPRParseError(ValueError):
    """Raised when the DPR text doesn't match the expected structure."""


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _clean(s: Optional[str]) -> str:
    return (s or "").strip()


def _parse_int(s: Optional[str]) -> Optional[int]:
    s = _clean(s).replace(",", "")
    return int(s) if s else None


def _parse_float(s: Optional[str]) -> Optional[float]:
    s = _clean(s).replace(",", "")
    return float(s) if s else None


def _parse_str(s: Optional[str]) -> Optional[str]:
    s = _clean(s)
    return s or None


def _parse_ddmmyyyy(s: Optional[str]) -> Optional[date]:
    s = _clean(s)
    if not s:
        return None
    day, month, year = s.split(".")
    return date(int(year), int(month), int(day))


def _split_pair(s: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split a 'planned/actual'-shaped raw token on its single '/'."""
    s = _clean(s)
    if "/" not in s:
        return (s or None), None
    planned, actual = s.split("/", 1)
    return (planned or None), (actual or None)


# ---------------------------------------------------------------------------
# Structural regexes
# ---------------------------------------------------------------------------

BANNER_RE = re.compile(
    r"OIL AND NATURAL GAS CORPORATION LTD\.[^\n]*\n"
    r"COMPANY\s*:\s*(?P<asset_name>[^\n]*?)\s*\n"
    r"DRILLING PROGRESS REPORT\s*\n"
    r"\(06:00 Hrs of (?P<start_date>[\d.]+) to 06:00 Hrs of (?P<end_date>[\d.]+)\)\s*\n"
    r"_{20,}\n?"
)

LITHO_WRAP_RE = re.compile(r"Litho:(.*?)\nObj No/Name:", re.DOTALL)

SECTION_SEP_RE = re.compile(r"\n?_{40,}\n?")

CATEGORY_RE = re.compile(r"^[A-Z][A-Z /]*WELLS$")

WELL_HEADER_RE = re.compile(
    r"^(?P<seq>\d+)\.(?P<well_name>\S+)\s+(?P<location_code>\S+)\s+"
    r"Type:\s*(?P<well_type>[^/]*)/\s*MODE:(?P<mode>[^/\s]*)\s*/WD:(?P<wd>[^\s]*)\s*"
    r"T\.Depth:(?P<target_depth>[\d,]*)\s*Pr\.Depth:(?P<present_depth>[\d,]*)\s*"
    r"Day Mtr:(?P<day_mtr>[\d,]*)\s*$"
)

START_LINE_RE = re.compile(
    r"^RB Start:\s*(?P<rb_start>[\d.]*)\s*DR\.Start:(?P<dr_start>[\d.]*)\s*"
    r"PT\.Start:(?P<pt_start>[\d.]*)\s*WO\.Start:CRep/OutCyl:(?P<crep_outcyl>[\d,./]*)\s*$"
)

DAYS_LINE_RE = re.compile(
    r"^Days RB\.P/A:(?P<rb_p>[\d,]*)/(?P<rb_a>[\d,]*)\s*"
    r"DR\.P/A:(?P<dr_p>[\d,]*)/(?P<dr_a>[\d,]*)\s*"
    r"PT\.P/A:(?P<pt_p>[\d,]*)/(?P<pt_a>[\d,]*)\s*"
    r"TOT\.P/A:(?P<tot_p>[\d,]*)/(?P<tot_a>[\d,]*)\s*"
    # WO P/A carries a trailing slash after the pair in every sample seen
    # (`WO P/A://` when blank, `WO P/A:45/40/` when populated) — not a typo.
    r"WO P/A:(?P<wo_p>[\d,]*)/(?P<wo_a>[\d,]*)/\s*$"
)

LA_MW_LOT_LITHO_RE = re.compile(
    r"^LA no/A\.Kick:(?P<la_no>[^/]*)/(?P<a_kick>[^\s]*)\s*"
    r"Mw wt/visc:(?P<mw>[\d.]*)/(?P<visc>[\d]*)\s*"
    r"Lot:(?P<lot_depth>[^/]*)/(?P<lot_val>[\d.]*)\s*"
    r"Litho:(?P<litho>.*)$"
)

OBJ_LINE_RE = re.compile(
    r"^Obj No/Name:(?P<obj_no>[^/]*)/(?P<obj_name>\S*)\s*"
    r"Obj days:(?P<obj_days>[\d]*)\s*Obj interval:(?P<obj_interval>.*)$"
)

COST_LINE_RE = re.compile(
    r"^Cost in INR\(Planned/Actual\):(?P<cost_p>[\d,.]*)\s*/\s*(?P<cost_a>[\d,.]*)\s*$"
)

NL1_LINE_RE = re.compile(
    r"^NL-1:\s*(?P<nl1>.*?)\s*Status:\s*(?P<status>.*?)\s*Cluster:\s*(?P<cluster>\S*)\s*$"
)

PHASE_ROW_RE = re.compile(
    r"^(?:(?P<phase_no>\d+)\s+)?"
    r"(?P<csg_size>\d+(?:\s\d+/\d+)?\")\s+"
    r"(?P<depth_p>[\d,]*)/(?P<depth_a>[\d,]*)\s+"
    r"(?P<days_p>[\d,]*)/(?P<days_a>[\d,]*)\s*"
    r"(?P<hole_top>\S*)\s*$"
)

HEADER_LINE_COUNT = 7  # well header .. NL-1/Status/Cluster (indices 0-6)
PHASE_ROWS_START = HEADER_LINE_COUNT + 2  # + short separator + phase-table header


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_dpr_text(raw_text: str) -> ParsedReport:
    """Parse the full text of one DPR PDF into a ParsedReport."""
    banner_match = BANNER_RE.search(raw_text)
    if not banner_match:
        raise DPRParseError("could not find the report banner (company/date range)")

    asset_name = banner_match.group("asset_name").strip()
    report_date = _parse_ddmmyyyy(banner_match.group("end_date"))

    text = BANNER_RE.sub("", raw_text)
    if "MOU PLAN:" in text:
        text = text.split("MOU PLAN:")[0]

    # Rejoin the two documented line-wrap hazards so the rest of parsing can
    # assume one field per line (see docs/02_data_dictionary.md §A.4).
    text = text.replace("WO\nP/A:", "WO P/A:")
    text = LITHO_WRAP_RE.sub(
        lambda m: "Litho:" + " ".join(m.group(1).split()) + "\nObj No/Name:", text
    )

    wells: list[ParsedWell] = []
    current_category: Optional[str] = None

    for chunk in SECTION_SEP_RE.split(text):
        lines = [line.strip() for line in chunk.split("\n") if line.strip()]
        if not lines:
            continue

        if CATEGORY_RE.match(lines[0]):
            current_category = lines[0]
            lines = lines[1:]
        if not lines:
            continue

        wells.append(_parse_well_block(lines, current_category))

    return ParsedReport(asset_name=asset_name, report_date=report_date, wells=wells)


def _parse_well_block(lines: list[str], category: Optional[str]) -> ParsedWell:
    if len(lines) < PHASE_ROWS_START:
        raise DPRParseError(f"well block too short ({len(lines)} lines): {lines!r}")

    header_m = WELL_HEADER_RE.match(lines[0])
    if not header_m:
        raise DPRParseError(f"could not parse well header line: {lines[0]!r}")

    start_m = START_LINE_RE.match(lines[1])
    if not start_m:
        raise DPRParseError(f"could not parse RB/DR/PT start line: {lines[1]!r}")

    days_m = DAYS_LINE_RE.match(lines[2])
    if not days_m:
        raise DPRParseError(f"could not parse Days P/A line: {lines[2]!r}")

    la_m = LA_MW_LOT_LITHO_RE.match(lines[3])
    if not la_m:
        raise DPRParseError(f"could not parse LA/Mw/Lot/Litho line: {lines[3]!r}")

    obj_m = OBJ_LINE_RE.match(lines[4])
    if not obj_m:
        raise DPRParseError(f"could not parse Obj line: {lines[4]!r}")

    cost_m = COST_LINE_RE.match(lines[5])
    if not cost_m:
        raise DPRParseError(f"could not parse Cost line: {lines[5]!r}")

    nl1_m = NL1_LINE_RE.match(lines[6])
    if not nl1_m:
        raise DPRParseError(f"could not parse NL-1/Status/Cluster line: {lines[6]!r}")

    try:
        oper_idx = next(i for i, line in enumerate(lines) if line.startswith("OPER:"))
    except StopIteration as exc:
        raise DPRParseError(f"no OPER narrative found in well block: {lines!r}") from exc

    phase_lines = lines[PHASE_ROWS_START:oper_idx]
    phases: list[ParsedPhase] = []
    for i, phase_line in enumerate(phase_lines):
        phase_m = PHASE_ROW_RE.match(phase_line)
        if not phase_m:
            raise DPRParseError(f"could not parse phase row: {phase_line!r}")
        phases.append(
            ParsedPhase(
                phase_no=_parse_int(phase_m.group("phase_no")) or (i + 1),
                casing_size=phase_m.group("csg_size"),
                depth_planned=_parse_float(phase_m.group("depth_p")),
                depth_actual=_parse_float(phase_m.group("depth_a")),
                days_planned=_parse_int(phase_m.group("days_p")),
                days_actual=_parse_int(phase_m.group("days_a")),
                hole_top=_parse_str(phase_m.group("hole_top")),
            )
        )

    narrative = re.sub(r"^OPER:\s*", "", "\n".join(lines[oper_idx:]))
    narrative = " ".join(narrative.split())

    crep_p, crep_a = _split_pair(start_m.group("crep_outcyl"))

    return ParsedWell(
        sequence_no=int(header_m.group("seq")),
        well_name=header_m.group("well_name"),
        location_code=header_m.group("location_code"),
        category=category,
        well_type=_parse_str(header_m.group("well_type")),
        mode=_parse_str(header_m.group("mode")),
        target_depth=_parse_float(header_m.group("target_depth")),
        present_depth=_parse_float(header_m.group("present_depth")),
        day_meterage=_parse_float(header_m.group("day_mtr")),
        rb_start=_parse_ddmmyyyy(start_m.group("rb_start")),
        dr_start=_parse_ddmmyyyy(start_m.group("dr_start")),
        pt_start=_parse_ddmmyyyy(start_m.group("pt_start")),
        crep_outcyl_planned=_parse_int(crep_p),
        crep_outcyl_actual=_parse_int(crep_a),
        rb_days_planned=_parse_int(days_m.group("rb_p")),
        rb_days_actual=_parse_int(days_m.group("rb_a")),
        dr_days_planned=_parse_int(days_m.group("dr_p")),
        dr_days_actual=_parse_int(days_m.group("dr_a")),
        pt_days_planned=_parse_int(days_m.group("pt_p")),
        pt_days_actual=_parse_int(days_m.group("pt_a")),
        tot_days_planned=_parse_int(days_m.group("tot_p")),
        tot_days_actual=_parse_int(days_m.group("tot_a")),
        wo_days_planned=_parse_int(days_m.group("wo_p")),
        wo_days_actual=_parse_int(days_m.group("wo_a")),
        la_no=_parse_str(la_m.group("la_no")),
        a_kick=_parse_str(la_m.group("a_kick")),
        mud_weight=_parse_float(la_m.group("mw")),
        mud_viscosity=_parse_float(la_m.group("visc")),
        lot_depth=_parse_float(la_m.group("lot_depth")),
        lot_value=_parse_float(la_m.group("lot_val")),
        litho=_parse_str(la_m.group("litho")),
        obj_no=_parse_str(obj_m.group("obj_no")),
        obj_name=_parse_str(obj_m.group("obj_name")),
        obj_days=_parse_int(obj_m.group("obj_days")),
        obj_interval=_parse_str(obj_m.group("obj_interval")),
        cost_planned_inr=_parse_float(cost_m.group("cost_p")),
        cost_actual_inr=_parse_float(cost_m.group("cost_a")),
        nl1=_parse_str(nl1_m.group("nl1")),
        status_text=_parse_str(nl1_m.group("status")),
        cluster=_parse_str(nl1_m.group("cluster")),
        oper_narrative=narrative,
        phases=phases,
    )
