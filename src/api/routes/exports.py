"""Download a trip's current plan as an Excel file."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Response

from api.deps import Conn, Deps
from api.schemas.trips import trip_request
from core.exceptions import Conflict
from db.repositories import trips
from domain.plan import Plan
from utils.xlsx_exporter import export_plan

router = APIRouter()

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SAFE_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._-")
FALLBACK_NAME = "trip"


# A plain ASCII file name: accents folded, Vietnamese D with stroke as D, anything else unsafe as _
def ascii_file_name(name: str) -> str:
    stroked = name.replace("Đ", "D").replace("đ", "d")
    folded = unicodedata.normalize("NFKD", stroked).encode("ascii", "ignore").decode("ascii")
    safe = "".join(ch if ch in SAFE_NAME_CHARS else "_" for ch in folded).strip(" ._")
    return safe or FALLBACK_NAME


# GET /trips/{trip_id}/export.xlsx - Download the current plan
@router.get("/trips/{trip_id}/export.xlsx")
def export_trip(trip_id: UUID, conn: Conn, deps: Deps) -> Response:
    row = trips.get_trip(conn, trip_id)
    if row.plan is None:
        raise Conflict("The plan is not ready yet")

    content = export_plan(
        Path(deps.settings.template_path), Plan.model_validate(row.plan), trip_request(row)
    )
    # Both forms of the name: plain ASCII for old clients, UTF-8 (RFC 5987) for the real one
    disposition = (
        f'attachment; filename="{ascii_file_name(row.destination_name)}.xlsx"; '
        f"filename*=UTF-8''{quote(row.destination_name, safe='')}.xlsx"
    )
    return Response(
        content=content, media_type=XLSX_TYPE, headers={"Content-Disposition": disposition}
    )
