from __future__ import annotations

import zipfile
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from openpyxl.worksheet.worksheet import Worksheet  # type: ignore[import-untyped]

from domain.budget import total_cost_vnd
from domain.plan import ChecklistItem, Plan
from domain.trip_request import TripRequest
from tests.fixtures.builders import bangkok_plan, bangkok_request, dalat_plan, dalat_request
from utils.xlsx_exporter import export_plan

TEMPLATE = Path(__file__).parents[2] / "data" / "trip-template.xlsx"
# The sums are floats in the cells and Decimals in the plan; one cent of VND is far below any visible
TOLERANCE = Decimal("0.01")


# Export and reopen the bytes
def export(plan: Plan, request: TripRequest) -> Workbook:
    return load_workbook(BytesIO(export_plan(TEMPLATE, plan, request)))


# The group's cost in VND read back from the written cells with the template's own conversion:
# a cell's price x K8 x the rate that the J3:K6 table gives for its currency
def written_total(wb: Workbook) -> Decimal:
    itinerary, checklist = wb["Itinerary"], wb["Checklist"]
    rates = {
        row[0].value: Decimal(str(row[1].value))
        for row in itinerary["J3:K6"]
        if row[0].value is not None
    }
    travelers = Decimal(str(itinerary["K8"].value))
    transport_currency = itinerary["J4"].value or itinerary["J3"].value
    per_person = sum(
        (
            Decimal(str(c.value)) * rates[transport_currency]
            for (c,) in itinerary["E3:E1000"]
            if c.value is not None
        ),
        Decimal(0),
    )
    for price, _, unit in checklist["C3:E31"]:
        if price.value is not None:
            per_person += Decimal(str(price.value)) * rates[unit.value]
    return per_person * travelers


# Every cell with a value, by coordinate
def filled_cells(ws: Worksheet) -> dict[str, object]:
    return {c.coordinate: c.value for row in ws.iter_rows() for c in row if c.value is not None}


# The Itinerary rows that hold an item: those with a title in column C
def item_rows(ws: Worksheet) -> list[int]:
    return [r for r in range(3, ws.max_row + 1) if ws[f"C{r}"].value]


# The Bangkok plan with the chosen stay costing a non-terminating amount per person
def awkward_bangkok() -> tuple[Plan, TripRequest]:
    plan = bangkok_plan()
    stays = tuple(
        a.model_copy(update={"price_per_night": Decimal(1000)}) if a.chosen else a
        for a in plan.accommodation
    )
    return plan.model_copy(update={"accommodation": stays}), bangkok_request(travelers=3)


def test_domestic_trip_fills_title_currency_headcount():
    ws = export(dalat_plan(), dalat_request())["Itinerary"]
    assert (ws["A1"].value, ws["J3"].value, ws["K3"].value, ws["K8"].value) == (
        "Đà Lạt TRIP",
        "VND",
        1,
        4,
    )
    assert ws["J4"].value is None
    assert ws["K4"].value is None


def test_abroad_trip_sets_local_currency_and_rate_in_j4_k4():
    ws = export(bangkok_plan(), bangkok_request())["Itinerary"]
    assert (ws["A1"].value, ws["J3"].value, ws["K3"].value) == ("Bangkok TRIP", "VND", 1)
    assert (ws["J4"].value, ws["K4"].value, ws["K8"].value) == ("THB", 720.5, 2)


def test_itinerary_rows_follow_the_plan_with_a_date_on_each_days_first_row():
    plan = dalat_plan()
    ws = export(plan, dalat_request())["Itinerary"]
    items = [(d.date, i) for d in plan.days for i in d.items]
    rows = item_rows(ws)
    assert len(rows) == len(items)
    # openpyxl reads a date cell back as a datetime
    assert [ws[f"A{r}"].value for r in rows if ws[f"A{r}"].value] == [
        datetime(d.date.year, d.date.month, d.date.day) for d in plan.days
    ]
    first = rows[0]
    assert ws[f"B{first}"].value == "06:30-13:00"
    assert ws[f"C{first}"].value == "Xe giường nằm Phương Trang TP.HCM - Đà Lạt (Bến xe Miền Đông)"
    assert ws[f"D{first}"].value == "Xe khách"
    assert ws[f"H{first}"].value == "Dự kiến"


def test_only_transport_prices_go_in_itinerary_column_e():
    plan = dalat_plan()
    ws = export(plan, dalat_request())["Itinerary"]
    items = [i for d in plan.days for i in d.items]
    by_row = dict(zip(item_rows(ws), items, strict=True))
    for row, item in by_row.items():
        if item.category == "transport":
            assert ws[f"E{row}"].value == item.price_per_person
        else:
            assert ws[f"E{row}"].value is None
    food = next(r for r, i in by_row.items() if i.category == "food" and i.price_per_person > 0)
    assert "VND/người" in ws[f"G{food}"].value


def test_non_transport_price_and_estimate_marker_go_in_the_note_by_language():
    vi = export(dalat_plan(), dalat_request())["Itinerary"]
    en = export(bangkok_plan(), bangkok_request())["Itinerary"]
    lunch_vi = next(r for r in item_rows(vi) if vi[f"C{r}"].value.startswith("Cơm trưa gà nướng"))
    lunch_en = next(r for r in item_rows(en) if en[f"C{r}"].value.startswith("Lunch: pad thai"))
    assert vi[f"G{lunch_vi}"].value == "120,000 VND/người (ước tính)"
    assert en[f"G{lunch_en}"].value == "350 THB per person (estimate)"


def test_vnd_priced_transport_abroad_goes_to_checklist_row_with_vnd_unit():
    wb = export(bangkok_plan(), bangkok_request())
    itinerary, checklist = wb["Itinerary"], wb["Checklist"]
    flight = next(
        r for r in item_rows(itinerary) if itinerary[f"C{r}"].value.startswith("Flight SGN")
    )
    assert itinerary[f"E{flight}"].value is None
    assert "2,500,000 VND per person" in itinerary[f"G{flight}"].value
    rows = [r for r in range(3, 32) if checklist[f"B{r}"].value == "Đi lại"]
    assert [(checklist[f"C{r}"].value, checklist[f"E{r}"].value) for r in rows] == [
        (5100000, "VND")
    ]


def test_checklist_lists_costs_then_items_with_trip_info_in_column_l():
    ws = export(bangkok_plan(), bangkok_request())["Checklist"]
    rows = [
        (ws[f"B{r}"].value, ws[f"C{r}"].value, ws[f"E{r}"].value, ws[f"A{r}"].value)
        for r in range(3, 32)
        if ws[f"B{r}"].value
    ]
    assert rows == [
        ("Đi lại", 5100000, "VND", "☐"),
        ("Lưu trú", 3600, "THB", "☐"),
        ("Ăn uống", 2800, "THB", "☐"),
        ("Mua sắm", 700, "THB", "☐"),
        ("Thăm quan", 1400, "THB", "☐"),
        ("Travel insurance", 350000, "VND", "☐"),
        ("Check passports are valid for 6 more months", None, None, "☑"),
        ("Buy a Rabbit card for the BTS", 200, "THB", "☐"),
    ]
    assert [ws[f"L{r}"].value for r in (2, 3, 4, 5, 8, 9, 12)] == [
        "Bangkok",
        "Ho Chi Minh City",
        "20/12/2026 - 24/12/2026",
        4,
        "Culture, Food",
        20000000,
        "Sukhumvit 11 Boutique Hotel, Sukhumvit",
    ]
    assert ws["C2"].value == "=SUM(Itinerary!E3:E82)"
    assert ws["B2"].value == "Di chuyển/Đi lại"


def test_trip_without_budget_writes_the_plan_cost_per_person_as_budget():
    plan, request = dalat_plan(), dalat_request(budget_amount=None, budget_scope=None)
    ws = export(plan, request)["Checklist"]
    per_person = total_cost_vnd(plan, request.travelers) / request.travelers
    assert ws["L9"].value == pytest.approx(float(per_person))


def test_vietnamese_trip_writes_trip_info_in_vietnamese():
    ws = export(dalat_plan(), dalat_request())["Checklist"]
    assert ws["L8"].value == "Thiên nhiên, Ẩm thực"


@pytest.mark.parametrize(
    ("plan", "request_"),
    [
        (dalat_plan(), dalat_request()),
        (bangkok_plan(), bangkok_request()),
        awkward_bangkok(),
    ],
    ids=["domestic", "abroad", "abroad_three_travelers_odd_stay"],
)
def test_written_costs_add_up_to_plan_total(plan: Plan, request_: TripRequest) -> None:
    wb = export(plan, request_)
    assert abs(written_total(wb) - total_cost_vnd(plan, request_.travelers)) <= TOLERANCE


def test_more_than_80_items_extends_formulas_and_checklist_sum():
    plan = dalat_plan()
    first = plan.days[0]
    many = first.model_copy(update={"items": first.items * 23})
    plan = plan.model_copy(update={"days": (many, *plan.days[1:])})
    n = sum(len(d.items) for d in plan.days)
    last = 2 + n
    assert last > 82
    wb = export(plan, dalat_request())
    ws = wb["Itinerary"]
    assert ws["F83"].value == '=IF(E83="","",E83*$K$8)'
    assert ws[f"F{last}"].value == f'=IF(E{last}="","",E{last}*$K$8)'
    assert ws[f"F{last + 1}"].value is None
    assert wb["Checklist"]["C2"].value == f"=SUM(Itinerary!E3:E{last})"
    assert ws.conditional_formatting and all(
        str(cf.sqref).endswith(str(last)) for cf in ws.conditional_formatting
    )
    assert abs(written_total(wb) - total_cost_vnd(plan, 4)) <= TOLERANCE


def test_template_validations_and_currencies_name_survive():
    template = load_workbook(TEMPLATE)
    exported = export(dalat_plan(), dalat_request())

    # Every kind of template feature a load and save can drop, read the same way from both files
    def features(wb: Workbook) -> dict[str, Any]:
        return {
            "names": {n: d.attr_text for n, d in wb.defined_names.items()},
            "validations": {
                ws.title: sorted(
                    (str(v.sqref), v.type, v.formula1, v.operator)
                    for v in ws.data_validations.dataValidation
                )
                for ws in wb
            },
            "formatting": {
                ws.title: sorted(
                    (str(cf.sqref), [r.formula[0] for r in cf.rules])
                    for cf in ws.conditional_formatting
                )
                for ws in wb
            },
            "merged": {ws.title: sorted(str(r) for r in ws.merged_cells.ranges) for ws in wb},
            "tables": {ws.title: dict(ws.tables.items()) for ws in wb},
            "charts": {ws.title: len(ws._charts) for ws in wb},
            "links": {ws.title: [h.target for h in ws._hyperlinks] for ws in wb},
        }

    assert features(exported) == features(template)
    assert features(template)["names"] == {"Currencies": "Itinerary!$J$3:$J$6"}
    assert features(template)["validations"]["Checklist"]
    with zipfile.ZipFile(BytesIO(export_plan(TEMPLATE, dalat_plan(), dalat_request()))) as z:
        assert "xl/charts/chart1.xml" in z.namelist()


def test_template_formulas_outside_the_filled_cells_are_kept():
    template = load_workbook(TEMPLATE)["Checklist"]
    ws = export(dalat_plan(), dalat_request())["Checklist"]
    for coord in ("D3", "G2", "G31", "L6", "L10", "L11"):
        assert ws[coord].value == template[coord].value


def test_summary_sheet_left_empty():
    template = load_workbook(TEMPLATE)["Summary"]
    ws = export(dalat_plan(), dalat_request())["Summary"]
    assert filled_cells(ws) == filled_cells(template)


def test_checklist_overflow_merges_into_khac_row():
    plan = bangkok_plan()
    extra = tuple(
        ChecklistItem(
            label=f"Extra {n}",
            price_per_person=Decimal(100 * n),
            price_currency="THB" if n % 2 else "VND",
            category="service",
        )
        for n in range(1, 41)
    )
    plan = plan.model_copy(update={"checklist": plan.checklist + extra})
    wb = export(plan, bangkok_request())
    ws = wb["Checklist"]
    assert ws["B31"].value == "Khác"
    assert ws["E31"].value == "VND"
    assert ws["B32"].value is None
    assert ws["B30"].value != "Khác"
    assert abs(written_total(wb) - total_cost_vnd(plan, 2)) <= TOLERANCE


def test_checklist_item_marked_done_is_ticked():
    plan = dalat_plan()
    done = plan.checklist[0].model_copy(update={"done": True})
    plan = plan.model_copy(update={"checklist": (done, *plan.checklist[1:])})
    ws = export(plan, dalat_request())["Checklist"]
    row = next(r for r in range(3, 32) if ws[f"B{r}"].value == done.label)
    assert ws[f"A{row}"].value == "☑"
