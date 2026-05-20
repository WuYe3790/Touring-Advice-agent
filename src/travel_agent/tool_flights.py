from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from travel_agent.tool_clients import _get_env_key
from travel_agent.tool_data import AIRPORT_IATA_BY_CITY
from travel_agent.tool_formatters import (
    _first_non_empty,
    _format_minutes,
    _format_money,
    _poi_scalar,
    _summarize_letsfg_error,
)


def _normalize_airport_iata(value: str) -> str:
    text = str(value or "").strip().upper()
    if re.fullmatch(r"[A-Z]{3}", text):
        return text
    cleaned = str(value or "").strip()
    for suffix in ("市", "机场", "国际机场", "机场T1", "机场T2", "机场T3"):
        cleaned = cleaned.replace(suffix, "")
    return AIRPORT_IATA_BY_CITY.get(cleaned, text)

def _letsfg_search_timeout() -> int:
    try:
        return max(5, min(int(_get_env_key("LETSFG_SEARCH_TIMEOUT") or 600), 600))
    except ValueError:
        return 600

def _letsfg_search_mode() -> str:
    return (_get_env_key("LETSFG_SEARCH_MODE") or "fast").strip() or "fast"

def _letsfg_max_browsers() -> int:
    try:
        return max(1, min(int(_get_env_key("LETSFG_MAX_BROWSERS") or 3), 6))
    except ValueError:
        return 3

def _letsfg_max_stopovers() -> int:
    try:
        return max(0, min(int(_get_env_key("LETSFG_MAX_STOPOVERS") or 0), 2))
    except ValueError:
        return 0

def _search_letsfg_local(
    dep_iata: str,
    arr_iata: str,
    date: str,
    limit: int,
    adults: int = 1,
    currency: str = "CNY",
) -> tuple[str, bool]:
    if not dep_iata or not arr_iata or not date:
        return "LetsFG 查询跳过：缺少出发机场、到达机场或日期。", False

    script = r"""
import asyncio
import json
import sys
from letsfg.local import search_local

origin, destination, date_from, limit, adults, currency, mode, max_browsers, max_stopovers = sys.argv[1:10]

async def main():
    result = await search_local(
        origin,
        destination,
        date_from,
        adults=int(adults),
        currency=currency,
        limit=int(limit),
        max_browsers=int(max_browsers),
        max_stopovers=int(max_stopovers),
        mode=mode,
    )
    print(json.dumps(result, ensure_ascii=False, default=str))

asyncio.run(main())
"""
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                dep_iata,
                arr_iata,
                date,
                str(max(1, min(int(limit), 10))),
                str(max(1, int(adults))),
                currency,
                _letsfg_search_mode(),
                str(_letsfg_max_browsers()),
                str(_letsfg_max_stopovers()),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_letsfg_search_timeout(),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except FileNotFoundError:
        return "LetsFG 未返回实时票价：当前 Python 环境未安装 letsfg，已回退到 Aviationstack。", False
    except subprocess.TimeoutExpired:
        return f"LetsFG 未在 {_letsfg_search_timeout()} 秒内返回实时票价，已回退到 Aviationstack。", False

    try:
        data = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        if completed.returncode != 0:
            error = _summarize_letsfg_error(f"{completed.stderr}\n{completed.stdout}")
            return f"LetsFG 未返回实时票价：{error} 已回退到 Aviationstack。", False
        return "LetsFG 未返回实时票价：未能解析本地搜索结果，已回退到 Aviationstack。", False

    offers = data.get("offers") or []
    if not offers:
        return "LetsFG 未查询到可用机票报价，已回退到 Aviationstack。", False
    return _format_letsfg_offers(data, dep_iata, arr_iata, limit), True

def _segment_time(value: object) -> str:
    text = _poi_scalar(value, "")
    if not text:
        return "未知"
    return text.replace("T", " ").split("+")[0].replace("Z", "")

def _format_letsfg_offers(data: dict, dep_iata: str, arr_iata: str, limit: int) -> str:
    offers = data.get("offers") or []
    currency = _first_non_empty(data.get("currency"), default="CNY")
    lines = [
        "数据源：LetsFG 本地实时机票搜索",
        f"查询航线：{dep_iata} → {arr_iata}",
        f"报价数量：{data.get('total_results', len(offers))}",
        "说明：价格来自 LetsFG 本地连接器实时搜索，库存、税费、行李和最终支付价仍以航司/购票页面确认结果为准。",
    ]
    pricing_note = _poi_scalar(data.get("pricing_note"), "")
    if pricing_note:
        lines.append(f"价格说明：{pricing_note}")

    sorted_offers = sorted(
        offers,
        key=lambda item: float(item.get("price") or 10**12),
    )[: max(1, min(int(limit), 10))]
    for index, offer in enumerate(sorted_offers, start=1):
        outbound = offer.get("outbound") or {}
        segments = outbound.get("segments") or []
        first = segments[0] if segments else {}
        last = segments[-1] if segments else {}
        airlines = offer.get("airlines") or []
        airline = _first_non_empty(offer.get("owner_airline"), ", ".join(airlines), first.get("airline_name"), default="未知航司")
        flight_no = " + ".join(
            _first_non_empty(seg.get("flight_no"), seg.get("airline"), default="").strip()
            for seg in segments
            if _first_non_empty(seg.get("flight_no"), seg.get("airline"), default="").strip()
        )
        route = " → ".join([segments[0].get("origin", dep_iata), *[seg.get("destination", "") for seg in segments]]) if segments else f"{dep_iata} → {arr_iata}"
        price_text = _first_non_empty(offer.get("price_formatted"), default="")
        if not price_text:
            price_text = _format_money(offer.get("price"), _first_non_empty(offer.get("currency"), currency, default="CNY"))
        departure_time = _segment_time(first.get("departure"))
        arrival_time = _segment_time(last.get("arrival"))
        duration = _format_minutes(outbound.get("total_duration_seconds") or 0)
        stopovers = outbound.get("stopovers")
        seats = offer.get("availability_seats")
        booking_url = _poi_scalar(offer.get("booking_url"), "")
        extras = []
        if flight_no:
            extras.append(f"航班 {flight_no}")
        if stopovers is not None:
            extras.append(f"中转 {stopovers} 次")
        if seats:
            extras.append(f"余位 {seats}")
        if booking_url:
            extras.append(f"预订链接 {booking_url}")
        lines.append(
            f"{index}. {airline}｜{route}｜{departure_time} → {arrival_time}｜"
            f"耗时 {duration}｜票价 {price_text}"
            + (f"｜{'；'.join(extras)}" if extras else "")
        )
    return "\n".join(lines)
