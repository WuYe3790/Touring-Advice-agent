from pathlib import Path
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
CACHE_DIR = PROJECT_ROOT / ".cache"
os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))
os.environ.setdefault("TRANSFORMERS_CACHE", str(CACHE_DIR / "transformers"))
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flask import Flask, Response, jsonify, render_template, request, stream_with_context  # noqa: E402

from travel_agent.agent import (  # noqa: E402
    extract_structured_json,
    run_agent_with_trace,
    run_offline_demo,
    stream_agent_events,
    strip_structured_json,
)
from travel_agent.config import load_llm_config  # noqa: E402
from travel_agent.train_tools import is_train_tools_available  # noqa: E402
from travel_agent.storage import (  # noqa: E402
    add_message,
    create_conversation,
    delete_conversation,
    ensure_conversation,
    get_messages,
    init_db,
    list_conversations,
    maybe_update_title,
)


app = Flask(__name__, template_folder="templates", static_folder="static")
load_dotenv()
init_db()

AMAP_BASE_URL = "https://restapi.amap.com/v3"


def amap_key() -> str:
    return os.getenv("AMAP_API_KEY", "").strip()


def amap_request(path: str, params: dict, timeout: int = 10) -> dict:
    key = amap_key()
    if not key:
        raise RuntimeError("未配置 AMAP_API_KEY")
    clean_params = {k: v for k, v in params.items() if v not in ("", None)}
    clean_params["key"] = key
    response = requests.get(f"{AMAP_BASE_URL}{path}", params=clean_params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def public_client_context(payload: dict) -> dict:
    context = payload.get("client_context")
    return context if isinstance(context, dict) else {}


def build_client_context_prompt(context: dict) -> str:
    if not context:
        return ""
    city = str(context.get("city") or "").strip()
    province = str(context.get("province") or "").strip()
    district = str(context.get("district") or "").strip()
    address = str(context.get("address") or "").strip()
    location = str(context.get("location") or "").strip()
    source = str(context.get("source") or "").strip()
    if not any((city, province, district, address, location)):
        return ""
    lines = ["当前用户位置上下文（来自前端定位/高德地图）："]
    if province or city or district:
        lines.append(f"- 默认出发区域：{province}{city}{district}")
    if address:
        lines.append(f"- 默认出发地址：{address}")
    if location:
        lines.append(f"- 默认出发坐标：{location}")
    if source:
        lines.append(f"- 位置来源：{source}")
    lines.append("如果用户没有明确说明出发地，可将该位置作为默认出发地；如果用户明确给出出发地，则必须以用户输入为准。")
    return "\n".join(lines)


def looks_like_garbled_text(text: str) -> bool:
    compact = "".join(text.split())
    if len(compact) < 4:
        return False
    question_count = compact.count("?") + compact.count("？")
    replacement_count = compact.count("�")
    suspicious_count = question_count + replacement_count
    if suspicious_count >= 4 and suspicious_count / max(len(compact), 1) >= 0.35:
        return True
    return replacement_count >= 2


def garbled_error_response():
    return jsonify(
        {
            "error": "输入内容疑似编码乱码，请在网页输入框中重新输入中文，或确认终端使用 UTF-8 编码。",
            "garbled_input": True,
        }
    ), 400


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    config = load_llm_config()
    return jsonify(
        {
            "model": config.model,
            "thinking_model": config.thinking_model,
            "base_url": config.base_url,
            "api_key_loaded": bool(config.api_key),
            "amap_key_loaded": bool(os.getenv("AMAP_API_KEY", "").strip()),
            "qweather_key_loaded": bool(os.getenv("QWEATHER_API_KEY", "").strip()),
            "qweather_host_loaded": bool(os.getenv("QWEATHER_API_HOST", "").strip()),
            "train_tools_available": is_train_tools_available(),
            "aviationstack_key_loaded": bool(os.getenv("AVIATIONSTACK_API_KEY", "").strip()),
        }
    )


@app.get("/api/amap/ip-location")
def amap_ip_location():
    try:
        ip = str(request.args.get("ip", "")).strip()
        if ip in ("127.0.0.1", "::1", "localhost"):
            ip = ""
        data = amap_request("/ip", {"ip": ip, "output": "JSON"})
        if data.get("status") != "1":
            return jsonify({"error": data.get("info", "IP定位失败"), "raw": data}), 400
        return jsonify(
            {
                "source": "amap_ip",
                "province": data.get("province") if isinstance(data.get("province"), str) else "",
                "city": data.get("city") if isinstance(data.get("city"), str) else "",
                "adcode": data.get("adcode") if isinstance(data.get("adcode"), str) else "",
                "rectangle": data.get("rectangle") if isinstance(data.get("rectangle"), str) else "",
                "raw": data,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/amap/reverse-geocode")
def amap_reverse_geocode():
    location = str(request.args.get("location", "")).strip()
    if not location:
        return jsonify({"error": "缺少 location 参数，格式为 lng,lat"}), 400
    try:
        data = amap_request(
            "/geocode/regeo",
            {
                "location": location,
                "extensions": "all",
                "radius": request.args.get("radius", "1000"),
                "output": "JSON",
            },
        )
        if data.get("status") != "1":
            return jsonify({"error": data.get("info", "逆地理编码失败"), "raw": data}), 400
        regeocode = data.get("regeocode") or {}
        component = regeocode.get("addressComponent") or {}
        city = component.get("city")
        if isinstance(city, list):
            city = ""
        return jsonify(
            {
                "source": "browser_geolocation",
                "location": location,
                "address": regeocode.get("formatted_address", ""),
                "province": component.get("province", ""),
                "city": city or component.get("province", ""),
                "district": component.get("district", ""),
                "township": component.get("township", ""),
                "adcode": component.get("adcode", ""),
                "pois": (regeocode.get("pois") or [])[:5],
                "raw": data,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/amap/input-tips")
def amap_input_tips():
    keywords = str(request.args.get("keywords", "")).strip()
    city = str(request.args.get("city", "")).strip()
    if len(keywords) < 2:
        return jsonify({"tips": []})
    try:
        data = amap_request(
            "/assistant/inputtips",
            {"keywords": keywords, "city": city, "citylimit": "false", "datatype": "all", "output": "JSON"},
        )
        tips = data.get("tips") or []
        clean_tips = []
        for tip in tips[:8]:
            if not isinstance(tip, dict):
                continue
            clean_tips.append(
                {
                    "name": tip.get("name", ""),
                    "district": tip.get("district", ""),
                    "address": tip.get("address", ""),
                    "location": tip.get("location", ""),
                    "adcode": tip.get("adcode", ""),
                }
            )
        return jsonify({"tips": clean_tips})
    except Exception as exc:
        return jsonify({"error": str(exc), "tips": []}), 200


@app.get("/api/amap/static-map")
def amap_static_map():
    try:
        params = {
            "location": request.args.get("location", ""),
            "zoom": request.args.get("zoom", "12"),
            "size": request.args.get("size", "640*360"),
            "scale": request.args.get("scale", "2"),
            "markers": request.args.get("markers", ""),
            "labels": request.args.get("labels", ""),
            "paths": request.args.get("paths", ""),
            "traffic": request.args.get("traffic", "0"),
        }
        key = amap_key()
        if not key:
            return jsonify({"error": "未配置 AMAP_API_KEY"}), 500
        clean_params = {k: v for k, v in params.items() if v not in ("", None)}
        clean_params["key"] = key
        response = requests.get(f"{AMAP_BASE_URL}/staticmap", params=clean_params, timeout=10)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/png")
        if "image" not in content_type.lower() or response.content[:1] in (b"{", b"["):
            return Response(status=204)
        return Response(response.content, mimetype=content_type)
    except Exception as exc:
        return Response(status=204)


@app.get("/api/conversations")
def conversations():
    return jsonify({"conversations": list_conversations()})


@app.post("/api/conversations")
def new_conversation():
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip() or None
    return jsonify({"conversation": create_conversation(title)})


@app.get("/api/conversations/<conversation_id>/messages")
def conversation_messages(conversation_id: str):
    return jsonify({"messages": get_messages(conversation_id)})


@app.delete("/api/conversations/<conversation_id>")
def remove_conversation(conversation_id: str):
    deleted = delete_conversation(conversation_id)
    return jsonify({"deleted": deleted})


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()
    offline_demo = bool(payload.get("offline_demo", False))
    thinking_mode = bool(payload.get("thinking_mode", False))
    conversation_id = str(payload.get("conversation_id", "")).strip() or None
    client_context_prompt = build_client_context_prompt(public_client_context(payload))

    # Extract and sanitize fallback conversation history. When conversation_id is
    # available, the server-side SQLite history is the source of truth.
    history = payload.get("history", [])
    MAX_HISTORY = 12
    MAX_HISTORY_TEXT_LENGTH = 2000
    if not isinstance(history, list):
        history = []
    history = [
        {"role": h["role"], "text": h["text"].strip()[:MAX_HISTORY_TEXT_LENGTH]}
        for h in history
        if isinstance(h, dict)
        and h.get("role") in ("user", "assistant")
        and isinstance(h.get("text"), str)
        and h["text"].strip()
    ]
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    if not message:
        return jsonify({"error": "请输入行程需求。"}), 400
    if looks_like_garbled_text(message):
        return garbled_error_response()

    started_at = time.time()
    try:
        conversation_id = ensure_conversation(conversation_id, title_hint=message)
        maybe_update_title(conversation_id, message)
        add_message(conversation_id, "user", message)

        db_history = get_messages(conversation_id, limit=12)
        history_for_agent = [
            {"role": item["role"], "text": item["text"]}
            for item in db_history
            if not (item["role"] == "user" and item["text"] == message and item["id"] == db_history[-1]["id"])
        ]
        if not history_for_agent:
            history_for_agent = history

        config = load_llm_config()
        trace = []
        structured_data = None
        if offline_demo:
            answer = run_offline_demo(message)
            structured_data = extract_structured_json(answer)
            answer = strip_structured_json(answer)
            model = "offline-demo"
            mode = "离线演示"
        else:
            model = config.thinking_model if thinking_mode else config.model
            mode = "深度思考模式" if thinking_mode else "普通模式"
            answer, trace, structured_data = run_agent_with_trace(
                message, config,
                thinking_mode=thinking_mode,
                message_history=history_for_agent,
                client_context=client_context_prompt,
            )
        elapsed = round(time.time() - started_at, 2)
        meta = {"elapsed_seconds": elapsed, "model": model, "mode": mode, "trace": trace}
        if structured_data:
            meta["structured_data"] = structured_data
        add_message(conversation_id, "assistant", answer, meta=meta)
        return jsonify(
            {
                "answer": answer,
                "structured_data": structured_data,
                "elapsed_seconds": elapsed,
                "model": model,
                "mode": mode,
                "trace": trace,
                "conversation_id": conversation_id,
            }
        )
    except Exception as exc:
        elapsed = round(time.time() - started_at, 2)
        if conversation_id:
            add_message(conversation_id, "assistant", f"运行失败：{exc}", meta={"elapsed_seconds": elapsed, "error": True})
        return jsonify({"error": str(exc), "elapsed_seconds": elapsed, "conversation_id": conversation_id}), 500


@app.post("/api/chat/stream")
def chat_stream():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()
    offline_demo = bool(payload.get("offline_demo", False))
    thinking_mode = bool(payload.get("thinking_mode", False))
    conversation_id = str(payload.get("conversation_id", "")).strip() or None
    client_context_prompt = build_client_context_prompt(public_client_context(payload))

    if not message:
        return jsonify({"error": "请输入行程需求。"}), 400
    if looks_like_garbled_text(message):
        return garbled_error_response()

    history = payload.get("history", [])
    if not isinstance(history, list):
        history = []

    def send(data: dict) -> str:
        return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"

    @stream_with_context
    def generate():
        started_at = time.time()
        current_conversation_id = ensure_conversation(conversation_id, title_hint=message)
        maybe_update_title(current_conversation_id, message)
        add_message(current_conversation_id, "user", message)
        yield send({"event": "status", "message": "请求已接收。", "conversation_id": current_conversation_id})

        try:
            db_history = get_messages(current_conversation_id, limit=12)
            history_for_agent = [
                {"role": item["role"], "text": item["text"]}
                for item in db_history[:-1]
            ] or history

            config = load_llm_config()
            trace = []
            structured_data = None
            if offline_demo:
                answer = run_offline_demo(message)
                structured_data = extract_structured_json(answer)
                answer = strip_structured_json(answer)
                model = "offline-demo"
                mode = "离线演示"
                yield send({"event": "status", "message": "离线演示已生成。"})
            else:
                model = config.thinking_model if thinking_mode else config.model
                mode = "深度思考模式" if thinking_mode else "普通模式"
                yield send({"event": "status", "message": f"{mode}启动，模型：{model}"})
                answer = ""
                for event in stream_agent_events(
                    message,
                    config,
                    thinking_mode=thinking_mode,
                    message_history=history_for_agent,
                    client_context=client_context_prompt,
                ):
                    if event.get("event") == "trace":
                        trace = event.get("trace", trace)
                    elif event.get("event") == "final":
                        answer = event.get("answer", "")
                        structured_data = event.get("structured_data")
                        trace = event.get("trace", trace)
                    yield send(event)

            elapsed = round(time.time() - started_at, 2)
            meta = {"elapsed_seconds": elapsed, "model": model, "mode": mode, "trace": trace}
            if structured_data:
                meta["structured_data"] = structured_data
            add_message(current_conversation_id, "assistant", answer, meta=meta)
            yield send(
                {
                    "event": "done",
                    "answer": answer,
                    "structured_data": structured_data,
                    "elapsed_seconds": elapsed,
                    "model": model,
                    "mode": mode,
                    "trace": trace,
                    "conversation_id": current_conversation_id,
                }
            )
        except Exception as exc:
            elapsed = round(time.time() - started_at, 2)
            error_text = f"运行失败：{exc}"
            add_message(current_conversation_id, "assistant", error_text, meta={"elapsed_seconds": elapsed, "error": True})
            yield send({"event": "error", "error": str(exc), "elapsed_seconds": elapsed, "conversation_id": current_conversation_id})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
