from __future__ import annotations

import time
import os
import re
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool


DEFAULT_DATE = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

WEATHER_CODES = {
    0: "晴朗",
    1: "主要晴朗",
    2: "部分多云",
    3: "阴天",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "中度毛毛雨",
    55: "强毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    95: "雷雨",
    96: "雷雨伴冰雹",
    99: "强雷雨伴冰雹",
}

AMAP_BASE_URL = "https://restapi.amap.com/v3"
# Aviationstack free-tier keys commonly reject HTTPS with HTTP 403.
AVIATIONSTACK_BASE_URL = "http://api.aviationstack.com/v1"
COORDINATE_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
AIRPORT_IATA_BY_CITY = {
    "北京": "PEK",
    "北京首都": "PEK",
    "大兴": "PKX",
    "上海": "SHA",
    "上海虹桥": "SHA",
    "上海浦东": "PVG",
    "广州": "CAN",
    "深圳": "SZX",
    "成都": "TFU",
    "成都天府": "TFU",
    "成都双流": "CTU",
    "重庆": "CKG",
    "杭州": "HGH",
    "宁波": "NGB",
    "郑州": "CGO",
    "南京": "NKG",
    "武汉": "WUH",
    "长沙": "CSX",
    "西安": "XIY",
    "昆明": "KMG",
    "厦门": "XMN",
    "青岛": "TAO",
    "天津": "TSN",
    "济南": "TNA",
    "福州": "FOC",
    "三亚": "SYX",
    "海口": "HAK",
    "哈尔滨": "HRB",
    "沈阳": "SHE",
    "大连": "DLC",
    "乌鲁木齐": "URC",
    "贵阳": "KWE",
    "南宁": "NNG",
    "太原": "TYN",
    "兰州": "LHW",
    "呼和浩特": "HET",
    "长春": "CGQ",
    "拉萨": "LXA",
    "张家界": "DYG",
}


def _get_env_key(name: str) -> str:
    load_dotenv()
    return os.getenv(name, "").strip()


def _request_json(url: str, params: dict[str, object], timeout: int = 10, headers: dict[str, str] | None = None) -> dict:
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _amap_key() -> str:
    return _get_env_key("AMAP_API_KEY")


def _aviationstack_key() -> str:
    return _get_env_key("AVIATIONSTACK_API_KEY")


def _qweather_key() -> str:
    return _get_env_key("QWEATHER_API_KEY")


def _qweather_host() -> str:
    return _get_env_key("QWEATHER_API_HOST").removeprefix("https://").removeprefix("http://").strip("/")


def _qweather_headers() -> dict[str, str]:
    return {"X-QW-Api-Key": _qweather_key()}


def _qweather_lookup(city: str) -> dict | None:
    qweather_key = _qweather_key()
    qweather_host = _qweather_host()
    if not qweather_key or not qweather_host:
        return None
    geo_data = _request_json(
        f"https://{qweather_host}/geo/v2/city/lookup",
        {"location": city, "lang": "zh"},
        headers=_qweather_headers(),
    )
    locations = geo_data.get("location") or []
    return locations[0] if locations else None


def _amap_geocode(address: str, city: str = "") -> dict | None:
    key = _amap_key()
    if not key:
        return None
    coordinate = _normalize_coordinate(address)
    if coordinate:
        return {
            "location": coordinate,
            "formatted_address": address,
            "province": "",
            "city": city,
            "district": "",
            "level": "经纬度",
        }

    city_candidates = []
    if city:
        city_candidates.extend([city, f"{city}市" if not city.endswith("市") else city])
    city_candidates.append("")
    for city_name in dict.fromkeys(city_candidates):
        data = _request_json(
            f"{AMAP_BASE_URL}/geocode/geo",
            {"key": key, "address": address, "city": city_name or None, "output": "JSON"},
        )
        if data.get("status") == "1" and data.get("geocodes"):
            return data["geocodes"][0]

    for city_name in dict.fromkeys(city_candidates):
        data = _request_json(
            f"{AMAP_BASE_URL}/place/text",
            {
                "key": key,
                "keywords": address,
                "city": city_name or None,
                "citylimit": "true" if city_name else "false",
                "offset": 1,
                "page": 1,
                "extensions": "base",
                "output": "JSON",
            },
        )
        pois = data.get("pois") or []
        if data.get("status") == "1" and pois:
            poi = pois[0]
            return {
                "location": poi.get("location", ""),
                "formatted_address": poi.get("address") or poi.get("name") or address,
                "province": poi.get("pname", ""),
                "city": poi.get("cityname", city),
                "district": poi.get("adname", ""),
                "level": "POI",
            }
    return None


def _normalize_coordinate(value: str) -> str | None:
    match = COORDINATE_RE.match(str(value or ""))
    if not match:
        return None
    lon = float(match.group(1))
    lat = float(match.group(2))
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        return f"{lon:.6f},{lat:.6f}"
    return None


def _amap_location(address: str, city: str = "") -> tuple[str, str] | None:
    info = _amap_geocode(address, city=city)
    if not info or not info.get("location"):
        return None
    return info["location"], info.get("formatted_address") or address


def _resolve_route_points(origin: str, destination: str, city: str = "") -> tuple[str, str, str, str] | None:
    origin_info = _amap_location(origin, city=city)
    destination_info = _amap_location(destination, city=city)
    if not origin_info or not destination_info:
        return None
    origin_location, origin_address = origin_info
    destination_location, destination_address = destination_info
    return origin_location, origin_address, destination_location, destination_address


def _format_minutes(seconds: int | float | str) -> str:
    try:
        minutes = max(1, round(float(seconds) / 60))
    except (TypeError, ValueError):
        return "未知"
    if minutes >= 60:
        hours = minutes // 60
        rest = minutes % 60
        return f"{hours}小时{rest}分钟" if rest else f"{hours}小时"
    return f"{minutes}分钟"


def _format_km(meters: int | float | str) -> str:
    try:
        km = float(meters) / 1000
    except (TypeError, ValueError):
        return "未知"
    return f"{km:.1f}公里"


def _format_route_steps(steps: list[dict], limit: int = 6) -> str:
    items = []
    for step in steps[:limit]:
        instruction = _first_non_empty(step.get("instruction"), step.get("road"), default="")
        distance = step.get("distance")
        if instruction:
            items.append(f"{instruction}（{_format_km(distance)}）" if distance else instruction)
    return "；".join(items) if items else "未返回详细步骤"


def _format_distance_matrix_type(travel_type: str) -> tuple[str, int]:
    normalized = str(travel_type or "driving").strip().lower()
    if normalized in {"walking", "walk", "步行"}:
        return "步行", 3
    if normalized in {"straight", "linear", "distance", "直线"}:
        return "直线距离", 0
    return "驾车", 1


def _city_name_from_geocode(info: dict | None, fallback: str) -> str:
    if not info:
        return fallback
    city = info.get("city")
    if isinstance(city, list):
        city = city[0] if city else ""
    province = info.get("province")
    if isinstance(province, list):
        province = province[0] if province else ""
    return str(city or province or fallback)


def _poi_scalar(value: object, default: str = "") -> str:
    if value is None or value == [] or value == {}:
        return default
    if isinstance(value, list):
        return str(value[0]) if value else default
    return str(value)


def _format_transit_cost(cost: object) -> str:
    value = _poi_scalar(cost, "")
    if not value:
        return "未知"
    return value if value.endswith("元") else f"{value}元"


def _geocode_many(places: str, city: str = "") -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    for raw_place in re.split(r"[|,，;；\n]+", str(places or "")):
        place = raw_place.strip()
        if not place:
            continue
        info = _amap_geocode(place, city=city)
        if info and info.get("location"):
            results.append((place, info["location"], info.get("formatted_address") or place))
    return results


def _format_transit_segment(segment: dict) -> str:
    bus_info = segment.get("bus") or {}
    buslines = bus_info.get("buslines") or []
    if buslines:
        line = buslines[0]
        name = _poi_scalar(line.get("name"), "未知线路")
        departure = _poi_scalar(line.get("departure_stop", {}).get("name"), "未知上车站")
        arrival = _poi_scalar(line.get("arrival_stop", {}).get("name"), "未知下车站")
        stops = _poi_scalar(line.get("via_num"), "未知")
        return f"{name}：{departure} → {arrival}，约{stops}站"

    walking = segment.get("walking") or {}
    distance = walking.get("distance")
    if distance:
        return f"步行约{_format_km(distance)}"
    return "换乘步骤信息不完整"


def _transit_mode_label(transit: dict) -> str:
    names: list[str] = []
    for segment in transit.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        buslines = (segment.get("bus") or {}).get("buslines") or []
        for line in buslines:
            name = _poi_scalar(line.get("name"), "")
            if name:
                names.append(name)
    has_rail = any("地铁" in name or "轨道交通" in name for name in names)
    has_bus = any("路" in name and "地铁" not in name and "轨道交通" not in name for name in names)
    if has_rail and has_bus:
        return "地铁+公交换乘"
    if has_rail:
        return "地铁优先"
    if has_bus:
        return "公交备选"
    return "公共交通"


def _format_poi_lines(title: str, pois: list[dict], limit: int) -> str:
    lines = ["数据源：高德地图", title]
    for index, poi in enumerate(pois[: max(1, min(int(limit), 20))], start=1):
        name = poi.get("name", "未知地点")
        poi_type = poi.get("type", "未知类型")
        address = poi.get("address") or "地址未提供"
        location = poi.get("location") or "坐标未知"
        tel = poi.get("tel") or "电话未提供"
        distance = poi.get("distance")
        biz_ext = poi.get("biz_ext") or {}
        rating = _poi_scalar(biz_ext.get("rating"), "暂无评分")
        cost = _poi_scalar(biz_ext.get("cost"), "暂无人均")
        opentime = _poi_scalar(biz_ext.get("opentime"), "营业时间未提供")
        photos = poi.get("photos") or []
        photo_url = ""
        if photos and isinstance(photos[0], dict):
            photo_url = photos[0].get("url") or ""

        optional_parts = [
            f"距离 {_format_km(distance)}" if distance else "",
            f"评分 {rating}" if rating != "暂无评分" else "",
            f"人均 {cost}元" if cost != "暂无人均" else "",
            f"营业时间 {opentime}" if opentime != "营业时间未提供" else "",
            f"照片 {photo_url}" if photo_url else "",
        ]
        optional_text = "；".join(part for part in optional_parts if part)
        lines.append(
            f"{index}. {name}；{poi_type}；{address}；坐标 {location}；电话 {tel}"
            + (f"；{optional_text}" if optional_text else "")
        )
    return "\n".join(lines)


def _amap_marker_url(location: str, name: str) -> str:
    return f"https://uri.amap.com/marker?position={location}&name={requests.utils.quote(name)}"


def _first_non_empty(*values: object, default: str = "未知") -> str:
    for value in values:
        text = _poi_scalar(value, "").strip()
        if text:
            return text
    return default


def _normalize_airport_iata(value: str) -> str:
    text = str(value or "").strip().upper()
    if re.fullmatch(r"[A-Z]{3}", text):
        return text
    cleaned = str(value or "").strip()
    for suffix in ("市", "机场", "国际机场", "机场T1", "机场T2", "机场T3"):
        cleaned = cleaned.replace(suffix, "")
    return AIRPORT_IATA_BY_CITY.get(cleaned, text)


def _format_flight_time(value: object) -> str:
    text = _poi_scalar(value, "")
    if not text:
        return "未知"
    return text.replace("T", " ").split("+")[0]


def _format_aviationstack_flights(
    flights: list[dict],
    dep_iata: str,
    arr_iata: str,
    limit: int,
    note: str = "",
) -> str:
    lines = [
        "数据源：Aviationstack",
        "说明：该接口提供航班时刻/状态信息，不提供机票价格；票价需到航司或 OTA 平台另查。",
        f"查询机场：{dep_iata or '不限'} → {arr_iata or '不限'}",
    ]
    if note:
        lines.append(note)
    for index, flight in enumerate(flights[: max(1, min(int(limit), 20))], start=1):
        dep = flight.get("departure") or {}
        arr = flight.get("arrival") or {}
        airline_info = flight.get("airline") or {}
        flight_info = flight.get("flight") or {}
        flight_code = _first_non_empty(flight_info.get("iata"), flight_info.get("icao"), flight_info.get("number"))
        airline_name = _first_non_empty(airline_info.get("name"), airline_info.get("iata"), default="未知航空公司")
        dep_airport = _first_non_empty(dep.get("airport"), dep.get("iata"), default="未知出发机场")
        arr_airport = _first_non_empty(arr.get("airport"), arr.get("iata"), default="未知到达机场")
        dep_time = _format_flight_time(dep.get("scheduled") or dep.get("estimated") or dep.get("actual"))
        arr_time = _format_flight_time(arr.get("scheduled") or arr.get("estimated") or arr.get("actual"))
        status = _first_non_empty(flight.get("flight_status"), default="未知状态")
        terminal_gate = []
        if dep.get("terminal"):
            terminal_gate.append(f"出发航站楼 {dep.get('terminal')}")
        if dep.get("gate"):
            terminal_gate.append(f"登机口 {dep.get('gate')}")
        if arr.get("terminal"):
            terminal_gate.append(f"到达航站楼 {arr.get('terminal')}")
        lines.append(
            f"{index}. {airline_name} {flight_code}；"
            f"{dep_airport}({dep.get('iata', '未知')}) → {arr_airport}({arr.get('iata', '未知')})；"
            f"计划 {dep_time} → {arr_time}；状态 {status}"
            + (f"；{'，'.join(terminal_gate)}" if terminal_gate else "")
        )
    return "\n".join(lines)


def _log_tool_start(name: str, **kwargs: object) -> float:
    start = time.time()
    print(f"\n{'=' * 20} 开始调用工具: {name} {'=' * 20}")
    print(f"工具调用时间戳: {start:.2f}")
    for key, value in kwargs.items():
        print(f"- {key}: {value}")
    print("=" * 70)
    return start


def _log_tool_end(name: str, start: float, result: str) -> None:
    elapsed = time.time() - start
    print(f"\n工具 {name} 调用完成，耗时 {elapsed:.2f} 秒")
    print(result)


@tool
def get_weather_info(city: str, date: str = DEFAULT_DATE) -> str:
    """查询指定城市的实时天气信息，用于出行规划。

    Args:
        city: 城市名称，例如 "杭州"、"郑州"、"北京"。
        date: 行程日期，格式建议为 YYYY-MM-DD。该字段用于规划展示，天气数据为实时天气。
    """
    start = _log_tool_start("get_weather_info", city=city, date=date)

    try:
        qweather_key = _qweather_key()
        qweather_host = _qweather_host()
        if qweather_key and qweather_host:
            try:
                location = _qweather_lookup(city)
                if location:
                    location_id = location["id"]
                    city_name = location.get("name", city)
                    adm1 = location.get("adm1", "")
                    adm2 = location.get("adm2", "")
                    now_data = _request_json(
                        f"https://{qweather_host}/v7/weather/now",
                        {"location": location_id, "lang": "zh", "unit": "m"},
                        headers=_qweather_headers(),
                    )
                    now = now_data.get("now") or {}
                    daily_data = _request_json(
                        f"https://{qweather_host}/v7/weather/3d",
                        {"location": location_id, "lang": "zh", "unit": "m"},
                        headers=_qweather_headers(),
                    )
                    daily_items = daily_data.get("daily") or []
                    daily = next((item for item in daily_items if item.get("fxDate") == date), None)
                    if daily is None and daily_items:
                        daily = daily_items[0]

                    result = (
                        f"数据源：和风天气\n"
                        f"城市：{city_name}（{adm1}{adm2}）\n"
                        f"行程日期：{date}\n"
                        f"实时温度：{now.get('temp', '未知')}℃\n"
                        f"体感温度：{now.get('feelsLike', '未知')}℃\n"
                        f"天气状况：{now.get('text', '未知')}\n"
                        f"相对湿度：{now.get('humidity', '未知')}%\n"
                        f"风向风力：{now.get('windDir', '未知')} {now.get('windScale', '未知')}级\n"
                        f"风速：{now.get('windSpeed', '未知')} km/h\n"
                        f"能见度：{now.get('vis', '未知')} km\n"
                        f"气压：{now.get('pressure', '未知')} hPa"
                    )
                    if daily:
                        result += (
                            f"\n未来预报：{daily.get('fxDate', date)} "
                            f"{daily.get('textDay', '未知')}，"
                            f"{daily.get('tempMin', '未知')}℃-{daily.get('tempMax', '未知')}℃，"
                            f"降水概率 {daily.get('pop', '未知')}%"
                        )
                    _log_tool_end("get_weather_info", start, result)
                    return result
            except Exception as exc:
                print(f"和风天气查询失败，回退 Open-Meteo：{exc}")

        amap_info = _amap_geocode(city)
        if amap_info and _amap_key():
            try:
                adcode = amap_info.get("adcode")
                weather_data = _request_json(
                    f"{AMAP_BASE_URL}/weather/weatherInfo",
                    {"key": _amap_key(), "city": adcode, "extensions": "base", "output": "JSON"},
                )
                lives = weather_data.get("lives") or []
                if weather_data.get("status") == "1" and lives:
                    live = lives[0]
                    result = (
                        "数据源：高德地图天气\n"
                        f"城市：{live.get('province', '')}{live.get('city', city)}\n"
                        f"行程日期：{date}\n"
                        f"实时温度：{live.get('temperature', '未知')}℃\n"
                        f"天气状况：{live.get('weather', '未知')}\n"
                        f"相对湿度：{live.get('humidity', '未知')}%\n"
                        f"风向风力：{live.get('winddirection', '未知')}风 {live.get('windpower', '未知')}级\n"
                        f"发布时间：{live.get('reporttime', '未知')}"
                    )
                    _log_tool_end("get_weather_info", start, result)
                    return result
            except Exception as exc:
                print(f"高德天气查询失败，回退 Open-Meteo：{exc}")

        geo_resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
            timeout=10,
        )
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()

        if not geo_data.get("results"):
            return f"天气查询失败：未找到城市 {city}"

        city_info = geo_data["results"][0]
        lat = city_info["latitude"]
        lon = city_info["longitude"]
        city_name = city_info.get("name", city)

        weather_resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "weather_code",
                    "wind_speed_10m",
                    "pressure_msl",
                ],
                "timezone": "auto",
            },
            timeout=10,
        )
        weather_resp.raise_for_status()
        current = weather_resp.json()["current"]

        weather_desc = WEATHER_CODES.get(current["weather_code"], "未知")
        result = (
            f"城市：{city_name}\n"
            f"行程日期：{date}\n"
            f"实时温度：{current['temperature_2m']}℃\n"
            f"体感温度：{current['apparent_temperature']}℃\n"
            f"天气状况：{weather_desc}\n"
            f"相对湿度：{current['relative_humidity_2m']}%\n"
            f"风速：{current['wind_speed_10m']} km/h\n"
            f"气压：{current['pressure_msl']} hPa"
        )
        _log_tool_end("get_weather_info", start, result)
        return result
    except Exception as exc:
        result = f"天气查询异常：{exc}"
        _log_tool_end("get_weather_info", start, result)
        return result


@tool
def get_air_quality_info(city: str) -> str:
    """查询城市实时空气质量，用于判断是否适合户外步行、骑行、亲子或老人出行。

    Args:
        city: 城市名称，例如 "宁波"、"杭州"、"北京"。
    """
    start = _log_tool_start("get_air_quality_info", city=city)
    try:
        qweather_host = _qweather_host()
        location = _qweather_lookup(city)
        if not qweather_host or not location:
            result = "空气质量查询不可用：未配置和风天气 Key/Host，或未找到城市。"
            _log_tool_end("get_air_quality_info", start, result)
            return result

        air_data = _request_json(
            f"https://{qweather_host}/v7/air/now",
            {"location": location["id"], "lang": "zh"},
            headers=_qweather_headers(),
        )
        now = air_data.get("now") or {}
        if not now:
            result = f"空气质量查询失败：和风天气未返回 {city} 的空气质量数据。"
            _log_tool_end("get_air_quality_info", start, result)
            return result

        result = (
            "数据源：和风天气空气质量\n"
            f"城市：{location.get('name', city)}（{location.get('adm1', '')}{location.get('adm2', '')}）\n"
            f"AQI：{now.get('aqi', '未知')}\n"
            f"空气质量等级：{now.get('category', '未知')}\n"
            f"首要污染物：{now.get('primary', '无或未知')}\n"
            f"PM2.5：{now.get('pm2p5', '未知')} μg/m³\n"
            f"PM10：{now.get('pm10', '未知')} μg/m³\n"
            f"NO2：{now.get('no2', '未知')} μg/m³\n"
            f"SO2：{now.get('so2', '未知')} μg/m³\n"
            f"O3：{now.get('o3', '未知')} μg/m³\n"
            f"CO：{now.get('co', '未知')} mg/m³"
        )
        _log_tool_end("get_air_quality_info", start, result)
        return result
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else ""
        if status_code == 403:
            result = "空气质量查询暂不可用：当前和风天气账号可能未开通空气质量 API 权限。"
        else:
            result = f"空气质量查询暂不可用：HTTP {status_code or '未知'}。"
        _log_tool_end("get_air_quality_info", start, result)
        return result
    except Exception as exc:
        result = f"空气质量查询暂不可用：{exc}"
        _log_tool_end("get_air_quality_info", start, result)
        return result


@tool
def get_weather_alerts(city: str) -> str:
    """查询城市当前天气灾害预警，用于出行安全提醒。

    Args:
        city: 城市名称，例如 "宁波"、"杭州"、"北京"。
    """
    start = _log_tool_start("get_weather_alerts", city=city)
    try:
        qweather_host = _qweather_host()
        location = _qweather_lookup(city)
        if not qweather_host or not location:
            result = "天气预警查询不可用：未配置和风天气 Key/Host，或未找到城市。"
            _log_tool_end("get_weather_alerts", start, result)
            return result

        warning_data = _request_json(
            f"https://{qweather_host}/v7/warning/now",
            {"location": location["id"], "lang": "zh"},
            headers=_qweather_headers(),
        )
        warnings = warning_data.get("warning") or []
        if not warnings:
            result = (
                "数据源：和风天气灾害预警\n"
                f"城市：{location.get('name', city)}（{location.get('adm1', '')}{location.get('adm2', '')}）\n"
                "当前无正在生效的天气灾害预警。"
            )
            _log_tool_end("get_weather_alerts", start, result)
            return result

        lines = [
            "数据源：和风天气灾害预警",
            f"城市：{location.get('name', city)}（{location.get('adm1', '')}{location.get('adm2', '')}）",
        ]
        for index, warning in enumerate(warnings[:5], start=1):
            lines.append(
                f"{index}. {warning.get('title', '未知预警')}；"
                f"等级：{warning.get('severityColor', warning.get('severity', '未知'))}；"
                f"类型：{warning.get('typeName', '未知')}；"
                f"发布时间：{warning.get('pubTime', '未知')}；"
                f"说明：{warning.get('text', '无详细说明')}"
            )
        result = "\n".join(lines)
        _log_tool_end("get_weather_alerts", start, result)
        return result
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else ""
        if status_code == 403:
            result = "天气预警查询暂不可用：当前和风天气账号可能未开通灾害预警 API 权限。"
        else:
            result = f"天气预警查询暂不可用：HTTP {status_code or '未知'}。"
        _log_tool_end("get_weather_alerts", start, result)
        return result
    except Exception as exc:
        result = f"天气预警查询暂不可用：{exc}"
        _log_tool_end("get_weather_alerts", start, result)
        return result


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
def get_transport_advice(origin: str, destination: str) -> str:
    """获取出发地与目的地之间的驾车路线信息（距离、耗时、过路费），用于辅助交通决策。

    注意：此工具只提供驾车路线数据，不包含火车票或高铁票信息。
    如需查询火车票/高铁票的具体车次、时刻和余票，必须另外调用 search_train_tickets 工具。"""
    start = _log_tool_start("get_transport_advice", origin=origin, destination=destination)
    origin_info = _amap_location(origin)
    destination_info = _amap_location(destination)
    if origin_info and destination_info and _amap_key():
        origin_location, origin_address = origin_info
        destination_location, destination_address = destination_info
        try:
            data = _request_json(
                f"{AMAP_BASE_URL}/direction/driving",
                {
                    "key": _amap_key(),
                    "origin": origin_location,
                    "destination": destination_location,
                    "extensions": "base",
                    "strategy": 10,
                    "output": "JSON",
                },
            )
            route = data.get("route") or {}
            paths = route.get("paths") or []
            if data.get("status") == "1" and paths:
                path = paths[0]
                distance = _format_km(path.get("distance", ""))
                duration = _format_minutes(path.get("duration", ""))
                taxi_cost = route.get("taxi_cost")
                tolls = path.get("tolls")
                result = (
                    f"数据源：高德地图\n"
                    f"路线：{origin_address} → {destination_address}\n"
                    f"驾车距离：{distance}\n"
                    f"预计驾车耗时：{duration}\n"
                    f"高速/过路费估算：{tolls or '未知'}元\n"
                    f"出租车费用估算：{taxi_cost or '未知'}元\n"
                    "交通建议：\n"
                    "1. 若两地距离较远，优先比较高铁和飞机；高铁适合稳定出行，飞机适合长距离且时间紧张的行程。\n"
                    "2. 若驾车距离在300公里以内，自驾/包车可作为重点备选；超过300公里建议优先公共交通。\n"
                    "3. 到达目的地后，景区密集区域优先地铁、公交、步行或网约车组合。"
                )
                _log_tool_end("get_transport_advice", start, result)
                return result
        except Exception as exc:
            print(f"高德交通查询失败，回退通用建议：{exc}")

    result = (
        f"从{origin}到{destination}的交通建议：\n"
        "1. 跨城市优先比较高铁和飞机：高铁稳定、进出站便利；飞机适合距离较远且时间紧张的情况。\n"
        "2. 到达目的地后，市区内优先使用地铁、公交和步行，景区密集区域可选择骑行。\n"
        "3. 若遇到降雨、大风或携带较多行李，建议在景区间使用网约车补充。"
    )
    _log_tool_end("get_transport_advice", start, result)
    return result


@tool
def search_flight_options(
    departure: str = "",
    arrival: str = "",
    date: str = "",
    airline: str = "",
    flight_number: str = "",
    limit: int = 8,
) -> str:
    """使用 Aviationstack 查询航班时刻/状态信息，作为跨城远距离出行的飞机备选。

    注意：Aviationstack 提供的是航班动态、机场、航空公司和计划/实际时刻信息，不提供机票价格。
    Args:
        departure: 出发机场 IATA 三字码或常见城市名，例如 "NGB"、"CGO"、"宁波"、"郑州"。
        arrival: 到达机场 IATA 三字码或常见城市名，例如 "HGH"、"成都"、"北京"。
        date: 可选，航班日期 YYYY-MM-DD。免费/实时接口可能主要返回当前或近期数据，历史/未来日期是否可用取决于账号套餐。
        airline: 可选，航空公司 IATA 代码，例如 "MU"、"CA"。
        flight_number: 可选，航班号数字部分，例如 MU2397 的 "2397"。
        limit: 返回结果数量，建议 3-10。
    """
    start = _log_tool_start(
        "search_flight_options",
        departure=departure,
        arrival=arrival,
        date=date,
        airline=airline,
        flight_number=flight_number,
        limit=limit,
    )
    key = _aviationstack_key()
    if not key:
        result = "航班查询不可用：未配置 AVIATIONSTACK_API_KEY。"
        _log_tool_end("search_flight_options", start, result)
        return result

    params: dict[str, object] = {
        "access_key": key,
        "limit": max(1, min(int(limit), 20)),
    }
    dep_iata = _normalize_airport_iata(departure)
    arr_iata = _normalize_airport_iata(arrival)
    if dep_iata:
        params["dep_iata"] = dep_iata
    if arr_iata:
        params["arr_iata"] = arr_iata
    if date:
        params["flight_date"] = date
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
                        note=f"提示：当前 Aviationstack 账号不支持按指定日期 {date} 查询，已自动回退为近期/实时航班结果。",
                    )
                    _log_tool_end("search_flight_options", start, result)
                    return result
            except Exception as fallback_exc:
                print(f"Aviationstack 日期查询失败后回退也失败：{fallback_exc}")
        result = f"航班查询暂不可用：HTTP {status_code or '未知'}。"
        _log_tool_end("search_flight_options", start, result)
        return result
    except Exception as exc:
        result = f"航班查询异常：{exc}"
        _log_tool_end("search_flight_options", start, result)
        return result


@tool
def get_public_transit_plan(
    origin: str,
    destination: str,
    origin_city: str = "",
    destination_city: str = "",
    limit: int = 3,
) -> str:
    """使用高德地图查询公交/地铁换乘方案，适合市内或邻近城市景点、车站、酒店之间的公共交通规划。
    Args:
        origin: 出发地点，例如 "杭州东站"、"西湖"。
        destination: 到达地点，例如 "灵隐寺"、"武林广场"。
        origin_city: 出发城市，可选；地点名称模糊时建议填写。
        destination_city: 到达城市，可选；不填时默认使用出发城市或地理编码结果。
        limit: 返回方案数量，建议 1-5。
    """
    start = _log_tool_start(
        "get_public_transit_plan",
        origin=origin,
        destination=destination,
        origin_city=origin_city,
        destination_city=destination_city,
        limit=limit,
    )
    key = _amap_key()
    if not key:
        result = "公共交通查询不可用：未配置 AMAP_API_KEY。"
        _log_tool_end("get_public_transit_plan", start, result)
        return result

    try:
        origin_info = _amap_geocode(origin, city=origin_city)
        destination_info = _amap_geocode(destination, city=destination_city or origin_city)
        if not origin_info or not destination_info:
            result = f"公共交通查询失败：未能解析 {origin} 或 {destination} 的坐标。"
            _log_tool_end("get_public_transit_plan", start, result)
            return result

        origin_location = origin_info.get("location", "")
        destination_location = destination_info.get("location", "")
        resolved_origin_city = _city_name_from_geocode(origin_info, origin_city)
        resolved_destination_city = _city_name_from_geocode(destination_info, destination_city or resolved_origin_city)

        data = _request_json(
            f"{AMAP_BASE_URL}/direction/transit/integrated",
            {
                "key": key,
                "origin": origin_location,
                "destination": destination_location,
                "city": resolved_origin_city,
                "cityd": resolved_destination_city,
                "strategy": 0,
                "nightflag": 0,
                "extensions": "base",
                "output": "JSON",
            },
        )
        route = data.get("route") or {}
        transits = route.get("transits") or []
        if data.get("status") != "1" or not transits:
            result = (
                f"未查询到 {origin} 到 {destination} 的公共交通方案。"
                f"高德返回信息：{data.get('info', '无详细说明')}"
            )
            _log_tool_end("get_public_transit_plan", start, result)
            return result

        lines = [
            "数据源：高德地图公交/地铁路线规划",
            f"路线：{origin_info.get('formatted_address', origin)} → {destination_info.get('formatted_address', destination)}",
            f"查询城市：{resolved_origin_city} → {resolved_destination_city}",
        ]
        for index, transit in enumerate(transits[: max(1, min(int(limit), 5))], start=1):
            mode_label = _transit_mode_label(transit)
            duration = _format_minutes(transit.get("duration", ""))
            walking_distance = _format_km(transit.get("walking_distance", ""))
            cost = _format_transit_cost(transit.get("cost", ""))
            segments = [
                _format_transit_segment(segment)
                for segment in (transit.get("segments") or [])
                if isinstance(segment, dict)
            ]
            segment_text = "；".join(segment for segment in segments if segment) or "换乘步骤未提供"
            lines.append(
                f"{index}. {mode_label}；预计耗时 {duration}；步行 {walking_distance}；费用 {cost}；路线：{segment_text}"
            )
        result = "\n".join(lines)
        _log_tool_end("get_public_transit_plan", start, result)
        return result
    except Exception as exc:
        result = f"公共交通查询异常：{exc}"
        _log_tool_end("get_public_transit_plan", start, result)
        return result


@tool
def get_walking_route(origin: str, destination: str, city: str = "") -> str:
    """使用高德地图查询两点之间的步行路线，适合市内短距离景点、地铁站、酒店之间的步行可达性判断。

    Args:
        origin: 出发地点，例如 "宁波大学"、"天一阁"。
        destination: 到达地点，例如 "宁波大学地铁站"、"鼓楼"。
        city: 地点所在城市，可选；地点名称模糊时建议填写。
    """
    start = _log_tool_start("get_walking_route", origin=origin, destination=destination, city=city)
    key = _amap_key()
    if not key:
        result = "步行路线查询不可用：未配置 AMAP_API_KEY。"
        _log_tool_end("get_walking_route", start, result)
        return result

    try:
        points = _resolve_route_points(origin, destination, city=city)
        if not points:
            result = f"步行路线查询失败：未能解析 {origin} 或 {destination} 的坐标。"
            _log_tool_end("get_walking_route", start, result)
            return result
        origin_location, origin_address, destination_location, destination_address = points
        data = _request_json(
            f"{AMAP_BASE_URL}/direction/walking",
            {
                "key": key,
                "origin": origin_location,
                "destination": destination_location,
                "output": "JSON",
            },
        )
        paths = (data.get("route") or {}).get("paths") or []
        if data.get("status") != "1" or not paths:
            result = f"未查询到 {origin} 到 {destination} 的步行路线。高德返回信息：{data.get('info', '无详细说明')}"
            _log_tool_end("get_walking_route", start, result)
            return result

        path = paths[0]
        distance = _format_km(path.get("distance", ""))
        duration = _format_minutes(path.get("duration", ""))
        steps = _format_route_steps(path.get("steps") or [])
        result = (
            "数据源：高德地图步行路线规划\n"
            f"路线：{origin_address} -> {destination_address}\n"
            f"步行距离：{distance}\n"
            f"预计步行耗时：{duration}\n"
            f"主要步骤：{steps}\n"
            "建议：若步行距离超过 2 公里，建议同时比较骑行、公交/地铁或网约车。"
        )
        _log_tool_end("get_walking_route", start, result)
        return result
    except Exception as exc:
        result = f"步行路线查询异常：{exc}"
        _log_tool_end("get_walking_route", start, result)
        return result


@tool
def get_bicycling_route(origin: str, destination: str, city: str = "") -> str:
    """使用高德地图查询两点之间的骑行路线，适合市内 1-8 公里短途移动、共享单车或骑行体验判断。

    Args:
        origin: 出发地点，例如 "宁波大学"、"天一阁"。
        destination: 到达地点，例如 "宁波老外滩"、"鼓楼"。
        city: 地点所在城市，可选；地点名称模糊时建议填写。
    """
    start = _log_tool_start("get_bicycling_route", origin=origin, destination=destination, city=city)
    key = _amap_key()
    if not key:
        result = "骑行路线查询不可用：未配置 AMAP_API_KEY。"
        _log_tool_end("get_bicycling_route", start, result)
        return result

    try:
        points = _resolve_route_points(origin, destination, city=city)
        if not points:
            result = f"骑行路线查询失败：未能解析 {origin} 或 {destination} 的坐标。"
            _log_tool_end("get_bicycling_route", start, result)
            return result
        origin_location, origin_address, destination_location, destination_address = points
        data = _request_json(
            "https://restapi.amap.com/v4/direction/bicycling",
            {
                "key": key,
                "origin": origin_location,
                "destination": destination_location,
            },
        )
        paths = ((data.get("data") or {}).get("paths") or (data.get("route") or {}).get("paths") or [])
        ok = data.get("errcode") in (None, 0) or data.get("status") == "1"
        if not ok or not paths:
            message = data.get("errmsg") or data.get("info") or "无详细说明"
            result = f"未查询到 {origin} 到 {destination} 的骑行路线。高德返回信息：{message}"
            _log_tool_end("get_bicycling_route", start, result)
            return result

        path = paths[0]
        distance = _format_km(path.get("distance", ""))
        duration = _format_minutes(path.get("duration", ""))
        steps = _format_route_steps(path.get("steps") or [])
        result = (
            "数据源：高德地图骑行路线规划\n"
            f"路线：{origin_address} -> {destination_address}\n"
            f"骑行距离：{distance}\n"
            f"预计骑行耗时：{duration}\n"
            f"主要步骤：{steps}\n"
            "建议：骑行前结合天气、空气质量和道路条件；雨天、夜间或携带行李时优先公交/地铁或网约车。"
        )
        _log_tool_end("get_bicycling_route", start, result)
        return result
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else ""
        result = f"骑行路线查询暂不可用：HTTP {status_code or '未知'}。"
        _log_tool_end("get_bicycling_route", start, result)
        return result
    except Exception as exc:
        result = f"骑行路线查询异常：{exc}"
        _log_tool_end("get_bicycling_route", start, result)
        return result


@tool
def get_route_distance_matrix(origins: str, destination: str, city: str = "", travel_type: str = "driving") -> str:
    """使用高德地图距离测量 API 比较多个出发点到同一目的地的距离/耗时。

    适合回答"哪个景点离酒店近"、"从多个候选住宿点到车站多久"、"多个景点到机场的驾车距离"等问题。

    Args:
        origins: 多个出发地点，用竖线分隔，例如 "宁波大学|天一阁·月湖|宁波老外滩"。
        destination: 目的地，例如 "宁波站"。
        city: 地点所在城市，可选；地点名称模糊时建议填写。
        travel_type: driving/驾车、walking/步行、straight/直线，默认 driving。
    """
    start = _log_tool_start(
        "get_route_distance_matrix",
        origins=origins,
        destination=destination,
        city=city,
        travel_type=travel_type,
    )
    key = _amap_key()
    if not key:
        result = "距离矩阵查询不可用：未配置 AMAP_API_KEY。"
        _log_tool_end("get_route_distance_matrix", start, result)
        return result

    try:
        # Do not split on comma because coordinates use "lng,lat".
        origin_names = [item.strip() for item in re.split(r"[|｜;；\n]+", origins or "") if item.strip()]
        if not origin_names:
            result = "距离矩阵查询失败：请提供至少一个出发地点。"
            _log_tool_end("get_route_distance_matrix", start, result)
            return result
        origin_infos = []
        for name in origin_names[:10]:
            info = _amap_geocode(name, city=city)
            if info and info.get("location"):
                origin_infos.append((name, info))
        destination_info = _amap_geocode(destination, city=city)
        if not origin_infos or not destination_info or not destination_info.get("location"):
            result = f"距离矩阵查询失败：未能解析出发点或目的地 {destination} 的坐标。"
            _log_tool_end("get_route_distance_matrix", start, result)
            return result

        mode_label, type_code = _format_distance_matrix_type(travel_type)
        data = _request_json(
            f"{AMAP_BASE_URL}/distance",
            {
                "key": key,
                "origins": "|".join(info["location"] for _, info in origin_infos),
                "destination": destination_info["location"],
                "type": type_code,
                "output": "JSON",
            },
        )
        results = data.get("results") or []
        if data.get("status") != "1" or not results:
            result = f"未查询到距离矩阵。高德返回信息：{data.get('info', '无详细说明')}"
            _log_tool_end("get_route_distance_matrix", start, result)
            return result

        lines = [
            "数据源：高德地图距离测量",
            f"目的地：{destination_info.get('formatted_address', destination)}",
            f"测算方式：{mode_label}",
        ]
        for item in results:
            try:
                origin_index = int(item.get("origin_id", 1)) - 1
            except (TypeError, ValueError):
                origin_index = 0
            origin_name, origin_info = origin_infos[origin_index] if 0 <= origin_index < len(origin_infos) else origin_infos[0]
            distance = _format_km(item.get("distance", ""))
            duration = _format_minutes(item.get("duration", "")) if item.get("duration") else "未返回"
            lines.append(
                f"- {origin_name}（{origin_info.get('formatted_address', origin_name)}） -> {destination}：{distance}，预计耗时 {duration}"
            )
        result = "\n".join(lines)
        _log_tool_end("get_route_distance_matrix", start, result)
        return result
    except Exception as exc:
        result = f"距离矩阵查询异常：{exc}"
        _log_tool_end("get_route_distance_matrix", start, result)
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
    calculate_trip_budget,
    get_transport_advice,
    search_flight_options,
    get_public_transit_plan,
    get_walking_route,
    get_bicycling_route,
    get_route_distance_matrix,
    search_travel_pois,
    search_nearby_pois,
    get_place_location,
    get_map_marker_link,
]
