import json, uuid, os, shutil, contextlib, io, sys
from pathlib import Path
from flask import Flask, request, Response, send_from_directory, jsonify
import requests
from .config import CONFIG
from .sessions import get_or_create
from .agent import run_agent
from .tools import REGISTRY
from .tools.shell import _run
from .tools.files import _resolve
from .tools.tabbit_cli import run_cli
from .tools.tabbit import JS_TABS, JS_READ, build_open_js
from .paths import STATIC_DIR
app = Flask(__name__, static_folder=None)


# ─── API Token 认证 ────────────────────────────────────────────
# 如果设置了 AIH_TOKEN，所有 /api/* 端点都需要带 Authorization: Bearer <token>
# 前端静态页面 / 和 /static/* 不需要 token（浏览器直接打开）。

@app.before_request
def _check_token():
    token = CONFIG.TOKEN
    if not token:
        return  # 没配 token，完全开放（开发模式）

    path = request.path
    if not path.startswith("/api/"):
        return  # 静态资源不需要

    # 健康检查也放行（docker healthcheck 用）
    if path == "/api/health":
        return

    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {token}":
        return

    # 也允许 query param 方式（便于 curl / 测试）
    if request.args.get("token") == token:
        return

    return jsonify({"error": "Unauthorized", "hint": "设置 AIH_TOKEN 后所有 /api/* 需要 Bearer token"}), 401


def _count_multimodal(messages):
    """
    扫描 messages 里的多模态元素数量（供日志和安全校验）。
    返回 (图片数量, image_url URL 总字符数)。
    """
    count = 0
    chars = 0
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "image_url":
                url = (item.get("image_url") or {}).get("url", "")
                if url:
                    count += 1
                    chars += len(url)
    return count, chars

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")

@app.route("/static/<path:p>")
def static_files(p):
    return send_from_directory(str(STATIC_DIR), p)

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "version": "3.0"})

@app.get("/api/tools")
def tools():
    return jsonify([t.to_spec() for t in REGISTRY.values()])

@app.post("/api/models")
def list_models():
    payload = request.get_json(force=True) or {}
    api_url = (payload.get("api_url") or "").rstrip("/")
    api_key = payload.get("api_key") or ""
    if not api_url:
        return jsonify({"error": "请先在设置中填写 API 地址"}), 400
    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        r = requests.get(api_url + "/models", headers=headers, timeout=10)
        if r.status_code != 200:
            return jsonify({"error": f"HTTP {r.status_code}: {r.text[:200]}"}), 400
        data = r.json()
        models = [m["id"] for m in data.get("data", [])]
        models.sort()
        return jsonify({"models": models})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.post("/api/save_file")
def save_file():
    payload = request.get_json(force=True) or {}
    filename = payload.get("filename")
    content = payload.get("content")
    if not filename or content is None:
        return jsonify({"error": "缺少 filename 或 content"}), 400

    try:
        target = (CONFIG.WORKDIR / filename).resolve()
        target.relative_to(CONFIG.WORKDIR)  # 路径穿越防护
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return jsonify({"ok": True, "path": str(target)})
    except ValueError:
        return jsonify({"error": "非法的路径"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/chat")
def chat():
    payload = request.get_json(force=True) or {}
    sid = payload.get("session_id") or "sess_" + uuid.uuid4().hex[:12]
    session = get_or_create(sid)
    messages = payload.get("messages") or []

    # ── 多模态安全校验 ──
    total_images, total_image_chars = _count_multimodal(messages)
    if total_image_chars > 400_000:  # 单张图 base64 约 100K~300K，超 400K 警告
        # 不拒绝，只给个 notice 让前端知道可能爆 token
        pass  # 后续可以考虑压缩

    cfg = {
        "api_url": payload.get("api_url"),
        "api_key": payload.get("api_key"),
        "model": payload.get("model"),
        "system": payload.get("system"),
        "tools_enabled": bool(payload.get("tools_enabled")),
        "think_level": payload.get("think_level", 0),
        "permission": payload.get("permission", "workspace"),
        "sandbox_mode": bool(payload.get("sandbox_mode", True)),
    }

    def gen():
        yield f"data: {json.dumps({'type':'session','id':sid}, ensure_ascii=False)}\n\n"
        try:
            for ev in run_agent(cfg, messages, session):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type':'end'}, ensure_ascii=False)}\n\n"

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/ask/<aid>")
def answer(aid):
    payload = request.get_json(force=True) or {}
    sid = payload.get("session_id") or ""
    if not sid:
        return jsonify({"ok": False, "error": "缺少 session_id"}), 400
    session = get_or_create(sid)
    ok = session.resolve_ask(aid, payload.get("answers") or [])
    return jsonify({"ok": ok})

# ─── 插件 HTTP 端点（给前端 JS 插件用） ──────────────────────────

@app.post("/api/plugin/exec")
def plugin_exec():
    payload = request.get_json(force=True) or {}
    cmd = payload.get("command")
    shell_type = payload.get("shell", "cmd")
    if not cmd:
        return jsonify({"error": "缺少 command"}), 400
    try:
        res = _run(shell_type, cmd)
        return jsonify({"ok": True, "result": res})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/plugin/file")
def plugin_file():
    payload = request.get_json(force=True) or {}
    op = payload.get("op")
    try:
        p = _resolve(payload.get("path", ""))
        if op == "read":
            return jsonify({"ok": True, "content": p.read_text(encoding="utf-8", errors="replace")})
        elif op == "write":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(payload.get("content", ""), encoding="utf-8")
            return jsonify({"ok": True})
        elif op == "list":
            items = [f.name for f in p.iterdir()]
            return jsonify({"ok": True, "items": items})
        elif op == "delete":
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            return jsonify({"ok": True})
        else:
            return jsonify({"error": "未知 op"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Tabbit 插件：action → JS 脚本映射
# 底层 run_cli 由 tools/tabbit_cli.py 提供，JS 模板由 tools/tabbit.py 提供
_TABBIT_ACTIONS = {
    "tabs":  JS_TABS,
    "text":  JS_READ,
}

@app.post("/api/plugin/tabbit")
def plugin_tabbit():
    payload = request.get_json(force=True) or {}
    action = (payload.get("action") or "").strip()

    if not action:
        return jsonify({"ok": False, "error": "缺少 action 参数"}), 400

    try:
        # open 是唯一一个需要动态构造 JS（URL 参数来自 payload）
        if action == "open":
            url = payload.get("url") or ""
            if not url or not str(url).startswith(("http", "https")):
                return jsonify({"ok": False, "error": f"无效的 URL: {url}"}), 400
            js_code = build_open_js(url)
        elif action in _TABBIT_ACTIONS:
            js_code = _TABBIT_ACTIONS[action]
        else:
            return jsonify({"ok": False, "error": f"未知 action: {action}"}), 400

        result = run_cli(js_code, task=(payload.get("group") or payload.get("task") or "ai-assistant"))
        return jsonify({"ok": True, "result": result})

    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─── 入口 ───────────────────────────────────────────────────────

def main():
    # 初始化可写目录（frozen 模式下把 plugins 拷到 %APPDATA%）
    from .paths import ensure_dirs
    ensure_dirs()

    # 用 lolcat + figlet 组装彩虹横幅（纯 Python，零依赖）
    from .art import build_banner
    banner = build_banner(
        host=CONFIG.HOST,
        port=CONFIG.PORT,
        workdir=CONFIG.WORKDIR,
        token_enabled=bool(CONFIG.TOKEN),
        os_info=os.sys.platform,
        version="3.0",
        tools=REGISTRY,
    )
    # GBK 终端兜底（Windows cmd 默认 cp936 不支持 emoji）
    try:
        print(banner)
    except UnicodeEncodeError:
        safe = banner.encode(sys.stdout.encoding or "utf-8", errors="replace")
        print(safe.decode(sys.stdout.encoding or "utf-8"))

    # 启动 REPL 指令行（daemon 线程，不影响 Flask 主线程）
    import threading
    from .cli import run_repl
    repl_thread = threading.Thread(target=run_repl, name="aih-repl", daemon=True)
    repl_thread.start()

    # 静默 Flask/Werkzeug 默认输出（Running on / Serving Flask app / WARNING 等）
    # REPL 线程的 _out() 用 sys.__stdout__，不受 redirect_stdout/stderr 影响
    _hole = io.StringIO()
    with contextlib.redirect_stdout(_hole), contextlib.redirect_stderr(_hole):
        app.run(host=CONFIG.HOST, port=CONFIG.PORT, threaded=True, use_reloader=False)

if __name__ == "__main__":
    main()
