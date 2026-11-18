"""Fill the trip template with a plan and return the .xlsx bytes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook  # type: ignore[import-untyped]
from openpyxl.formatting.formatting import ConditionalFormattingList  # type: ignore[import-untyped]
from openpyxl.utils.cell import range_boundaries  # type: ignore[import-untyped]
from openpyxl.worksheet.worksheet import Worksheet  # type: ignore[import-untyped]

from domain.budget import cost_lines
from domain.currency import HOME_CURRENCY, to_vnd
from domain.plan import CATEGORY_LABELS_VI, ChecklistItem, Plan, PlanItem
from domain.trip_request import Language, TripRequest, budget_total_vnd

FIRST_ROW = 3
# The template's last Itinerary row and the last Checklist row that its formulas cover
TEMPLATE_LAST_ROW = 82
CHECKLIST_LAST_ROW = 31
OTHER_LABEL = "Khác"

STATUS_TEXT: Mapping[Language, Mapping[str, str]] = {
    "en": {"planned": "planned", "booked": "booked", "paid": "paid"},
    "vi": {"planned": "Dự kiến", "booked": "Đã đặt", "paid": "Đã thanh toán"},
}
ESTIMATE_TEXT: Mapping[Language, str] = {"en": "(estimate)", "vi": "(ước tính)"}
PER_PERSON_TEXT: Mapping[Language, str] = {"en": " per person", "vi": "/người"}
MODE_TEXT: Mapping[Language, Mapping[str, str]] = {
    "en": {m: m.capitalize() for m in ("flight", "train", "bus", "car", "motorbike", "boat")},
    "vi": {
        "flight": "Máy bay",
        "train": "Tàu hỏa",
        "bus": "Xe khách",
        "car": "Ô tô",
        "motorbike": "Xe máy",
        "boat": "Tàu thuyền",
    },
}
VI_STYLES = {
    "relax": "Nghỉ dưỡng",
    "adventure": "Phiêu lưu",
    "culture": "Văn hóa",
    "food": "Ẩm thực",
    "nature": "Thiên nhiên",
    "nightlife": "Cuộc sống về đêm",
    "shopping": "Mua sắm",
    "luxury": "Sang trọng",
    "budget": "Tiết kiệm",
}


# One Checklist row: label, price per person (None when unpriced), currency, ticked
Row = tuple[str, Decimal | None, str | None, bool]


# Fill the template with the plan and return the workbook as bytes
def export_plan(template: Path, plan: Plan, request: TripRequest) -> bytes:
    wb = load_workbook(template)
    itinerary, checklist = wb["Itinerary"], wb["Checklist"]
    local = plan.currencies.local
    currency = local or HOME_CURRENCY

    itinerary["A1"] = f"{request.destination.name} TRIP"
    itinerary["J3"], itinerary["K3"] = HOME_CURRENCY, 1
    itinerary["K8"] = request.travelers
    if local is not None and plan.currencies.local_to_home_rate is not None:
        itinerary["J4"], itinerary["K4"] = local, float(plan.currencies.local_to_home_rate)

    last_row = _fill_itinerary(itinerary, plan, request.language, currency)
    if last_row > TEMPLATE_LAST_ROW:
        checklist["C2"] = f"=SUM(Itinerary!E{FIRST_ROW}:E{last_row})"
    _fill_checklist(checklist, plan, request, currency)

    out = BytesIO()
    wb.save(out)
    return out.getvalue()


# A whole amount as an int, others as a float, so the cell reads 300000 and not 300000.0
def _num(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


# An amount for note text: thousands separators, up to two decimals
def _amount_text(value: Decimal) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


# The note column: the item's note, the price when it is not in column E, the estimate marker
def _note_text(item: PlanItem, in_column_e: bool, language: Language) -> str | None:
    parts = [item.note] if item.note else []
    priced = item.price_per_person > 0
    if priced and not in_column_e:
        amount = _amount_text(item.price_per_person)
        parts.append(f"{amount} {item.price_currency}{PER_PERSON_TEXT[language]}")
    if priced and item.price_basis == "estimate":
        parts.append(ESTIMATE_TEXT[language])
    return " ".join(parts) or None


# Write one row per item from row 3, a date on the first row of each day (the template's
# banding counts the filled dates); return the last row the formulas must cover
def _fill_itinerary(ws: Worksheet, plan: Plan, language: Language, currency: str) -> int:
    rows = [
        (day.date, item) for day in sorted(plan.days, key=lambda d: d.date) for item in day.items
    ]
    last_row = max(TEMPLATE_LAST_ROW, FIRST_ROW + len(rows) - 1)
    previous: date | None = None
    for row, (day, item) in enumerate(rows, start=FIRST_ROW):
        if day != previous:
            ws[f"A{row}"] = day
            ws[f"A{row}"].number_format = "dd/mm"
            previous = day
        if item.start_time:
            ws[f"B{row}"] = (
                f"{item.start_time}-{item.end_time}" if item.end_time else item.start_time
            )
        ws[f"C{row}"] = f"{item.title} ({item.location})" if item.location else item.title
        if item.transport_mode:
            ws[f"D{row}"] = MODE_TEXT[language][item.transport_mode]
        in_column_e = item.category == "transport" and item.price_currency == currency
        if in_column_e:
            ws[f"E{row}"] = _num(item.price_per_person)
        ws[f"G{row}"] = _note_text(item, in_column_e, language)
        ws[f"H{row}"] = STATUS_TEXT[language][item.status]

    if last_row > TEMPLATE_LAST_ROW:
        _extend_rows(ws, last_row)
    return last_row


# Give rows past the template's last one its formatting, banding and column F formula
def _extend_rows(ws: Worksheet, last_row: int) -> None:
    for row in range(TEMPLATE_LAST_ROW + 1, last_row + 1):
        for column in "ABCDEFGH":
            ws[f"{column}{row}"]._style = ws[f"{column}{TEMPLATE_LAST_ROW}"]._style
        ws[f"F{row}"] = f'=IF(E{row}="","",E{row}*$K$8)'

    old = ws.conditional_formatting
    ws.conditional_formatting = ConditionalFormattingList()
    for entry in old:
        min_col, min_row, max_col, _ = range_boundaries(str(entry.sqref))
        # Same columns, rows down to the new last row; each rule's formula stays relative
        for rule in entry.rules:
            ws.conditional_formatting.add(
                f"{ws.cell(min_row, min_col).coordinate}:{ws.cell(last_row, max_col).coordinate}",
                rule,
            )


# Cost rows per person: one per category and currency except transport in column E's currency
def _cost_rows(plan: Plan, travelers: int, currency: str) -> list[Row]:
    lines = cost_lines(plan.model_copy(update={"checklist": ()}), travelers)
    return [
        (CATEGORY_LABELS_VI[line.category], line.per_person, line.currency, False)
        for line in lines
        if not (line.category == "transport" and line.currency == currency)
    ]


# The checklist item as a row; a zero price means unpriced
def _item_row(entry: ChecklistItem) -> Row:
    if entry.price_per_person > 0:
        return (entry.label, entry.price_per_person, entry.price_currency, entry.done)
    return (entry.label, None, None, entry.done)


# Trip info in column L, then the cost rows and the checklist items from row 3
def _fill_checklist(ws: Worksheet, plan: Plan, request: TripRequest, currency: str) -> None:
    vi = request.language == "vi"
    styles = ", ".join(VI_STYLES[s] if vi else s.capitalize() for s in request.travel_styles)
    chosen = next((a for a in plan.accommodation if a.chosen), None)
    ws["L2"] = request.destination.name
    ws["L3"] = request.origin
    ws["L4"] = f"{request.start_date:%d/%m/%Y} - {request.end_date:%d/%m/%Y}"
    ws["L5"] = (request.end_date - request.start_date).days
    ws["L8"] = styles
    ws["L9"] = _num(budget_total_vnd(request) / request.travelers)
    if chosen is not None:
        ws["L12"] = ", ".join(filter(None, (chosen.name, chosen.area)))

    rows = _cost_rows(plan, request.travelers, currency)
    entries = [_item_row(c) for c in plan.checklist]
    free = CHECKLIST_LAST_ROW - FIRST_ROW + 1 - len(rows)
    if len(entries) > free:
        merged, entries = entries[free - 1 :], entries[: free - 1]
        total = sum((to_vnd(p, c, plan.currencies) for _, p, c, _ in merged if p and c), Decimal(0))
        entries.append((OTHER_LABEL, total or None, HOME_CURRENCY if total else None, False))

    for row, (label, price, unit, done) in enumerate(rows + entries, start=FIRST_ROW):
        ws[f"A{row}"] = "☑" if done else "☐"
        ws[f"B{row}"] = label
        if price is not None:
            ws[f"C{row}"] = _num(price)
            ws[f"E{row}"] = unit
