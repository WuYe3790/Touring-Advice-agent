from __future__ import annotations

from datetime import datetime, timedelta

import requests
from langchain_core.tools import tool
from travel_agent.tool_formatters import (
    _first_non_empty,
    _format_aviationstack_flights,
    _format_money,
    _format_poi_lines,
    _log_tool_end,
    _log_tool_start,
    _poi_scalar,
)
from travel_agent.tool_clients import (
    AMAP_BASE_URL,
    AVIATIONSTACK_BASE_URL,
    _amap_key,
    _aviationstack_key,
    _rapidapi_headers,
    _rapidapi_host,
    _rapidapi_key,
    _request_json,
)
from travel_agent.tool_flights import (
    _normalize_airport_iata,
    _search_letsfg_local,
)
from travel_agent.tool_hotels import _booking_destination_id, _booking_search_destinations
from travel_agent.tool_weather import (
    get_air_quality_info,
    get_weather_alerts,
    get_weather_indices,
    get_weather_info,
)
from travel_agent.tool_transport import (
    get_bicycling_route,
    get_public_transit_plan,
    get_route_distance_matrix,
    get_traffic_status,
    get_transport_advice,
    get_walking_route,
)
from travel_agent.tool_maps import (
    _amap_geocode,
    _amap_marker_url,
    _geocode_many,
)


DEFAULT_DATE = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


@tool
def calculate_trip_budget(
    city: str,
    days: int,
    person_num: int,
    hotel_price_per_night: int,
    food_cost_per_day: int,
    attraction_fee: int,
) -> str:
    """计算旅行预算，只有用户明确给出费用参数时才应调用。

    Args:
        city: 目的地城市。
        days: 行程天数。
        person_num: 出行人数。
        hotel_price_per_night: 每人每晚住宿费用，单位元。
        food_cost_per_day: 每人每天餐饮费用，单位元。
        attraction_fee: 每人整个行程的景点门票总费用，单位元。
    """
    start = _log_tool_start(
        "calculate_trip_budget",
        city=city,
        days=days,
        person_num=person_num,
        hotel_price_per_night=hotel_price_per_night,
        food_cost_per_day=food_cost_per_day,
        attraction_fee=attraction_fee,
    )

    if not city or days <= 0 or person_num <= 0:
        return "预算计算失败：城市、天数、人数必须由用户明确提供且合法。"
    if hotel_price_per_night < 0 or food_cost_per_day < 0 or attraction_fee < 0:
        return "预算计算失败：费用不能为负数。"

    hotel_total = hotel_price_per_night * max(days - 1, 0) * person_num
    food_total = food_cost_per_day * days * person_num
    attraction_total = attraction_fee * person_num
    total = hotel_total + food_total + attraction_total

    result = (
        f"【{city}{days}天行程预算明细】\n"
        f"1. 酒店费用：{hotel_total}元（{max(days - 1, 0)}晚 x {person_num}人 x {hotel_price_per_night}元）\n"
        f"2. 餐饮费用：{food_total}元（{days}天 x {person_num}人 x {food_cost_per_day}元）\n"
        f"3. 景点门票：{attraction_total}元（{person_num}人 x {attraction_fee}元）\n"
        f"总预算：{total}元"
    )
    _log_tool_end("calculate_trip_budget", start, result)
    return result


@tool
def search_flight_options(
    departure: str = "",
    arrival: str = "",
    date: str = "",
    airline: str = "",
    flight_number: str = "",
    adults: int = 1,
    limit: int = 8,
) -> str:
    """优先使用 LetsFG 查询实时机票报价，失败或超时后回退 Aviationstack 航班时刻/状态。

    注意：LetsFG 本地实时搜索可能较慢；Aviationstack 只提供航班动态、机场、航空公司和计划/实际时刻信息，不提供机票价格。
    Args:
        departure: 出发机场 IATA 三字码或常见城市名，例如 "NGB"、"CGO"、"宁波"、"郑州"。
        arrival: 到达机场 IATA 三字码或常见城市名，例如 "HGH"、"成都"、"北京"。
        date: 可选，航班日期 YYYY-MM-DD。LetsFG 会按该日期搜索；Aviationstack 回退能力取决于账号套餐。
        airline: 可选，航空公司 IATA 代码，例如 "MU"、"CA"。
        flight_number: 可选，航班号数字部分，例如 MU2397 的 "2397"。
        adults: 成人乘客数，默认 1。
        limit: 返回结果数量，建议 3-10。
    """
    start = _log_tool_start(
        "search_flight_options",
        departure=departure,
        arrival=arrival,
        date=date,
        airline=airline,
        flight_number=flight_number,
        adults=adults,
        limit=limit,
    )
    dep_iata = _normalize_airport_iata(departure)
    arr_iata = _normalize_airport_iata(arrival)
    search_date = date or DEFAULT_DATE
    try:
        adults_count = max(1, min(int(adults), 9))
    except (TypeError, ValueError):
        adults_count = 1
    letsfg_result = ""
    if not airline and not flight_number:
        letsfg_result, letsfg_ok = _search_letsfg_local(dep_iata, arr_iata, search_date, limit, adults=adults_count)
        if letsfg_ok:
            _log_tool_end("search_flight_options", start, letsfg_result)
            return letsfg_result

    key = _aviationstack_key()
    if not key:
        result = (
            f"{letsfg_result}\n\n"
            "Aviationstack 回退不可用：未配置 AVIATIONSTACK_API_KEY。"
        ).strip()
        _log_tool_end("search_flight_options", start, result)
        return result

    params: dict[str, object] = {
        "access_key": key,
        "limit": max(1, min(int(limit), 20)),
    }
    if dep_iata:
        params["dep_iata"] = dep_iata
    if arr_iata:
        params["arr_iata"] = arr_iata
    if search_date:
        params["flight_date"] = search_date
    if airline:
        params["airline_iata"] = airline.strip().upper()
    if flight_number:
        params["flight_number"] = flight_number.strip().upper().removeprefix((airline or "").upper())

    try:
        data = _request_json(f"{AVIATIONSTACK_BASE_URL}/flights", params=params, timeout=15)
        if data.get("error"):
            error = data["error"]
            result = f"航班查询失败：{error.get('code', 'unknown')} - {error.get('message', error)}"
            _log_tool_end("search_flight_options", start, result)
            return result

        flights = data.get("data") or []
        if not flights:
            result = "未查询到符合条件的航班。可尝试只填写出发/到达机场三字码，或换用当天/近期日期。"
            _log_tool_end("search_flight_options", start, result)
            return result

        result = _format_aviationstack_flights(flights, dep_iata, arr_iata, limit)
        if letsfg_result:
            result = f"{letsfg_result}\n\nAviationstack 回退结果：\n{result}"
        _log_tool_end("search_flight_options", start, result)
        return result
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else ""
        if status_code == 403 and date:
            try:
                fallback_params = dict(params)
                fallback_params.pop("flight_date", None)
                fallback_data = _request_json(f"{AVIATIONSTACK_BASE_URL}/flights", params=fallback_params, timeout=15)
                flights = fallback_data.get("data") or []
                if flights:
                    result = _format_aviationstack_flights(
                        flights,
                        dep_iata,
                        arr_iata,
                        limit,
                        note=f"提示：当前 Aviationstack 账号不支持按指定日期 {search_date} 查询，已自动回退为近期/实时航班结果。",
                    )
                    if letsfg_result:
                        result = f"{letsfg_result}\n\nAviationstack 回退结果：\n{result}"
                    _log_tool_end("search_flight_options", start, result)
                    return result
            except Exception as fallback_exc:
                print(f"Aviationstack 日期查询失败后回退也失败：{fallback_exc}")
        result = f"{letsfg_result}\n\n航班查询暂不可用：HTTP {status_code or '未知'}。".strip()
        _log_tool_end("search_flight_options", start, result)
        return result
    except Exception as exc:
        result = f"{letsfg_result}\n\n航班查询异常：{exc}".strip()
        _log_tool_end("search_flight_options", start, result)
        return result


@tool
def search_travel_pois(city: str, keyword: str = "景点", limit: int = 8) -> str:
    """使用高德地图搜索目的地的景点、餐饮、商圈、酒店等 POI，用于生成更真实的行程推荐。

    Args:
        city: 查询城市，例如 "杭州"、"南京"。
        keyword: 搜索关键词，例如 "景点"、"博物馆"、"本地菜"、"酒店"、"商圈"。
        limit: 返回结果数量，建议 3-10。
    """
    start = _log_tool_start("search_travel_pois", city=city, keyword=keyword, limit=limit)
    key = _amap_key()
    if not key:
        result = "POI 查询不可用：未配置 AMAP_API_KEY。"
        _log_tool_end("search_travel_pois", start, result)
        return result

    try:
        data = _request_json(
            f"{AMAP_BASE_URL}/place/text",
            {
                "key": key,
                "keywords": keyword,
                "city": city,
                "citylimit": "true",
                "offset": max(1, min(int(limit), 20)),
                "page": 1,
                "extensions": "all",
                "output": "JSON",
            },
        )
        pois = data.get("pois") or []
        if data.get("status") != "1" or not pois:
            result = f"未在{city}找到与“{keyword}”相关的 POI。"
            _log_tool_end("search_travel_pois", start, result)
            return result

        lines = [f"数据源：高德地图", f"{city}“{keyword}”POI 推荐："]
        for index, poi in enumerate(pois[: max(1, min(int(limit), 20))], start=1):
            name = poi.get("name", "未知地点")
            poi_type = poi.get("type", "未知类型")
            address = poi.get("address") or "地址未提供"
            location = poi.get("location") or "坐标未知"
            tel = poi.get("tel") or "电话未提供"
            biz_ext = poi.get("biz_ext") or {}
            rating = _poi_scalar(biz_ext.get("rating"), "暂无评分")
            cost = _poi_scalar(biz_ext.get("cost"), "暂无人均")
            opentime = _poi_scalar(biz_ext.get("opentime"), "营业时间未提供")
            photos = poi.get("photos") or []
            photo_url = ""
            if photos and isinstance(photos[0], dict):
                photo_url = photos[0].get("url") or ""
            optional_parts = [
                f"评分 {rating}" if rating != "暂无评分" else "",
                f"人均 {cost}元" if cost != "暂无人均" else "",
                f"营业时间 {opentime}" if opentime != "营业时间未提供" else "",
                f"照片 {photo_url}" if photo_url else "",
            ]
            optional_text = "｜".join(part for part in optional_parts if part)
            lines.append(
                f"{index}. {name}｜{poi_type}｜{address}｜坐标 {location}｜电话 {tel}"
                + (f"｜{optional_text}" if optional_text else "")
            )
        result = "\n".join(lines)
        _log_tool_end("search_travel_pois", start, result)
        return result
    except Exception as exc:
        result = f"POI 查询异常：{exc}"
        _log_tool_end("search_travel_pois", start, result)
        return result


@tool
def search_nearby_pois(
    place: str,
    city: str = "",
    keyword: str = "餐饮",
    radius: int = 1500,
    limit: int = 8,
) -> str:
    """使用高德地图周边搜索查询某个景点、车站、酒店附近的餐饮、住宿、商圈或景点。
    Args:
        place: 中心地点，例如 "西湖"、"杭州东站"、"灵隐寺"。
        city: 中心地点所在城市，可选；地点名称模糊时建议填写。
        keyword: 周边搜索关键词，例如 "餐饮"、"酒店"、"咖啡"、"景点"、"地铁站"。
        radius: 搜索半径，单位米，建议 500-5000。
        limit: 返回结果数量，建议 3-10。
    """
    start = _log_tool_start(
        "search_nearby_pois",
        place=place,
        city=city,
        keyword=keyword,
        radius=radius,
        limit=limit,
    )
    key = _amap_key()
    if not key:
        result = "周边 POI 查询不可用：未配置 AMAP_API_KEY。"
        _log_tool_end("search_nearby_pois", start, result)
        return result

    try:
        center_info = _amap_geocode(place, city=city)
        if not center_info or not center_info.get("location"):
            result = f"周边 POI 查询失败：未能解析中心地点 {place}。"
            _log_tool_end("search_nearby_pois", start, result)
            return result

        safe_radius = max(100, min(int(radius), 50000))
        data = _request_json(
            f"{AMAP_BASE_URL}/place/around",
            {
                "key": key,
                "location": center_info["location"],
                "keywords": keyword,
                "radius": safe_radius,
                "offset": max(1, min(int(limit), 20)),
                "page": 1,
                "extensions": "all",
                "output": "JSON",
            },
        )
        pois = data.get("pois") or []
        if data.get("status") != "1" or not pois:
            result = (
                f"未在 {place} 周边 {safe_radius} 米内找到与“{keyword}”相关的 POI。"
                f"高德返回信息：{data.get('info', '无详细说明')}"
            )
            _log_tool_end("search_nearby_pois", start, result)
            return result

        title = (
            f"{center_info.get('formatted_address', place)} 周边 {safe_radius} 米"
            f"“{keyword}”推荐："
        )
        result = _format_poi_lines(title, pois, limit)
        _log_tool_end("search_nearby_pois", start, result)
        return result
    except Exception as exc:
        result = f"周边 POI 查询异常：{exc}"
        _log_tool_end("search_nearby_pois", start, result)
        return result


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


@tool
def get_place_location(place: str, city: str = "") -> str:
    """使用高德地图解析地点经纬度和标准地址，用于路线规划和地点核验。"""
    start = _log_tool_start("get_place_location", place=place, city=city)
    info = _amap_geocode(place, city=city)
    if not info:
        result = f"地点解析失败：未找到 {place}。"
        _log_tool_end("get_place_location", start, result)
        return result
    result = (
        "数据源：高德地图\n"
        f"查询地点：{place}\n"
        f"标准地址：{info.get('formatted_address', '未知')}\n"
        f"省市区：{info.get('province', '')}{info.get('city', '')}{info.get('district', '')}\n"
        f"经纬度：{info.get('location', '未知')}\n"
        f"匹配级别：{info.get('level', '未知')}"
    )
    _log_tool_end("get_place_location", start, result)
    return result


@tool
def get_map_marker_link(place: str, city: str = "") -> str:
    """生成高德地图地点标记链接，不暴露 API Key，适合在最终方案中给用户点击打开地点。

    Args:
        place: 地点名称，例如 "天一阁·月湖"、"宁波大学"。
        city: 地点所在城市，可选；地点名称模糊时建议填写。
    """
    start = _log_tool_start("get_map_marker_link", place=place, city=city)
    info = _amap_geocode(place, city=city)
    if not info or not info.get("location"):
        result = f"地图链接生成失败：未找到 {place} 的坐标。"
        _log_tool_end("get_map_marker_link", start, result)
        return result
    address = info.get("formatted_address") or place
    url = _amap_marker_url(info["location"], place)
    result = (
        "数据源：高德地图 URI\n"
        f"地点：{place}\n"
        f"标准地址：{address}\n"
        f"经纬度：{info.get('location', '未知')}\n"
        f"地图链接：{url}"
    )
    _log_tool_end("get_map_marker_link", start, result)
    return result


TRAVEL_TOOLS = [
    get_weather_info,
    get_air_quality_info,
    get_weather_alerts,
    get_weather_indices,
    calculate_trip_budget,
    get_transport_advice,
    search_flight_options,
    get_public_transit_plan,
    get_walking_route,
    get_bicycling_route,
    get_route_distance_matrix,
    get_traffic_status,
    search_travel_pois,
    search_nearby_pois,
    search_hotel_prices,
    get_place_location,
    get_map_marker_link,
]
