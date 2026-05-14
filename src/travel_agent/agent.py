from __future__ import annotations

import json
import re
import time

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from travel_agent.config import LLMConfig
from travel_agent.tools import DEFAULT_DATE, TRAVEL_TOOLS


BASE_SYSTEM_PROMPT_TEMPLATE = """
你是一个资深旅游出行规划智能体。你必须体现"理解需求 -> 拆解任务 -> 调用工具 -> 汇总结果 -> 输出方案"的智能体工作流程。

行为规则：
1. 先理解用户的出发地、目的地、行程日期、天数、人数、预算和偏好。
2. 天气会影响出行体验。只要识别出目的地，就应调用 get_weather_info 查询目的地天气；如果识别出出发地，也可以查询出发地天气。
3. 当用户提供了明确预算计算参数时，调用 calculate_trip_budget。不要编造酒店、餐饮、门票费用；缺少参数时，在最终方案中说明需要用户补充。
4. 当识别出出发地和目的地时，调用 get_transport_advice 获取交通建议。
5. 工具调用后，综合工具结果生成清晰、可执行、面向真实用户的中文旅行规划。
6. 输出必须包含：需求理解、思考摘要、工具调用依据、天气参考、交通建议、每日路线、预算分析或预算缺失说明、注意事项。
7. 今天的默认规划日期参考为 __DEFAULT_DATE__。如果用户说"明天"，可使用这个日期。
8. 输出风格要求：
- 使用规范 Markdown，但不要滥用装饰符号。
- 标题最多使用二级标题和三级标题，不要连续使用长横线分割。
- 表格只在确实适合对比时使用，列数控制在 4 列以内，避免过宽。
- 尽量少用 emoji；除非特别有帮助，每次回答最多使用 0-2 个 emoji。
- 不要在末尾输出泛泛的"还需要我继续吗"式推销问题。
9. 结构化输出要求：每一次最终回答末尾都必须包含一个 json 代码块，即使用户要求"简短回答"也不能省略。Markdown 正文可以简短，但末尾 JSON 是前端卡片渲染必需的数据协议。格式如下。注意：下面只是字段结构示意，不代表真实目的地；所有字段必须以用户当前需求和工具结果为准，不能照抄示例地点。
```json
{
  "summary": "行程整体概述，一句话概括",
  "weather": [{"city": "目的地城市", "date": "日期", "temperature": "温度", "condition": "天气", "humidity": "湿度", "wind": "风速"}],
  "transport_options": [{"mode": "交通方式", "from": "出发地", "to": "目的地", "duration": "耗时", "cost_estimate": "费用估计", "notes": "补充说明"}],
  "daily_itinerary": [{"day": 1, "title": "当日主题", "activities": ["活动1", "活动2"], "meals": ["餐饮建议"], "accommodation": "住宿建议"}],
  "budget": {"total": 0, "breakdown": {"项目": 0}, "currency": "CNY", "notes": "预算说明"},
  "tips": ["提示1", "提示2"]
}
```
要求：内容必须与你的 Markdown 回答保持一致；无数据时使用空数组 []；json 代码块必须放在回答最末尾；不要在 json 之后添加任何文本；不要因为用户要求简短、快速或只回答一句话而省略 json 代码块。
"""

BASE_SYSTEM_PROMPT = BASE_SYSTEM_PROMPT_TEMPLATE.replace("__DEFAULT_DATE__", DEFAULT_DATE)

THINKING_MODE_PROMPT = """
当前已开启深度思考模式：
1. 在回答前进行更充分的需求分析、约束检查和工具选择。
2. 工具调用前先判断为什么需要该工具，避免遗漏关键工具。
3. 最终回答中加入"思考摘要"，说明你如何拆解任务、为什么调用这些工具、如何综合工具结果。
4. 不输出冗长的内部推理链，只输出用户可读的思考摘要和结论。
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
    system_prompt = BASE_SYSTEM_PROMPT + "\n" + identity_prompt + ("\n" + THINKING_MODE_PROMPT if thinking_mode else "")

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
    print(f"\nLLM模式：{'深度思考模式' if thinking_mode else '普通模式'} | 模型：{selected_model}")
    return create_agent(model=llm, tools=TRAVEL_TOOLS, system_prompt=system_prompt)


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
    error_markers = ("error", "traceback", "exception", "失败", "异常", "报错", "错误")
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
    known_keys = ("summary", "weather", "transport_options", "daily_itinerary", "budget", "tips")
    for _start, _end, content in reversed(fences):
        try:
            data = json.loads(content)
            if isinstance(data, dict) and any(k in data for k in known_keys):
                return data
        except json.JSONDecodeError:
            continue
    return None


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
    structured = extract_structured_json(answer)
    cleaned = strip_structured_json(answer)
    return cleaned, collect_agent_trace(messages), structured


def run_agent(
    user_input: str,
    config: LLMConfig,
    thinking_mode: bool = False,
    message_history: list | None = None,
) -> str:
    answer, _trace, _structured = run_agent_with_trace(
        user_input=user_input,
        config=config,
        thinking_mode=thinking_mode,
        message_history=message_history,
    )
    return answer


def build_langchain_messages(user_input: str, message_history: list | None = None) -> list[BaseMessage]:
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
):
    agent = build_agent(config, thinking_mode=thinking_mode)
    lc_messages = build_langchain_messages(user_input, message_history)
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

    structured_data = extract_structured_json(final_answer)
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
                "mode": "高铁",
                "from": "郑州",
                "to": "杭州",
                "duration": "约4小时",
                "cost_estimate": "300-500元",
                "notes": "建议提前购票，杭州东站下车换乘地铁1号线。",
            }
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
