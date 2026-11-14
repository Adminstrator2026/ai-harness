import json
import requests

def stream_chat(cfg, messages):
    api_url = (cfg.get("api_url") or "").rstrip("/")
    if not api_url:
        yield {"error": "未配置 API 地址"}
        return
    url = api_url + "/chat/completions"
    api_key = cfg.get("api_key") or ""
    model = cfg.get("model") or ""
    if not model:
        yield {"error": "未选择模型"}
        return

    think = int(cfg.get("think_level") or 0)
    payload = {"model": model, "messages": messages, "stream": True}
    if think == 1:
        payload["reasoning_effort"] = "medium"
        payload["enable_thinking"] = True
    elif think == 2:
        payload["reasoning_effort"] = "high"
        payload["enable_thinking"] = True

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with requests.post(url, json=payload, headers=headers,
                           stream=True, timeout=(10, 300)) as r:
            if r.status_code != 200:
                text = r.text[:500] if r.text else ""
                yield {"error": f"HTTP {r.status_code}: {text}"}
                return
            for raw in r.iter_lines(decode_unicode=False):
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    return
                if not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if "error" in obj:
                    err = obj["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    yield {"error": msg or "上游错误"}
                    return
                choice = (obj.get("choices") or [{}])[0]
                delta = choice.get("delta") or choice.get("message") or {}
                rc = delta.get("reasoning_content") or delta.get("reasoning")
                if rc:
                    yield {"reasoning": rc}
                txt = delta.get("content")
                if txt:
                    yield {"text": txt}
    except requests.exceptions.RequestException as e:
        yield {"error": f"请求失败：{e}"}