import asyncio
import json
import os
import re
import time


def _extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("JSON not found in model response")
    return json.loads(text[start:end + 1])


def _clean_analysis(data):
    result = {
        "score_a": None,
        "score_b": None,
        "map": None,
        "players": [],
        "confidence": 0.0,
        "notes": "",
    }
    if not isinstance(data, dict):
        return result
    for key in ("score_a", "score_b"):
        value = data.get(key)
        if isinstance(value, (int, float)) and 0 <= int(value) <= 99:
            result[key] = int(value)
    map_name = str(data.get("map") or "").strip()
    if map_name:
        result["map"] = map_name[:40]
    try:
        result["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0))))
    except (TypeError, ValueError):
        pass
    result["notes"] = str(data.get("notes") or "")[:400]
    players = data.get("players") or []
    if isinstance(players, list):
        for item in players[:10]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            def number(field):
                try:
                    return max(0, min(200, int(item.get(field, 0))))
                except (TypeError, ValueError):
                    return 0
            result["players"].append({
                "name": name[:40],
                "game_id": str(item.get("game_id") or "")[:30],
                "team": str(item.get("team") or "")[:10].upper(),
                "kills": number("kills"),
                "deaths": number("deaths"),
                "assists": number("assists"),
                "mvp": number("mvp"),
            })
    return result


def analyze_screenshot_sync(image_bytes, mime_type="image/png"):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return {"error": "GEMINI_API_KEY не задан", **_clean_analysis({})}
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        configured_model = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash").strip()
        extra_models = [value.strip() for value in os.getenv("GEMINI_VISION_FALLBACK_MODELS", "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash").split(",") if value.strip()]
        models = list(dict.fromkeys((configured_model, *extra_models)))
        prompt = """
Ты анализируешь скриншот итоговой таблицы матча Standoff 2.
Верни только JSON без Markdown:
{
  "score_a": 13,
  "score_b": 9,
  "map": "Rust",
  "confidence": 0.95,
  "notes": "короткое замечание, если часть данных не видна",
  "players": [
    {"name":"nickname без кланового тега","game_id":"если виден","team":"A или B","kills":20,"deaths":12,"assists":4,"mvp":2}
  ]
}
Не выдумывай значения. Если поле не видно, используй null для счёта/карты и 0 для статистики. Команда слева или сверху — A, справа или снизу — B. Клановые теги в квадратных/круглых скобках не являются частью ника: например, "[RCB] winters" верни как "winters", а "[hhe] kaynakk" как "kaynakk". Сам ник сохрани максимально точно.
"""
        last_error = None
        for model in models:
            for attempt in range(2):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
                    )
                    cleaned = _clean_analysis(_extract_json(response.text))
                    cleaned["model"] = model
                    if model != configured_model:
                        cleaned["notes"] = (cleaned.get("notes","")+f" Использована резервная модель {model}.").strip()
                    return cleaned
                except Exception as exc:
                    last_error = exc
                    raw=str(exc).lower()
                    transient=any(token in raw for token in ("503","unavailable","high demand","resource exhausted","429","timeout"))
                    if transient and attempt==0:
                        time.sleep(1.5)
                        continue
                    break
        raise last_error or RuntimeError("Gemini vision model is unavailable")
    except Exception as exc:
        raw=str(exc)
        lower=raw.lower()
        code="temporarily_unavailable" if any(token in lower for token in ("503","unavailable","high demand","resource exhausted","429","timeout")) else "vision_error"
        return {"error": raw[:300], "error_code":code, **_clean_analysis({})}


async def analyze_screenshot(image_bytes, mime_type="image/png"):
    return await asyncio.to_thread(analyze_screenshot_sync, image_bytes, mime_type)
