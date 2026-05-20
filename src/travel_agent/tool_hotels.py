from __future__ import annotations

from langchain_core.tools import tool

from travel_agent.tool_clients import _rapidapi_headers, _rapidapi_host, _rapidapi_key, _request_json
from travel_agent.tool_data import HOTEL_CITY_ALIASES
from travel_agent.tool_formatters import (
    _first_non_empty,
    _format_money,
    _log_tool_end,
    _log_tool_start,
)


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


@tool
def search_hotel_prices(
    city: str,
    checkin_date: str,
    checkout_date: str,
    adults: int = 2,
    rooms: int = 1,
    limit: int = 6,
    currency: str = "CNY",
) -> str:
    """使用 Booking.com RapidAPI 查询真实酒店价格，适合住宿推荐、预算估算和酒店价格对比。

    Args:
        city: 目的地城市，例如 "杭州"、"西安"、"Ningbo"。
        checkin_date: 入住日期，YYYY-MM-DD。
        checkout_date: 离店日期，YYYY-MM-DD。
        adults: 成人数量。
        rooms: 房间数量。
        limit: 返回酒店数量，建议 3-8。
        currency: 价格币种，默认 CNY。
    """
    start = _log_tool_start(
        "search_hotel_prices",
        city=city,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
        adults=adults,
        rooms=rooms,
        limit=limit,
        currency=currency,
    )
    if not _rapidapi_key():
        result = "酒店价格查询不可用：未配置 RAPIDAPI_KEY。"
        _log_tool_end("search_hotel_prices", start, result)
        return result

    try:
        destinations = _booking_search_destinations(city)
        if not destinations:
            result = f"酒店价格查询失败：Booking.com 未找到“{city}”对应目的地。"
            _log_tool_end("search_hotel_prices", start, result)
            return result

        destination = destinations[0]
        dest_id, search_type = _booking_destination_id(destination)
        if not dest_id:
            result = f"酒店价格查询失败：未能取得“{city}”的 Booking.com 目的地 ID。"
            _log_tool_end("search_hotel_prices", start, result)
            return result

        safe_limit = max(1, min(int(limit), 10))
        host = _rapidapi_host()
        data = _request_json(
            f"https://{host}/api/v1/hotels/searchHotels",
            {
                "dest_id": dest_id,
                "search_type": search_type,
                "arrival_date": checkin_date,
                "departure_date": checkout_date,
                "adults": max(1, int(adults)),
                "room_qty": max(1, int(rooms)),
                "currency_code": currency,
            },
            timeout=30,
            headers=_rapidapi_headers(),
        )
        hotels = ((data.get("data") or {}).get("hotels") or []) if isinstance(data.get("data"), dict) else []
        if data.get("status") is False or not hotels:
            result = (
                f"酒店价格查询无结果：{city} {checkin_date} 至 {checkout_date}。"
                f"RapidAPI 返回：{data.get('message', '无详细说明')}"
            )
            _log_tool_end("search_hotel_prices", start, result)
            return result

        destination_name = _first_non_empty(destination.get("name"), city)
        lines = [
            "数据源：Booking.com via RapidAPI",
            f"查询目的地：{destination_name}（dest_id={dest_id}, search_type={search_type}）",
            f"入住/离店：{checkin_date} → {checkout_date}；成人 {max(1, int(adults))}；房间 {max(1, int(rooms))}",
            "说明：价格为接口返回的实时参考总价，库存、税费和最终支付价以 Booking.com 页面为准。",
            "酒店价格结果：",
        ]
        for index, entry in enumerate(hotels[:safe_limit], start=1):
            prop = entry.get("property") or {}
            price = ((prop.get("priceBreakdown") or {}).get("grossPrice") or {})
            hotel_currency = _first_non_empty(price.get("currency"), currency, default=currency)
            total_price = _format_money(price.get("value"), hotel_currency)
            review = _first_non_empty(prop.get("reviewScore"), default="暂无评分")
            review_count = _first_non_empty(prop.get("reviewCount"), default="暂无评论数")
            review_word = _first_non_empty(prop.get("reviewScoreWord"), default="")
            stars = _first_non_empty(prop.get("propertyClass"), default="未知星级")
            location = ""
            if prop.get("longitude") and prop.get("latitude"):
                location = f"{prop.get('longitude')},{prop.get('latitude')}"
            photos = prop.get("photoUrls") or []
            photo_url = photos[0] if photos else ""
            checkin = prop.get("checkin") or {}
            checkout = prop.get("checkout") or {}
            optional_parts = [
                f"评分 {review}/10" if review != "暂无评分" else "",
                f"评论 {review_count}" if review_count != "暂无评论数" else "",
                f"口碑 {review_word}" if review_word else "",
                f"星级 {stars}" if stars != "未知星级" else "",
                f"坐标 {location}" if location else "",
                f"入住 {checkin.get('fromTime', '')}-{checkin.get('untilTime', '')}".strip("-") if checkin else "",
                f"离店 {checkout.get('untilTime', '')}" if checkout else "",
                f"照片 {photo_url}" if photo_url else "",
            ]
            lines.append(
                f"{index}. {prop.get('name', '未知酒店')}｜"
                f"{prop.get('wishlistName') or prop.get('address') or destination_name}｜"
                f"总价 {total_price}｜"
                + "｜".join(part for part in optional_parts if part)
            )
        result = "\n".join(lines)
        _log_tool_end("search_hotel_prices", start, result)
        return result
    except Exception as exc:
        result = f"酒店价格查询异常：{exc}"
        _log_tool_end("search_hotel_prices", start, result)
        return result
