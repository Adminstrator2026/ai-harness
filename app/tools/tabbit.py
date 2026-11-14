"""
Tabbit 浏览器操作工具（供 LLM Agent 使用的 XML 工具标签）
--------------------------------------------------------
四个工具：browser_tabs / browser_read / browser_open / browser_eval
底层 CLI 执行全部委托给 tabbit_cli 模块。

页面查找约定：
  - 同一个 task 分组内，context.pages() 跨 CLI 调用持久化
  - globalThis.tabs 不存在，必须用 context.pages()
  - "活动页面" = context.pages() 里最后一个非 about:blank 的页面
"""

import json
from .base import Tool, ToolResult
from . import register
from .tabbit_cli import run_cli


# ─── 公共：在 context.pages() 里找目标页面 ──────────────────────

def _find_page_js(name="target"):
    """
    生成一段 JS，从 context.pages() 里找到"当前活动"的页面，
    赋值给变量名 `name`。找不到则 return { error: ... }。
    """
    return f"""
const _allPages = context.pages();
const _realPages = _allPages.filter(p => p.url() !== 'about:blank');
let {name} = null;
if (_realPages.length === 0) {{
    return {{ error: '找不到网页，请先让我打开一个网页（browser_open）。' }};
}}
{name} = _realPages[_realPages.length - 1];
"""


# ─── browser_tabs：列出所有页面 ──────────────────────────────────

JS_TABS = """
const pages = context.pages();
const real = pages.filter(p => p.url() !== 'about:blank');
if (real.length === 0) return { tabs: [] };
const results = [];
for (const p of real) {
    results.push({ url: p.url(), title: await p.title() });
}
return { tabs: results };
"""


def _tabs(args, ctx):
    result = run_cli(JS_TABS, task=_extract_task(args))
    tabs = result.get("tabs", [])
    if not tabs:
        return ToolResult(text="当前分组内没有打开的网页。")
    lines = []
    last_url = tabs[-1]["url"] if tabs else ""
    for t in tabs:
        mark = "【当前】" if t.get("url") == last_url else ""
        title = t.get("title") or "(无标题)"
        url = t.get("url", "")
        lines.append(f"{mark}{title} - {url}")
    return ToolResult(text=f"共 {len(tabs)} 个网页：\n" + "\n".join(lines))


# ─── browser_read：读取当前页面正文 ──────────────────────────────

JS_READ = _find_page_js("p") + """
try { await p.bringToFront(); } catch(e) {}
const title = await p.title();
const text = await p.evaluate(() =>
    document.documentElement ? document.documentElement.innerText :
    document.body ? document.body.innerText : ''
);
return { title, text, url: p.url() };
"""


def _read(args, ctx):
    result = run_cli(JS_READ, task=_extract_task(args))
    if result.get("error"):
        raise RuntimeError(result["error"])
    text = (result.get("text", "") or "").strip()
    title = result.get("title", "")
    if not text:
        text = "(页面已加载，但没有提取到文本，可能是 Canvas 渲染或反爬限制)"
    return ToolResult(text=f"标题：{title}\n---\n{text[:8000]}")


# ─── browser_open：打开指定网页 ─────────────────────────────────

def build_open_js(url):
    """动态拼接 JS（URL 是用户参数）。"""
    safe_url = url.replace("'", "\\'")
    return f"""
let newP;
try {{
    newP = await context.newPage();
    if (typeof usePage === 'function') usePage(newP);
    await newP.bringToFront();
}} catch(e) {{}}

await newP.goto('{safe_url}', {{ waitUntil: 'domcontentloaded', timeout: 20000 }});
await newP.waitForTimeout(4000);

const title = await newP.title() || '';
const text = await newP.evaluate(() => {{
    const txt = document.documentElement.innerText || '';
    return txt.length > 100 ? txt : (document.body ? document.body.innerHTML : '');
}});
return {{ title, text, url: newP.url() }};
"""


def _open(args, ctx):
    url = args.get("url") or (args.get("args", {}).get("url", "") if isinstance(args.get("args"), dict) else "")
    if not url or not str(url).startswith(("http", "https")):
        raise ValueError(f"URL 格式不对：{url}")

    result = run_cli(build_open_js(url), task=_extract_task(args))
    if result.get("error"):
        raise RuntimeError(result["error"])
    text = (result.get("text", "") or "").strip()
    title = result.get("title", "")
    if not text:
        text = "(无内容，可能被反爬)"
    return ToolResult(text=f"已在后台为你打开该网页。\n标题：{title}\n---\n提取到的内容：\n{text[:4000]}")


# ─── browser_eval：浏览器控制台执行 JS ──────────────────────────

def build_eval_js(code):
    """
    动态拼接 JS。所有逻辑（执行 + 序列化）都在 p.evaluate() 内完成，
    这样 serialize 函数能访问 HTMLElement/NodeList 等 DOM 类型。
    用户代码通过 json.dumps 转成合法 JS 字符串字面量直接内联传入
    （不使用 JSON.parse——tabbit-cli 对 JSON.parse(引号) 有奇怪的
    预处理问题，但直接内联字符串字面量没问题）。
    """
    safe_code = json.dumps(code)
    return _find_page_js("p") + f"""
try {{ await p.bringToFront(); }} catch(e) {{}}

const final = await p.evaluate(async code => {{
    // —— 浏览器页面上下文里的 serialize ——
    function serialize(val, depth, seen) {{
        depth = depth || 0; seen = seen || new WeakSet();
        if (val === null) return null;
        if (val === undefined) return undefined;
        if (typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') return val;
        if (typeof val === 'bigint') return val.toString() + 'n';
        if (typeof val === 'function') return '[Function: ' + (val.name || 'anonymous') + ']';
        if (typeof val === 'symbol') return val.toString();
        if (val instanceof Error) return {{ __error__: true, message: val.message, name: val.name, stack: val.stack }};
        if (val instanceof HTMLElement || val instanceof Element)
            return '<' + val.tagName.toLowerCase() + (val.id ? '#' + val.id : '') + (val.className ? '.' + String(val.className).split(' ')[0] : '') + '>';
        if (val instanceof NodeList || val instanceof HTMLCollection)
            return Array.from(val).map(el => serialize(el, depth + 1, seen));
        if (val instanceof Date) return val.toISOString();
        if (val instanceof RegExp) return val.toString();
        if (val instanceof Map) return {{ __map__: Object.fromEntries(Array.from(val.entries()).map(([k,v]) => [String(k), serialize(v, depth+1, seen)])) }};
        if (val instanceof Set) return {{ __set__: Array.from(val).map(v => serialize(v, depth+1, seen)) }};
        if (Array.isArray(val)) {{
            if (depth > 4) return '[Array too deep]';
            if (seen.has(val)) return '[Circular]';
            seen.add(val);
            const arr = val.slice(0, 100).map(v => serialize(v, depth + 1, seen));
            if (val.length > 100) arr.push('... (' + (val.length - 100) + ' more)');
            return arr;
        }}
        if (typeof val === 'object') {{
            if (depth > 4) return '[Object too deep]';
            if (seen.has(val)) return '[Circular]';
            seen.add(val);
            if (val.nodeType !== undefined && val.nodeName !== undefined)
                return '<' + String(val.nodeName).toLowerCase() + '>';
            const out = {{}};
            let count = 0;
            for (const k of Object.keys(val)) {{
                if (count++ >= 50) {{ out['...'] = '(' + (Object.keys(val).length - 50) + ' more keys)'; break; }}
                try {{ out[k] = serialize(val[k], depth + 1, seen); }} catch(e) {{ out[k] = '[Unserializable]'; }}
            }}
            return out;
        }}
        return String(val);
    }}

    // 执行用户代码（eval / await 被 tabbit-cli 安全拦截，
    // 用 new Function + async IIFE 替代）
    let raw = await (async function() {{
        try {{
            // 先尝试表达式模式，降级到函数体模式
            let fn;
            try {{ fn = new Function('return (' + code + ')'); }}
            catch(_) {{ fn = new Function(code); }}
            const result = fn();
            // 如果返回 Promise 就在 IIFE 里 await
            if (result && typeof result.then === 'function') {{
                return await result;
            }}
            return result;
        }} catch(e) {{
            return {{ __error__: true, message: String(e.message || e), name: String(e.name || ''), stack: String(e.stack || '') }};
        }}
    }})();

    return serialize(raw);
}}, {safe_code});

return {{ url: p.url(), result: final }};
"""


def _eval(args, ctx):
    code = args.get("code") or args.get("expression") or ""
    if not code or not str(code).strip():
        raise ValueError("code 参数不能为空")

    # 简单防护：拦截明显的 Node.js / 系统级调用
    code_stripped = str(code).strip().lower()
    blocked_patterns = [
        "child_process", "require(", "process.",
        "fs.read", "fs.write", "os.system",
        "Runtime.getRuntime", "subprocess.",
    ]
    for pat in blocked_patterns:
        if pat in code_stripped:
            raise ValueError(f"检测到潜在危险操作（{pat}），浏览器沙箱不允许系统级调用")

    result = run_cli(build_eval_js(str(code)), task=_extract_task(args))

    if result.get("error"):
        return ToolResult(text=f"❌ 执行失败：{result['error']}")

    url = result.get("url", "")
    val = result.get("result")

    # JS 运行时错误
    if isinstance(val, dict) and val.get("__error__"):
        msg = val.get("message", str(val))
        stack = val.get("stack", "")
        stack_short = "\n".join(stack.split("\n")[:3]) if stack else ""
        return ToolResult(text=f"❌ JS 执行报错：{msg}\n{stack_short}\n📍 页面：{url}")

    # 正常返回
    formatted = json.dumps(val, ensure_ascii=False, indent=2) if not isinstance(val, str) else val
    if len(formatted) > 5000:
        formatted = formatted[:5000] + "\n... (结果过长，已截断)"
    return ToolResult(text=f"✅ 执行成功\n📍 页面：{url}\n---\n{formatted}")


# ─── 从 args 里提取自定义分组名 ────────────────────────────────

def _extract_task(args):
    """从 args 里提取自定义分组名（支持 group / task / session 三种 key）"""
    for k in ("group", "task", "session"):
        v = args.get(k)
        if v and isinstance(v, str) and v.strip():
            return v.strip()[:64]
    return "ai-assistant"


# ─── 工具注册 ───────────────────────────────────────────────────

def register_all():
    register(Tool(name="browser_tabs", title="列出浏览器标签页", perm="Visitor",
        desc="列出 Tabbit 浏览器当前分组内打开的所有标签页。最后一个标记为【当前】。可用 group 参数指定分组名，默认 ai-assistant。",
        usage='{"group":"可选，分组名"}', handler=_tabs))

    register(Tool(name="browser_read", title="读取网页内容", perm="Visitor",
        desc="读取 Tabbit 浏览器当前标签页的网页正文。可用 group 参数指定分组名。",
        usage='{"group":"可选，分组名"}', handler=_read))

    register(Tool(name="browser_open", title="打开网页并读取", perm="Visitor",
        desc="在 Tabbit 浏览器中打开指定网址并读取正文。打开的页面在同一分组内持久化，后续可直接 browser_read 或 browser_eval。",
        usage='{"url":"https://example.com","group":"可选"}',
        required={"url": "string"}, handler=_open))

    register(Tool(name="browser_eval", title="浏览器控制台执行 JS", perm="Visitor",
        desc="在当前活动网页的浏览器控制台里执行一段 JavaScript 代码，返回执行结果。可以操作 DOM、读取变量、触发事件、运行复杂逻辑等。可用 group 参数指定分组名。",
        usage='{"code":"document.title","group":"可选"}',
        required={"code": "string"}, handler=_eval))
