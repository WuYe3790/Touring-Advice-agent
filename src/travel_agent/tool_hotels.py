from __future__ import annotations

from travel_agent.tool_clients import _rapidapi_headers, _rapidapi_host, _rapidapi_key, _request_json
from travel_agent.tool_data import HOTEL_CITY_ALIASES


def _hotel_city_queries(city: str) -> list[str]:
    raw = str(city or "").strip()
    if not raw:
        return []
    normalized = raw.removesuffix("市")
    alias = HOTEL_CITY_ALIASES.get(normalized) or HOTEL_CITY_ALIASES.get(raw)
    return list(dict.fromkeys(query for query in (raw, normalized, alias or "") if query))

def _booking_search_destinations(city: str) -> list[dict]:
    if not _rapidapi_key():
        return []
    host = _rapidapi_host()
    for query in _hotel_city_queries(city):
        data = _request_json(
            f"https://{host}/api/v1/hotels/searchDestination",
            {"query": query},
            timeout=20,
            headers=_rapidapi_headers(),
        )
        items = data.get("data") if isinstance(data.get("data"), list) else []
        if items:
            return items
    return []

def _booking_destination_id(destination: dict) -> tuple[str, str]:
    dest_id = destination.get("dest_id") or destination.get("city_ufi") or destination.get("id")
    dest_type = str(destination.get("dest_type") or "city").upper()
    if dest_type == "HOTEL":
        search_type = "HOTEL"
    elif dest_type in {"LANDMARK", "DISTRICT", "REGION", "AIRPORT"}:
        search_type = dest_type
    else:
        search_type = "CITY"
    return str(dest_id or ""), search_type
