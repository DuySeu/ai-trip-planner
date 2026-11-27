"""Outside hosts of the backend: the API URLs it calls and the domains each web search may read."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

# Open-Meteo: place name to coordinates, forecast for the next days, and past days
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Nominatim (OpenStreetMap): coordinates to a place name; at most 1 request per second
REVERSE_GEOCODING_URL = "https://nominatim.openstreetmap.org/reverse"

# ExchangeRate-API open endpoint: rates of one base currency, updated daily
RATES_URL = "https://open.er-api.com/v6/latest/{base}"

# The kinds of web search the backend runs. The first five are the research of a trip, "chat" is
# a question asked in a conversation, "discovery" is the search for places to go
SearchTask = Literal[
    "accommodation", "transport", "local_transport", "activities", "food", "chat", "discovery"
]

# Domains each task prefers (Tavily include_domains with include_domains_mode "prefer": the rest
# of the web may still answer). A task with an empty tuple searches the whole web.
GUIDES = ("tripadvisor.com", "lonelyplanet.com", "wikivoyage.org")
SEARCH_DOMAINS: Mapping[SearchTask, tuple[str, ...]] = {
    "accommodation": (
        "booking.com",
        "agoda.com",
        "traveloka.com",
    ),
    "transport": (
        "rome2rio.com",
        "12go.asia",
        "skyscanner.com",
        "traveloka.com",
        "vexere.com",
        "dsvn.vn",
    ),
    "local_transport": ("rome2rio.com", *GUIDES),
    "activities": ("klook.com", "viator.com", "getyourguide.com", "vietnam.travel", *GUIDES),
    "food": ("foody.vn", "guide.michelin.com", *GUIDES),
    "chat": GUIDES,
    "discovery": ("vietnam.travel", *GUIDES),
}

# Tasks whose search boosts pages from the destination's country (Tavily country). Not transport:
# a route crosses countries; not discovery: there is no destination yet
COUNTRY_TASKS: frozenset[SearchTask] = frozenset(
    {"accommodation", "local_transport", "activities", "food", "chat"}
)
# Tasks that read prices, so Tavily's cached copy of a page may be at most this many hours old
FRESH_TASKS: frozenset[SearchTask] = frozenset({"accommodation", "transport"})
PRICE_MAX_AGE_HOURS = 72

# ISO 3166-1 alpha-2 -> the name Tavily's country parameter takes; a country missing here gets no
# boost
TAVILY_COUNTRY: Mapping[str, str] = {
    "AD": "andorra",
    "AE": "united arab emirates",
    "AF": "afghanistan",
    "AL": "albania",
    "AM": "armenia",
    "AO": "angola",
    "AR": "argentina",
    "AT": "austria",
    "AU": "australia",
    "AZ": "azerbaijan",
    "BA": "bosnia and herzegovina",
    "BB": "barbados",
    "BD": "bangladesh",
    "BE": "belgium",
    "BF": "burkina faso",
    "BG": "bulgaria",
    "BH": "bahrain",
    "BI": "burundi",
    "BJ": "benin",
    "BN": "brunei",
    "BO": "bolivia",
    "BR": "brazil",
    "BS": "bahamas",
    "BT": "bhutan",
    "BW": "botswana",
    "BY": "belarus",
    "BZ": "belize",
    "CA": "canada",
    "CF": "central african republic",
    "CG": "congo",
    "CH": "switzerland",
    "CL": "chile",
    "CM": "cameroon",
    "CN": "china",
    "CO": "colombia",
    "CR": "costa rica",
    "CU": "cuba",
    "CV": "cape verde",
    "CY": "cyprus",
    "CZ": "czech republic",
    "DE": "germany",
    "DJ": "djibouti",
    "DK": "denmark",
    "DO": "dominican republic",
    "DZ": "algeria",
    "EC": "ecuador",
    "EE": "estonia",
    "EG": "egypt",
    "ER": "eritrea",
    "ES": "spain",
    "ET": "ethiopia",
    "FI": "finland",
    "FJ": "fiji",
    "FR": "france",
    "GA": "gabon",
    "GB": "united kingdom",
    "GE": "georgia",
    "GH": "ghana",
    "GM": "gambia",
    "GN": "guinea",
    "GQ": "equatorial guinea",
    "GR": "greece",
    "GT": "guatemala",
    "HN": "honduras",
    "HR": "croatia",
    "HT": "haiti",
    "HU": "hungary",
    "ID": "indonesia",
    "IE": "ireland",
    "IL": "israel",
    "IN": "india",
    "IQ": "iraq",
    "IR": "iran",
    "IS": "iceland",
    "IT": "italy",
    "JM": "jamaica",
    "JO": "jordan",
    "JP": "japan",
    "KE": "kenya",
    "KG": "kyrgyzstan",
    "KH": "cambodia",
    "KM": "comoros",
    "KP": "north korea",
    "KR": "south korea",
    "KW": "kuwait",
    "KZ": "kazakhstan",
    "LB": "lebanon",
    "LI": "liechtenstein",
    "LK": "sri lanka",
    "LR": "liberia",
    "LS": "lesotho",
    "LT": "lithuania",
    "LU": "luxembourg",
    "LV": "latvia",
    "LY": "libya",
    "MA": "morocco",
    "MC": "monaco",
    "MD": "moldova",
    "ME": "montenegro",
    "MG": "madagascar",
    "MK": "north macedonia",
    "ML": "mali",
    "MM": "myanmar",
    "MN": "mongolia",
    "MR": "mauritania",
    "MT": "malta",
    "MU": "mauritius",
    "MV": "maldives",
    "MW": "malawi",
    "MX": "mexico",
    "MY": "malaysia",
    "MZ": "mozambique",
    "NA": "namibia",
    "NE": "niger",
    "NG": "nigeria",
    "NI": "nicaragua",
    "NL": "netherlands",
    "NO": "norway",
    "NP": "nepal",
    "NZ": "new zealand",
    "OM": "oman",
    "PA": "panama",
    "PE": "peru",
    "PG": "papua new guinea",
    "PH": "philippines",
    "PK": "pakistan",
    "PL": "poland",
    "PT": "portugal",
    "PY": "paraguay",
    "QA": "qatar",
    "RO": "romania",
    "RS": "serbia",
    "RU": "russia",
    "RW": "rwanda",
    "SA": "saudi arabia",
    "SD": "sudan",
    "SE": "sweden",
    "SG": "singapore",
    "SI": "slovenia",
    "SK": "slovakia",
    "SN": "senegal",
    "SO": "somalia",
    "SS": "south sudan",
    "SV": "el salvador",
    "SY": "syria",
    "TD": "chad",
    "TG": "togo",
    "TH": "thailand",
    "TJ": "tajikistan",
    "TM": "turkmenistan",
    "TN": "tunisia",
    "TR": "turkey",
    "TT": "trinidad and tobago",
    "TW": "taiwan",
    "TZ": "tanzania",
    "UA": "ukraine",
    "UG": "uganda",
    "US": "united states",
    "UY": "uruguay",
    "UZ": "uzbekistan",
    "VE": "venezuela",
    "VN": "vietnam",
    "YE": "yemen",
    "ZA": "south africa",
    "ZM": "zambia",
    "ZW": "zimbabwe",
}
