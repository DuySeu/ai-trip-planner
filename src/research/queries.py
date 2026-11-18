"""The web search query for each kind of trip research, in the language of the destination."""

from __future__ import annotations

import calendar
from collections.abc import Mapping
from typing import Literal

from domain.trip_request import TripRequest

ResearchKind = Literal["accommodation", "transport", "local_transport", "activities", "food"]

VIETNAM = "VN"
STYLES_VI: Mapping[str, str] = {
    "relax": "nghỉ dưỡng",
    "adventure": "phiêu lưu",
    "culture": "văn hóa",
    "food": "ẩm thực",
    "nature": "thiên nhiên",
    "nightlife": "cuộc sống về đêm",
    "shopping": "mua sắm",
    "luxury": "sang trọng",
    "budget": "tiết kiệm",
}


# One query per research kind, in Vietnamese for a destination in Vietnam and in English otherwise.
# Dates are only a month, so trips to one place in one month share cache rows.
def build_queries(request: TripRequest) -> dict[ResearchKind, str]:
    place, origin = request.destination.name, request.origin
    start = request.start_date

    if request.destination.country_code == VIETNAM:
        styles = ", ".join(STYLES_VI[s] for s in request.travel_styles)
        return {
            "accommodation": f"khách sạn nơi ở {place} tháng {start.month} {start.year} giá mỗi đêm",
            "transport": f"đi từ {origin} đến {place} giá vé lịch trình",
            "local_transport": f"di chuyển tại {place} giá taxi xe buýt thuê xe máy",
            "activities": f"địa điểm tham quan hoạt động ở {place} {styles}",
            "food": f"quán ăn món ngon ở {place} giá",
        }

    styles = ", ".join(request.travel_styles)
    return {
        "accommodation": f"best hotels where to stay in {place} {calendar.month_name[start.month]}"
        f" {start.year} price per night",
        "transport": f"how to get from {origin} to {place} price schedule",
        "local_transport": f"getting around {place} local transport taxi bus prices",
        "activities": f"top things to do in {place} {styles}",
        "food": f"best local food and restaurants in {place} prices",
    }
