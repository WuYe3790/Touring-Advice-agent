from __future__ import annotations

import json
import re
import time

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from travel_agent.config import LLMConfig
from travel_agent.tools import DEFAULT_DATE, TRAVEL_TOOLS
from travel_agent.train_tools import get_train_tools


BASE_SYSTEM_PROMPT_TEMPLATE = """
你是一个资深旅游出行规划智能体。你必须体现"理解需求 -> 拆解任务 -> 调用工具 -> 汇总结果 -> 输出方案"的智能体工作流程。

行为规则：
1. 先理解用户的出发地、目的地、行程日期、天数、人数、预算和偏好。
2. 先判断用户意图是"单点查询"还是"完整旅行规划"。如果用户只要求查航班、火车、天气、公交、步行路线、地点、周边 POI、距离对比、路况或某类 POI，只回答该主题，不要扩展成完整出行方案，不要主动补预算、住宿、每日路线。
3. 只有当用户明确要求"规划/安排/行程/旅游方案/玩几天/一日游/多日游"等完整规划时，才生成完整旅行规划。
4. 天气会影响出行体验。完整旅行规划中只要识别出目的地，就应调用 get_weather_info；单点查询中只有用户询问天气、适合出行或该主题确实依赖天气时才调用天气工具。
5. 当用户提供了明确预算计算参数时，调用 calculate_trip_budget。不要编造酒店、餐饮、门票费用；缺少参数时，在完整规划中说明需要用户补充；单点查询中不要主动展开预算。
6. 当用户要求跨城交通方案或完整规划且识别出出发地和目的地时，调用 get_transport_advice 获取驾车路线参考；若城市间距离适合火车/高铁出行（跨城、超过约50公里），必须同时调用 search_train_tickets 查询真实火车票余票和时刻。不得仅凭 get_transport_advice 的通用文字建议编造火车信息。
7. 工具调用后，综合工具结果生成清晰、可执行、面向真实用户的中文回答；回答范围必须贴合用户问题，宁可窄而准，不要每次都输出全套旅行计划。
8. 完整规划输出建议包含：需求理解、思考摘要、工具调用依据、天气参考、交通建议、每日路线、预算分析或预算缺失说明、注意事项。单点查询只保留与问题直接相关的小节。
单点查询例子：
- "查一下明天宁波到广州的航班"：只查航班，只填 transport_options 和必要 tips。
- "西安钟楼附近有什么好吃的"：只查周边餐饮，只填 poi_recommendations 和必要 tips。
- "杭州东站到西湖怎么坐地铁"：只查公交/地铁，只填 transport_options。
- "明天成都天气怎么样"：只查天气，只填 weather/weather_alerts。
只要用户没有明确说"帮我规划行程/安排几日游/制定旅行方案"，不要生成完整每日行程。
9. 如果系统消息提供了“当前用户位置上下文”，且用户没有明确说明出发地，可将该位置作为默认出发地；如果用户明确给出出发地，必须以用户输入为准。
10. 今天的默认规划日期参考为 __DEFAULT_DATE__。如果用户说"明天"，可使用这个日期。
11. 输出风格要求：
- 使用规范 Markdown，但不要滥用装饰符号。
- 标题最多使用二级标题和三级标题，不要连续使用长横线分割。
- 表格只在确实适合对比时使用，列数控制在 4 列以内，避免过宽。
- 尽量少用 emoji；除非特别有帮助，每次回答最多使用 0-2 个 emoji。
- 不要在末尾输出泛泛的"还需要我继续吗"式推销问题。
12. 结构化输出要求：每一次最终回答末尾都必须包含一个 json 代码块，即使用户要求"简短回答"也不能省略。Markdown 正文可以简短，但末尾 JSON 是前端卡片渲染必需的数据协议。格式如下。注意：下面只是字段结构示意，不代表真实目的地；所有字段必须以用户当前需求和工具结果为准，不能照抄示例地点。单点查询时，只填充相关字段，其余字段使用 []、{} 或简短说明，不要为了填满 JSON 而编造行程。
```json
{
  "summary": "行程整体概述，一句话概括",
  "weather": [{"city": "目的地城市", "date": "日期", "temperature": "温度", "condition": "天气", "humidity": "湿度", "wind": "风速"}],
  "weather_alerts": [{"city": "城市", "title": "预警标题", "type": "预警类型", "severity": "等级或颜色", "pub_time": "发布时间", "text": "预警说明", "status": "active/no_active/unavailable", "data_source": "数据源"}],
  "transport_options": [{
    "mode": "交通方式或车次/航班号",
    "category": "flight/train/interline_train/transit/walking/bicycling/driving/traffic",
    "from": "出发地",
    "to": "目的地",
    "departure_time": "出发时间",
    "arrival_time": "到达时间",
    "duration": "耗时",
    "cost_estimate": "费用估计",
    "status": "余票/航班/可用状态",
    "data_source": "数据源",
    "notes": "补充说明",
    "legs": [{"mode": "第一段车次或交通方式", "from": "起点", "to": "终点", "departure_time": "出发", "arrival_time": "到达", "duration": "耗时", "cost_estimate": "票价", "status": "余票或状态", "notes": "说明"}]
  }],
  "daily_itinerary": [{"day": 1, "title": "当日主题", "activities": ["活动1", "活动2"], "meals": ["餐饮建议"], "accommodation": "住宿建议"}],
  "hotel_options": [{"name": "酒店名", "area": "所在区域", "price_total": "总价", "currency": "币种", "rating": "评分", "review_count": "评论数", "stars": "星级", "checkin": "入住时间", "checkout": "离店时间", "location": "经纬度", "photo_url": "图片链接", "data_source": "数据源", "notes": "限制说明"}],
  "budget": {"total": 0, "breakdown": {"项目": 0}, "currency": "CNY", "notes": "预算说明"},
  "tips": ["提示1", "提示2"],
  "poi_recommendations": [{"category": "分类标签", "items": [{"name": "地点名", "type": "类型", "address": "地址", "rating": "评分", "cost": "人均费用", "tel": "电话", "location": "经纬度", "map_url": "地图链接"}]}]
}
```
要求：内容必须与你的 Markdown 回答保持一致；无数据时使用空数组 []；json 代码块必须放在回答最末尾；不要在 json 之后添加任何文本；不要因为用户要求简短、快速或只回答一句话而省略 json 代码块。weather_alerts 用于天气灾害预警卡片；如果工具返回当前无预警，可写入一条 status 为 "no_active" 的记录；如果接口权限不可用，除非用户专门询问预警，否则可保持 []。hotel_options 用于真实酒店价格卡片；非酒店查询时必须为 []。transport_options 可以使用 category/data_source/status/departure_time/arrival_time/legs 等可选字段；中转火车方案必须把两段或多段车次写入 legs，方便前端渲染中转卡片。
"""

BASE_SYSTEM_PROMPT = BASE_SYSTEM_PROMPT_TEMPLATE.replace("__DEFAULT_DATE__", DEFAULT_DATE)

THINKING_MODE_PROMPT = """
当前已开启深度思考模式：
1. 在回答前进行更充分的需求分析、约束检查和工具选择。
2. 工具调用前先判断为什么需要该工具，避免遗漏关键工具。
3. 最终回答中加入"思考摘要"，说明你如何拆解任务、为什么调用这些工具、如何综合工具结果。
4. 不输出冗长的内部推理链，只输出用户可读的思考摘要和结论。
"""

REAL_DATA_TOOL_PROMPT = """
当前项目已接入真实数据工具：
1. get_weather_info 会优先使用和风天气查询实时天气和3日预报，失败时回退 Open-Meteo。
2. get_air_quality_info 可用和风天气查询实时空气质量，适合判断户外活动、老人儿童出行和骑行步行舒适度。
3. get_weather_alerts 可用和风天气查询当前天气灾害预警，适合补充安全提醒。
4. get_transport_advice 会优先使用高德地图解析路线距离、驾车耗时和费用估算，失败时回退通用交通建议。
5. get_public_transit_plan 可用高德地图查询公交/地铁换乘方案，适合市内景点、车站、酒店之间移动。
6. get_walking_route 可用高德地图查询步行路线，适合景点、酒店、地铁站之间的短距离可达性判断。
7. get_bicycling_route 可用高德地图查询骑行路线，适合 1-8 公里市内短途移动或共享单车方案判断。
8. get_route_distance_matrix 可用高德地图比较多个出发点到同一目的地的距离/耗时，适合住宿选址、景点排序、去车站/机场耗时比较。
9. get_traffic_status 可用高德地图查询指定地点周边实时交通态势，适合自驾、打车、机场/车站接驳和高峰期拥堵风险判断。
10. search_travel_pois 可用高德地图搜索目的地景点、博物馆、餐饮、商圈、酒店等 POI。
11. search_nearby_pois 可用高德地图围绕某个景点、车站或酒店查询周边餐饮、住宿、咖啡、地铁站等 POI。
12. get_place_location 可用高德地图核验地点地址和经纬度。
13. get_map_marker_link 可生成不暴露 API Key 的高德地图地点标记链接，适合放入 POI 或注意事项。
14. search_hotel_prices 可用 Booking.com RapidAPI 查询真实酒店价格，适合住宿推荐、酒店价格对比和预算估算；价格为接口返回的实时参考价，最终库存/税费/支付价以 Booking.com 为准。
15. search_train_tickets 可用 12306 查询真实火车票余票（高铁/动车/普速），支持按车型筛选和数量限制。
16. search_interline_train_tickets 可用 12306 查询中转余票方案，适合直达车次少、不合适或用户明确接受中转时调用。
17. get_train_route 可用 12306 查询特定车次的经停站和时刻表。
18. search_flight_options 会优先尝试 LetsFG 本地实时机票搜索，返回真实机票报价；如果 LetsFG 超时或失败，会自动回退到 Aviationstack 查询航班时刻/状态。Aviationstack 不提供机票价格。

使用要求：
- 当用户只是要求查某一种信息时，严格选择对应工具并窄回答：查航班只调用 search_flight_options；查高铁/火车只调用 search_train_tickets 或 search_interline_train_tickets；查天气只调用天气工具；查市内换乘只调用 get_public_transit_plan/步行/骑行等路线工具；查地点或周边只调用地点/POI 工具。不要因为识别出了城市就自动查询天气、景点、预算或完整日程。
- 单点查询的正文不要输出完整规划模板，不要包含“每日行程”“住宿建议”“预算分析”“景点推荐”等无关小节；只给结果、数据来源和必要限制说明。JSON 中也只填相关字段，例如航班查询只填 transport_options 和 tips；周边餐饮只填 poi_recommendations 和 tips；天气查询只填 weather/weather_alerts 和 tips。
- 单点查询时，summary 用一句话概括查询结果；daily_itinerary 必须为 []；hotel_options 只有酒店查询才填写，否则为 []；budget 使用 {"total": 0, "breakdown": {}, "currency": "CNY", "notes": ""}；无关字段必须为空数组，不要为了卡片好看而填充。
- 当用户请求具体目的地完整旅行规划时，除了天气和交通，优先调用 search_travel_pois 至少 3 次：分别搜索"景点"、"餐饮"或"本地菜"、"商圈"或"购物"。如果行程涉及住宿，应优先调用 search_hotel_prices 查询真实酒店价格；也可以补充 search_travel_pois 搜索"酒店"作为 POI/位置参考，但不要用高德酒店 POI 冒充真实房价。
- 当用户询问"酒店/住宿/住哪里/酒店价格/附近酒店/多少钱一晚"时，调用 search_hotel_prices；如果用户给出城市、日期和人数，按用户参数查询；如果缺少入住/离店日期，在完整规划中可用行程日期推断，单点查询中应要求补充日期或使用默认明天/后天并明确说明。最终回答必须说明 Booking.com/RapidAPI 价格只是实时参考，最终以平台确认页为准。酒店结果必须写入 hotel_options。
- 当用户行程包含较多户外活动、老人儿童出行、骑行步行、海边/山地/恶劣天气风险，或用户询问是否适合出行/天气预警时，可调用 get_air_quality_info 和 get_weather_alerts，并把可用的空气质量写入 tips，把天气预警写入 weather_alerts；如果工具返回"暂不可用"，不要把它当作规划失败，只需忽略或简短说明。用户单独查询天气预警时，只回答预警情况，不要扩展行程。
- 当行程包含车站到酒店、酒店到景点、景点到景点等城市内移动时，优先调用 get_public_transit_plan 获取真实公交/地铁换乘参考，并按距离和用户偏好补充 get_walking_route 或 get_bicycling_route：1.5 公里内优先比较步行，1-8 公里可比较骑行，携带行李或天气不好时优先公共交通/网约车。若工具结果同时包含"地铁优先"和"公交备选"，最终回答中必须至少保留一个公交备选方案，不能只写地铁。
- 当用户询问多个地点到同一目的地的远近、住宿区域选择、景点顺序或去车站/机场耗时时，调用 get_route_distance_matrix 做距离/耗时对比，不要凭感觉排序。
- 当用户选择自驾/打车、涉及机场车站接驳、上下班高峰、节假日拥堵，或询问“堵不堵/路况怎么样”时，可调用 get_traffic_status，把实时路况和拥堵风险写入 transport_options 或 tips。
- 当需要推荐"某景点附近吃什么""车站附近住哪里""酒店附近有什么"时，优先调用 search_nearby_pois，而不是只做全城 POI 搜索；周边搜索结果同样应写入 poi_recommendations。
- 当地点名称可能模糊或需要核验时，调用 get_place_location。
- 当最终方案里出现关键集合点、住宿区域或核心景点时，可调用 get_map_marker_link 获取地图链接；如果写入 JSON，可放在 poi_recommendations.items 的 map_url 字段或 tips 中。
- 最终回答的 JSON 代码块中必须包含 poi_recommendations 字段，将 search_travel_pois 返回的真实 POI 结果按类别分组填入。每个 item 必须包含 name（地点名）、type（POI 类型）和 address（地址）；如果工具返回了评分、人均、电话、经纬度或照片，也尽量填入 rating、cost、tel、location、photo_url。示例：
  {"category": "景点推荐", "items": [{"name": "西湖", "type": "风景名胜", "address": "杭州市西湖区龙井路1号", "rating": "4.8", "location": "120.1,30.2"}]}
- 关键规则：get_transport_advice 只返回驾车路线数据，不含火车信息。当行程涉及跨城时，必须在调用 get_transport_advice 之后额外调用 search_train_tickets 查询真实火车票。即使 get_transport_advice 结果中出现了"高铁"文字，那只是通用建议而非真实车次数据，不能替代 search_train_tickets。
- 用户提到"高铁"时传 train_filter_flags="G"，提到"动车"时传"D"。将 search_train_tickets 返回的车次号、出发/到达时刻、座型余票、票价如实地写入 transport_options（每条一个方案：mode 为"高铁 G车次号"，duration 为历时，cost_estimate 为座型+票价）和 daily_itinerary 的交通步骤中。
- 若 search_train_tickets 没有查到合适直达车，或用户提到"中转/换乘/怎么转车"，应调用 search_interline_train_tickets；不得自行编造中转车次。中转方案写入 transport_options 时 category 使用 "interline_train"，总方案写在外层，每一段车次写入 legs，并尽量包含换乘站、换乘等待时间、总耗时、各段票价/余票。
- 当用户明确提到"飞机/航班/机场/机票/机票价格"时，应调用 search_flight_options。跨城距离较远（例如驾车超过约500公里、火车耗时较长、或目的地适合航空出行）时，也应把 search_flight_options 作为备选工具调用。航班工具参数优先传机场 IATA 三字码；若不确定，可传常见城市名，工具内置部分中国城市机场映射；若用户给出人数，把成人数传入 adults。若工具返回 LetsFG 结果，最终回答应展示票价、航司、出发/到达时间和数据限制；若工具返回 Aviationstack 回退结果，必须说明这是航班时刻/状态参考，不含真实票价。
- 最终回答应说明关键数据来源，例如"天气和空气质量来自和风天气""地点和路线来自高德地图""酒店价格来自 Booking.com/RapidAPI""火车票来自12306""航班来自 Aviationstack"。
"""


def build_agent(config: LLMConfig, thinking_mode: bool = False):
    if not config.api_key:
        raise RuntimeError(
            "未检测到 LLM_API_KEY。请复制 .env.example 为 .env，并填写可用的大模型 API Key。"
        )

    selected_model = config.thinking_model if thinking_mode else config.model
    identity_prompt = f"""
当前运行配置：
- 模型名称：{selected_model}
- API 地址：{config.base_url}
- 运行模式：{'深度思考模式' if thinking_mode else '普通模式'}

如果用户询问你的身份、模型、版本或供应商，请根据以上实际运行配置回答。
不要声称自己是未在当前配置中出现的模型或供应商。
"""
    system_prompt = (
        BASE_SYSTEM_PROMPT
        + "\n"
        + REAL_DATA_TOOL_PROMPT
        + "\n"
        + identity_prompt
        + ("\n" + THINKING_MODE_PROMPT if thinking_mode else "")
    )

    llm_kwargs = {
        # DeepSeek V4 API-level thinking returns reasoning_content. When a tool call
        # happens, the API requires that field to be round-tripped in later calls.
        # LangChain's OpenAI-compatible tool agent does not preserve it yet, so we
        # disable API-level thinking for tool-calling stability and use the Pro model
        # plus the prompt-level thinking workflow in thinking mode.
        "extra_body": {"thinking": {"type": "disabled"}},
    }

    llm = ChatOpenAI(
        model=selected_model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        timeout=config.timeout,
        **llm_kwargs,
    )
    all_tools = TRAVEL_TOOLS + get_train_tools()
    print(f"\nLLM模式：{'深度思考模式' if thinking_mode else '普通模式'} | 模型：{selected_model} | 工具数：{len(all_tools)}")
    return create_agent(model=llm, tools=all_tools, system_prompt=system_prompt)


def message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return str(content)


def public_trace_item(item: dict) -> dict:
    """Return a copy of a trace item without internal LangChain bookkeeping ids."""
    return {key: value for key, value in item.items() if key != "tool_call_id"}


def public_trace(trace: list[dict]) -> list[dict]:
    return [public_trace_item(item) for item in trace]


def elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def trace_status_from_result(result: str) -> str:
    if not result:
        return "success"
    lowered = result.lower()
    if re.search(r"\b(error|traceback|exception)\b", lowered):
        return "error"
    error_markers = ("失败", "异常", "报错", "错误")
    return "error" if any(marker in lowered for marker in error_markers) else "success"


def finish_trace_item(item: dict, run_started_at: float, result: str | None = None) -> None:
    ended_ms = elapsed_ms(run_started_at)
    item["ended_ms"] = ended_ms
    item["duration_ms"] = max(0, ended_ms - int(item.get("started_ms") or ended_ms))
    if result is not None:
        item["result"] = result
        item["status"] = trace_status_from_result(result)
    elif item.get("status") == "running":
        item["status"] = "success"


def collect_agent_trace(messages: list[BaseMessage]) -> list[dict]:
    trace: list[dict] = []
    pending_tool_calls: dict[str, dict] = {}

    for index, message in enumerate(messages, start=1):
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            for tool_call in message.tool_calls:
                item = {
                    "type": "tool_call",
                    "step": index,
                    "tool": tool_call["name"],
                    "args": tool_call.get("args", {}),
                    "result": "",
                    "status": "success",
                    "started_ms": None,
                    "ended_ms": None,
                    "duration_ms": None,
                }
                trace.append(item)
                if tool_call.get("id"):
                    pending_tool_calls[tool_call["id"]] = item

        elif isinstance(message, ToolMessage):
            result = message_text(message)
            matched = False
            if getattr(message, "tool_call_id", None) in pending_tool_calls:
                pending_tool_calls[message.tool_call_id]["result"] = result
                pending_tool_calls[message.tool_call_id]["status"] = trace_status_from_result(result)
                matched = True
            if not matched:
                trace.append(
                    {
                        "type": "tool_result",
                        "step": index,
                        "tool": message.name,
                        "args": {},
                        "result": result,
                        "status": trace_status_from_result(result),
                        "started_ms": None,
                        "ended_ms": None,
                        "duration_ms": None,
                    }
                )

        if isinstance(message, AIMessage):
            usage = getattr(message, "usage_metadata", None)
            response_metadata = getattr(message, "response_metadata", {}) or {}
            model_name = response_metadata.get("model_name") or response_metadata.get("model")
            if usage or model_name:
                trace.append(
                    {
                        "type": "llm_response",
                        "step": index,
                        "model": model_name or "unknown",
                        "usage": usage or {},
                        "status": "success",
                        "started_ms": None,
                        "ended_ms": None,
                        "duration_ms": None,
                    }
                )

    return trace


def print_agent_trace(messages: list[BaseMessage]) -> None:
    print("\n智能体思考与工具调用过程：")
    print("-" * 70)

    for index, message in enumerate(messages, start=1):
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            for tool_call in message.tool_calls:
                print(f"[{index}] 决策：调用工具 {tool_call['name']}")
                print(f"    参数：{tool_call['args']}")
        elif isinstance(message, ToolMessage):
            print(f"[{index}] 工具返回：{message.name}")
            print(message_text(message))

        if isinstance(message, AIMessage):
            usage = getattr(message, "usage_metadata", None)
            response_metadata = getattr(message, "response_metadata", {}) or {}
            model_name = response_metadata.get("model_name") or response_metadata.get("model")
            if usage or model_name:
                print(f"[{index}] LLM响应元数据：model={model_name or 'unknown'}, usage={usage or 'unknown'}")


def extract_final_answer(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message_text(message).strip():
            return message_text(message).strip()
    return "智能体未生成最终回复。"


def _find_json_fence_pairs(text: str) -> list[tuple[int, int, str]]:
    """Return (full_start, full_end, content) for every json-like code fence."""
    results: list[tuple[int, int, str]] = []
    i = 0
    while True:
        fence_start = text.find("```", i)
        if fence_start == -1:
            break
        # Determine tag after opening ```
        tag_end = text.find("\n", fence_start)
        if tag_end == -1:
            break
        tag = text[fence_start + 3:tag_end].strip().lower()
        if tag not in ("json", ""):
            i = tag_end
            continue
        # Find closing ```
        content_start = tag_end + 1
        fence_end = text.find("\n```", content_start)
        if fence_end == -1:
            fence_end = text.find("```", content_start)
        if fence_end == -1:
            break
        content = text[content_start:fence_end].strip()
        full_end = fence_end + (4 if text.startswith("\n```", fence_end) else 3)
        while full_end < len(text) and text[full_end] in ("\n", "\r"):
            full_end += 1
        full_start = fence_start
        while full_start > 0 and text[full_start - 1] in ("\n", "\r"):
            full_start -= 1
        results.append((full_start, full_end, content))
        i = full_end
    return results


def extract_structured_json(text: str) -> dict | None:
    """Extract structured travel plan JSON from the last json code fence."""
    if not text:
        return None
    fences = _find_json_fence_pairs(text)
    if not fences:
        return None
    known_keys = (
        "summary",
        "weather",
        "weather_alerts",
        "transport_options",
        "daily_itinerary",
        "hotel_options",
        "budget",
        "tips",
        "poi_recommendations",
    )
    for _start, _end, content in reversed(fences):
        try:
            data = json.loads(content)
            if isinstance(data, dict) and any(k in data for k in known_keys):
                return data
        except json.JSONDecodeError:
            continue
    return None


def parse_hotel_options_from_trace(trace: list[dict]) -> list[dict]:
    """Extract hotel cards from search_hotel_prices tool output as a fallback."""
    hotels: list[dict] = []
    for item in trace:
        if item.get("tool") != "search_hotel_prices":
            continue
        result = str(item.get("result") or "")
        for line in result.splitlines():
            if not re.match(r"^\d+\.\s+", line):
                continue
            text = re.sub(r"^\d+\.\s+", "", line).strip()
            parts = [part.strip() for part in text.split("｜") if part.strip()]
            if len(parts) < 2:
                continue
            hotel = {
                "name": parts[0],
                "area": parts[1] if len(parts) > 1 else "",
                "price_total": "",
                "currency": "",
                "rating": "",
                "review_count": "",
                "stars": "",
                "checkin": "",
                "checkout": "",
                "location": "",
                "photo_url": "",
                "data_source": "Booking.com/RapidAPI",
                "notes": "价格为接口返回参考值，最终以 Booking.com 确认页为准。",
            }
            for part in parts[2:]:
                if part.startswith("总价 "):
                    hotel["price_total"] = part.removeprefix("总价 ").strip()
                    currency_match = re.match(r"([A-Z]{3})\s+", hotel["price_total"])
                    if currency_match:
                        hotel["currency"] = currency_match.group(1)
                elif part.startswith("评分 "):
                    hotel["rating"] = part.removeprefix("评分 ").strip()
                elif part.startswith("评论 "):
                    hotel["review_count"] = part.removeprefix("评论 ").strip()
                elif part.startswith("星级 "):
                    hotel["stars"] = part.removeprefix("星级 ").strip()
                elif part.startswith("坐标 "):
                    hotel["location"] = part.removeprefix("坐标 ").strip()
                elif part.startswith("入住 "):
                    hotel["checkin"] = part.removeprefix("入住 ").strip()
                elif part.startswith("离店 "):
                    hotel["checkout"] = part.removeprefix("离店 ").strip()
                elif part.startswith("照片 "):
                    hotel["photo_url"] = part.removeprefix("照片 ").strip()
            hotels.append(hotel)
    return hotels


def enrich_structured_data_from_trace(structured: dict | None, trace: list[dict]) -> dict | None:
    """Patch structured data with deterministic tool-result parsing when the LLM omits optional cards."""
    if not structured:
        return structured
    hotels = parse_hotel_options_from_trace(trace)
    if hotels and not structured.get("hotel_options"):
        structured["hotel_options"] = hotels
    elif hotels and structured.get("hotel_options"):
        trace_by_name = {
            re.sub(r"\s+", "", str(hotel.get("name") or "")).lower(): hotel
            for hotel in hotels
            if hotel.get("name")
        }
        for hotel in structured.get("hotel_options") or []:
            key = re.sub(r"\s+", "", str(hotel.get("name") or "")).lower()
            trace_hotel = trace_by_name.get(key)
            if not trace_hotel:
                continue
            for field in ("photo_url", "location", "price_total", "currency", "rating", "review_count", "stars", "checkin", "checkout"):
                if trace_hotel.get(field):
                    hotel[field] = trace_hotel[field]
    return structured


def strip_structured_json(text: str) -> str:
    """Remove all json code fence blocks from text."""
    if not text:
        return text
    fences = _find_json_fence_pairs(text)
    if not fences:
        return text
    # Remove fences from end to start to preserve earlier indices
    result = text
    for start, end, _content in reversed(fences):
        result = result[:start] + result[end:]
    return result.strip()


def build_memory_summary(message_history: list | None) -> str:
    if not message_history:
        return ""

    joined = "\n".join(str(msg.get("text", "")) for msg in message_history if isinstance(msg, dict))
    if not joined.strip():
        return ""

    memory_items = []
    route_match = re.findall(r"从\s*([\u4e00-\u9fa5A-Za-z]+)\s*(?:去|到|前往)\s*([\u4e00-\u9fa5A-Za-z]+)", joined)
    if route_match:
        origin, destination = route_match[-1]
        origin = _clean_place_name(origin)
        destination = _clean_place_name(destination)
        memory_items.append(f"最近识别到的出发地：{origin}")
        memory_items.append(f"最近识别到的目的地：{destination}")

    days_match = re.findall(r"(\d+)\s*天", joined)
    if days_match:
        memory_items.append(f"最近识别到的行程天数：{days_match[-1]}天")

    people_match = re.findall(r"(\d+)\s*(?:人|个人)", joined)
    if people_match:
        memory_items.append(f"最近识别到的出行人数：{people_match[-1]}人")

    budget_match = re.findall(r"(?:预算|花费|费用)[^\d]*(\d+)\s*(?:元|块|w|万)?", joined, flags=re.IGNORECASE)
    if budget_match:
        memory_items.append(f"最近识别到的预算数字：{budget_match[-1]}")

    preference_keywords = [
        "少走路",
        "美食",
        "博物馆",
        "海边",
        "亲子",
        "自驾",
        "公共交通",
        "慢节奏",
        "紧凑",
        "预算紧张",
        "轻松",
    ]
    preferences = [keyword for keyword in preference_keywords if keyword in joined]
    if preferences:
        memory_items.append("用户偏好：" + "、".join(dict.fromkeys(preferences)))

    if not memory_items:
        return ""

    return "会话记忆摘要：\n" + "\n".join(f"- {item}" for item in memory_items)


def build_current_request_summary(user_input: str) -> str:
    """Extract high-confidence facts from the current user input for the agent."""
    if not user_input:
        return ""

    facts: list[str] = []
    route_match = re.search(r"从\s*([\u4e00-\u9fa5A-Za-z]+)\s*(?:去|到|前往)\s*([\u4e00-\u9fa5A-Za-z]+)", user_input)
    if not route_match:
        route_match = re.search(r"([\u4e00-\u9fa5A-Za-z]+)\s*(?:去|到|前往)\s*([\u4e00-\u9fa5A-Za-z]+)", user_input)
    if route_match:
        origin = _clean_place_name(route_match.group(1))
        destination = _clean_place_name(route_match.group(2))
        facts.append(f"当前轮明确出发地：{origin}")
        facts.append(f"当前轮明确目的地：{destination}")

    days_match = re.search(r"(\d+)\s*天", user_input)
    if days_match:
        facts.append(f"当前轮明确行程天数：{days_match.group(1)}天")

    people_match = re.search(r"(\d+)\s*(?:人|个人)", user_input)
    if people_match:
        facts.append(f"当前轮明确出行人数：{people_match.group(1)}人")

    if not facts:
        return ""

    return (
        "当前轮需求摘要：\n"
        + "\n".join(f"- {item}" for item in facts)
        + "\n这些当前轮信息优先级最高；工具调用参数必须以当前轮明确地点为准，不得使用示例地点或历史地点替代。"
    )


def _clean_place_name(value: str) -> str:
    value = value.strip()
    for suffix in ("旅游", "旅行", "游玩", "玩", "游"):
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
    return value


def run_agent_with_trace(
    user_input: str,
    config: LLMConfig,
    thinking_mode: bool = False,
    message_history: list | None = None,
    client_context: str = "",
) -> tuple[str, list[dict], dict | None]:
    agent = build_agent(config, thinking_mode=thinking_mode)

    # Reconstruct LangChain message list from history + current input
    lc_messages: list[BaseMessage] = []
    memory_summary = build_memory_summary(message_history)
    if memory_summary:
        lc_messages.append(
            SystemMessage(
                content=(
                    memory_summary
                    + "\n请把这些信息作为多轮对话上下文参考。若用户在当前轮明确修改了某项信息，以当前轮为准。"
                )
            )
        )
    if client_context:
        lc_messages.append(SystemMessage(content=client_context))
    if message_history:
        for msg in message_history[-6:]:
            role = msg["role"]
            text = msg["text"]
            if len(text) > 1200:
                text = text[:1200] + "\n[历史消息过长，已截断]"
            if role == "user":
                lc_messages.append(HumanMessage(content=text))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=text))

    current_summary = build_current_request_summary(user_input)
    if current_summary:
        lc_messages.append(SystemMessage(content=current_summary))
    lc_messages.append(HumanMessage(content=user_input))

    response = agent.invoke({"messages": lc_messages})
    messages = response["messages"]
    print_agent_trace(messages)
    answer = extract_final_answer(messages)
    trace = collect_agent_trace(messages)
    structured = enrich_structured_data_from_trace(extract_structured_json(answer), trace)
    cleaned = strip_structured_json(answer)
    return cleaned, trace, structured


def run_agent(
    user_input: str,
    config: LLMConfig,
    thinking_mode: bool = False,
    message_history: list | None = None,
    client_context: str = "",
) -> str:
    answer, _trace, _structured = run_agent_with_trace(
        user_input=user_input,
        config=config,
        thinking_mode=thinking_mode,
        message_history=message_history,
        client_context=client_context,
    )
    return answer


def build_langchain_messages(
    user_input: str,
    message_history: list | None = None,
    client_context: str = "",
) -> list[BaseMessage]:
    lc_messages: list[BaseMessage] = []
    memory_summary = build_memory_summary(message_history)
    if memory_summary:
        lc_messages.append(
            SystemMessage(
                content=(
                    memory_summary
                    + "\n请把这些信息作为多轮对话上下文参考。若用户在当前轮明确修改了某项信息，以当前轮为准。"
                )
            )
        )
    if client_context:
        lc_messages.append(SystemMessage(content=client_context))
    if message_history:
        for msg in message_history[-6:]:
            role = msg["role"]
            text = msg["text"]
            if len(text) > 1200:
                text = text[:1200] + "\n[历史消息过长，已截断]"
            if role == "user":
                lc_messages.append(HumanMessage(content=text))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=text))
    current_summary = build_current_request_summary(user_input)
    if current_summary:
        lc_messages.append(SystemMessage(content=current_summary))
    lc_messages.append(HumanMessage(content=user_input))
    return lc_messages



def stream_agent_events(
    user_input: str,
    config: LLMConfig,
    thinking_mode: bool = False,
    message_history: list | None = None,
    client_context: str = "",
):
    agent = build_agent(config, thinking_mode=thinking_mode)
    lc_messages = build_langchain_messages(user_input, message_history, client_context=client_context)
    initial_message_count = len(lc_messages)
    seen_tool_calls: set[str] = set()
    seen_tool_results: set[str] = set()
    seen_llm_steps: set[int] = set()
    trace: list[dict] = []
    final_answer = ""
    run_started_at = time.monotonic()

    yield {
        "event": "status",
        "message": "请求已发送，智能体开始分析需求。",
        "elapsed_ms": elapsed_ms(run_started_at),
    }

    for chunk in agent.stream({"messages": lc_messages}, stream_mode="values"):
        messages = chunk.get("messages", [])
        if not messages:
            continue

        for step, latest_msg in enumerate(messages[initial_message_count:], start=initial_message_count + 1):
            if isinstance(latest_msg, AIMessage) and getattr(latest_msg, "tool_calls", None):
                for tool_call in latest_msg.tool_calls:
                    key = tool_call.get("id") or f"{step}-{tool_call['name']}-{tool_call.get('args')}"
                    if key in seen_tool_calls:
                        continue
                    seen_tool_calls.add(key)
                    item = {
                        "type": "tool_call",
                        "step": step,
                        "tool": tool_call["name"],
                        "args": tool_call.get("args", {}),
                        "result": "",
                        "tool_call_id": tool_call.get("id"),
                        "status": "running",
                        "started_ms": elapsed_ms(run_started_at),
                        "ended_ms": None,
                        "duration_ms": None,
                    }
                    trace.append(item)
                    yield {
                        "event": "trace",
                        "phase": "tool_call",
                        "message": f"决定调用工具：{tool_call['name']}",
                        "item": public_trace_item(item),
                        "trace": public_trace(trace),
                        "elapsed_ms": elapsed_ms(run_started_at),
                    }

            elif isinstance(latest_msg, ToolMessage):
                key = getattr(latest_msg, "tool_call_id", None) or f"{step}-{latest_msg.name}"
                if key not in seen_tool_results:
                    seen_tool_results.add(key)
                    result = message_text(latest_msg)
                    matched = False
                    for item in trace:
                        if item.get("tool_call_id") == getattr(latest_msg, "tool_call_id", None):
                            finish_trace_item(item, run_started_at, result=result)
                            result_item = item
                            matched = True
                            break
                    if not matched:
                        now_ms = elapsed_ms(run_started_at)
                        result_item = {
                            "type": "tool_result",
                            "step": step,
                            "tool": latest_msg.name,
                            "args": {},
                            "result": result,
                            "status": trace_status_from_result(result),
                            "started_ms": now_ms,
                            "ended_ms": now_ms,
                            "duration_ms": 0,
                        }
                        trace.append(result_item)
                    yield {
                        "event": "trace",
                        "phase": "tool_result",
                        "message": f"工具返回结果：{latest_msg.name or result_item.get('tool') or 'unknown'}",
                        "item": public_trace_item(result_item),
                        "trace": public_trace(trace),
                        "elapsed_ms": elapsed_ms(run_started_at),
                    }

            if isinstance(latest_msg, AIMessage):
                content = message_text(latest_msg).strip()
                if content:
                    final_answer = content
                usage = getattr(latest_msg, "usage_metadata", None)
                response_metadata = getattr(latest_msg, "response_metadata", {}) or {}
                model_name = response_metadata.get("model_name") or response_metadata.get("model")
                if (usage or model_name) and step not in seen_llm_steps:
                    seen_llm_steps.add(step)
                    now_ms = elapsed_ms(run_started_at)
                    item = {
                        "type": "llm_response",
                        "step": step,
                        "model": model_name or "unknown",
                        "usage": usage or {},
                        "status": "success",
                        "started_ms": now_ms,
                        "ended_ms": now_ms,
                        "duration_ms": 0,
                    }
                    trace.append(item)
                    yield {
                        "event": "trace",
                        "phase": "llm_response",
                        "message": f"模型阶段完成：{model_name or 'unknown'}",
                        "item": public_trace_item(item),
                        "trace": public_trace(trace),
                        "elapsed_ms": elapsed_ms(run_started_at),
                    }

    structured_data = enrich_structured_data_from_trace(extract_structured_json(final_answer), public_trace(trace))
    cleaned_answer = strip_structured_json(final_answer) or final_answer

    yield {
        "event": "final",
        "answer": cleaned_answer,
        "structured_data": structured_data,
        "trace": public_trace(trace),
        "elapsed_ms": elapsed_ms(run_started_at),
    }


def run_offline_demo(user_input: str) -> str:
    """No-LLM demo path for checking local tools when no API key is available."""
    from travel_agent.tools import calculate_trip_budget, get_transport_advice, get_weather_info

    print("\n离线演示模式：该模式只验证工具和项目流程，不代表真实 LLM 调用。")
    weather = get_weather_info.invoke({"city": "杭州", "date": DEFAULT_DATE})
    transport = get_transport_advice.invoke({"origin": "郑州", "destination": "杭州"})
    budget = calculate_trip_budget.invoke(
        {
            "city": "杭州",
            "days": 3,
            "person_num": 1,
            "hotel_price_per_night": 300,
            "food_cost_per_day": 120,
            "attraction_fee": 300,
        }
    )

    structured = {
        "summary": "杭州3天经典行程，涵盖西湖、灵隐寺、西溪湿地等核心景点。",
        "weather": [
            {
                "city": "杭州",
                "date": DEFAULT_DATE,
                "temperature": "25.5℃",
                "condition": "晴朗",
                "humidity": "72%",
                "wind": "5.8 km/h",
            }
        ],
        "transport_options": [
            {
                "mode": "高铁 G1880",
                "from": "郑州东",
                "to": "杭州东",
                "duration": "约4小时18分",
                "cost_estimate": "二等座 417元 / 一等座 668元",
                "notes": "06:52-11:10，数据源：12306。建议提前购票，杭州东站下车换乘地铁1号线。",
            },
            {
                "mode": "高铁 G3116",
                "from": "郑州东",
                "to": "杭州东",
                "duration": "约4小时50分",
                "cost_estimate": "二等座 386元 / 一等座 617元",
                "notes": "08:28-13:18，数据源：12306。备选车次，时间较宽裕。",
            },
        ],
        "daily_itinerary": [
            {
                "day": 1,
                "title": "西湖经典游",
                "activities": ["断桥残雪", "白堤", "苏堤春晓", "雷峰塔"],
                "meals": ["西湖醋鱼", "龙井虾仁"],
                "accommodation": "西湖区酒店",
            },
            {
                "day": 2,
                "title": "灵隐禅踪与龙井茶香",
                "activities": ["灵隐寺", "飞来峰", "龙井村", "湖滨商圈"],
                "meals": ["素斋", "杭帮菜"],
                "accommodation": "西湖区酒店",
            },
            {
                "day": 3,
                "title": "西溪湿地与返程",
                "activities": ["西溪湿地", "河坊街"],
                "meals": ["定胜糕", "葱包桧"],
                "accommodation": "",
            },
        ],
        "hotel_options": [],
        "budget": {
            "total": 1260,
            "breakdown": {"住宿": 600, "餐饮": 360, "门票": 300},
            "currency": "CNY",
            "notes": "以1人3天估算，实际费用随季节浮动。",
        },
        "tips": [
            "提前预约西湖游船，避免现场排队",
            "杭州夏季炎热，注意防晒补水",
            "灵隐寺建议上午前往，避开人流高峰",
            "建议购买杭州旅游一卡通，可节省门票费用",
        ],
        "poi_recommendations": [
            {
                "category": "景点推荐",
                "items": [
                    {"name": "西湖风景名胜区", "type": "风景名胜", "address": "杭州市西湖区龙井路1号", "rating": "4.8", "location": "120.130396,30.259242"},
                    {"name": "灵隐寺", "type": "寺庙", "address": "杭州市西湖区法云弄1号", "rating": "4.7", "location": "120.102371,30.240826"},
                    {"name": "西溪国家湿地公园", "type": "公园", "address": "杭州市西湖区天目山路518号", "rating": "4.6"},
                    {"name": "雷峰塔", "type": "文物古迹", "address": "杭州市西湖区南山路15号", "rating": "4.5"},
                ],
            },
            {
                "category": "餐饮推荐",
                "items": [
                    {"name": "楼外楼", "type": "杭帮菜", "address": "杭州市西湖区孤山路30号", "cost": "150元", "tel": "0571-87969682"},
                    {"name": "知味观", "type": "小吃", "address": "杭州市上城区仁和路83号", "cost": "60元"},
                    {"name": "绿茶餐厅", "type": "创意菜", "address": "杭州市西湖区龙井路83号", "cost": "80元"},
                ],
            },
            {
                "category": "商圈推荐",
                "items": [
                    {"name": "湖滨银泰in77", "type": "购物中心", "address": "杭州市上城区延安路258号"},
                    {"name": "河坊街", "type": "特色街区", "address": "杭州市上城区河坊街"},
                    {"name": "武林广场", "type": "商圈", "address": "杭州市拱墅区武林广场"},
                ],
            },
        ],
    }

    return (
        "### 离线演示：杭州3天出行规划\n\n"
        f"用户需求：{user_input}\n\n"
        "【工具调用结果】\n"
        f"{weather}\n\n{transport}\n\n{budget}\n\n"
        "【规划建议】\n"
        "Day1：抵达杭州后游览西湖核心区，路线为断桥、白堤、苏堤、雷峰塔。\n"
        "Day2：上午灵隐寺和飞来峰，下午龙井村，晚上可去湖滨商圈。\n"
        "Day3：西溪湿地和河坊街，返程前预留充足交通时间。\n\n"
        "【说明】真实实验运行时请配置 .env，让 LangChain Agent 调用 LLM 自主选择工具。\n\n"
        "```json\n"
        + json.dumps(structured, ensure_ascii=False, indent=2) +
        "\n```"
    )
