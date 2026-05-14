from __future__ import annotations

import time
import os
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


def _get_env_key(name: str) -> str:
    load_dotenv()
    return os.getenv(name, "").strip()


def _request_json(url: str, params: dict[str, object], timeout: int = 10, headers: dict[str, str] | None = None) -> dict:
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _amap_key() -> str:
    return _get_env_key("AMAP_API_KEY")


def _qweather_key() -> str:
    return _get_env_key("QWEATHER_API_KEY")


def _qweather_host() -> str:
    return _get_env_key("QWEATHER_API_HOST").removeprefix("https://").removeprefix("http://").strip("/")


def _amap_geocode(address: str, city: str = "") -> dict | None:
    key = _amap_key()
    if not key:
        return None
    data = _request_json(
        f"{AMAP_BASE_URL}/geocode/geo",
        {"key": key, "address": address, "city": city or None, "output": "JSON"},
    )
    if data.get("status") != "1" or not data.get("geocodes"):
        return None
    return data["geocodes"][0]


def _amap_location(address: str, city: str = "") -> tuple[str, str] | None:
    info = _amap_geocode(address, city=city)
    if not info or not info.get("location"):
        return None
    return info["location"], info.get("formatted_address") or address


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
                qweather_headers = {"X-QW-Api-Key": qweather_key}
                geo_data = _request_json(
                    f"https://{qweather_host}/geo/v2/city/lookup",
                    {"location": city, "lang": "zh"},
                    headers=qweather_headers,
                )
                locations = geo_data.get("location") or []
                if locations:
                    location = locations[0]
                    location_id = location["id"]
                    city_name = location.get("name", city)
                    adm1 = location.get("adm1", "")
                    adm2 = location.get("adm2", "")
                    now_data = _request_json(
                        f"https://{qweather_host}/v7/weather/now",
                        {"location": location_id, "lang": "zh", "unit": "m"},
                        headers=qweather_headers,
                    )
                    now = now_data.get("now") or {}
                    daily_data = _request_json(
                        f"https://{qweather_host}/v7/weather/3d",
                        {"location": location_id, "lang": "zh", "unit": "m"},
                        headers=qweather_headers,
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
    """根据出发地和目的地给出交通方式建议。"""
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
                "extensions": "base",
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
            lines.append(f"{index}. {name}｜{poi_type}｜{address}｜坐标 {location}｜{tel}")
        result = "\n".join(lines)
        _log_tool_end("search_travel_pois", start, result)
        return result
    except Exception as exc:
        result = f"POI 查询异常：{exc}"
        _log_tool_end("search_travel_pois", start, result)
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


TRAVEL_TOOLS = [
    get_weather_info,
    calculate_trip_budget,
    get_transport_advice,
    search_travel_pois,
    get_place_location,
]
