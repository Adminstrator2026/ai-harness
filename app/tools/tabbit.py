"""
Tabbit 浏览器操作工具（供 LLM Agent 使用的 XML 工具标签）
--------------------------------------------------------
三个工具：browser_tabs / browser_read / browser_open
底层 CLI 执行全部委托给 tabbit_cli 模块。
"""

from .base import Tool, ToolResult
from . import register
from .tabbit_cli import run_cli


# ─── JS 模板（Agent 工具和 HTTP 插件共用，只写一份） ──────────────

JS_TABS = """
let activeTabs = [];
if (typeof globalThis.tabs !== 'undefined' && globalThis.tabs.length > 0) {
    activeTabs = globalThis.tabs.map(t => ({
        tabId: t.tabId, title: t.title, url: t.url, active: !!t.active
    }));
}
activeTabs = activeTabs.filter(t => t.url !== 'about:blank');
if (activeTabs.length === 0) return { tabs: [] };
return { tabs: activeTabs };
"""


def _tabs(args, ctx):
    result = run_cli(JS_TABS)
    tabs = result.get("tabs", [])
    if not tabs:
        return ToolResult(text="当前没有打开的网页标签。")
    lines = []
    for t in tabs:
        mark = "【当前】" if t.get("active") else ""
        title = t.get("title") or "(无标题)"
        url = t.get("url")
        lines.append(f"{mark}{title} - {url}")
    return ToolResult(text="\n".join(lines))


# ─── 读取当前页面正文 ────────────────────────────────────────────

JS_READ = """
// 找当前活动标签，找不到就抓最后面的
let urlToRead = '';
if (typeof globalThis.tabs !== 'undefined') {
    const t = globalThis.tabs.find(x => x.active);
    if (t) urlToRead = t.url;
    if (!urlToRead && globalThis.tabs.length > 0)
        urlToRead = globalThis.tabs[globalThis.tabs.length - 1].url;
}
if (!urlToRead) return { error: '找不到网页，请先让我打开一个网页。' };

const p = await context.newPage();
try { await p.bringToFront(); } catch(e) {}
try { await p.goto(urlToRead, { waitUntil: 'domcontentloaded', timeout: 20000 }); } catch(e) {}
await p.waitForTimeout(3000);  // 死等 3 秒让 SPA 渲染

const title = await p.title();
const text = await p.evaluate(() =>
    document.documentElement ? document.documentElement.innerText :
    document.body ? document.body.innerText : ''
);
await p.close();
return { title, text };
"""


def _read(args, ctx):
    result = run_cli(JS_READ)
    if result.get("error"):
        raise RuntimeError(result["error"])
    text = (result.get("text", "") or "").strip()
    title = result.get("title", "")
    if not text:
        text = "(页面已加载，但没有提取到文本，可能是 Canvas 渲染或反爬限制)"
    return ToolResult(text=f"标题：{title}\n---\n{text[:8000]}")


# ─── 打开指定网页并读取内容 ──────────────────────────────────────

def build_open_js(url):
    """动态拼接 JS 代码（因为 URL 是用户参数，不硬编码在模板里）"""
    safe_url = url.replace("'", "\\'")
    return f"""
let newP;
try {{
    newP = await context.newPage();
    if (typeof usePage === 'function') usePage(newP);
    await newP.bringToFront();
}} catch(e) {{}}

await newP.goto('{safe_url}', {{ waitUntil: 'domcontentloaded', timeout: 20000 }});
await newP.waitForTimeout(4000);  // 死等 4 秒

const title = await newP.title() || '';
const text = await newP.evaluate(() => {{
    const txt = document.documentElement.innerText || '';
    return txt.length > 100 ? txt : (document.body ? document.body.innerHTML : '');
}});
return {{ title, text }};
"""


def _open(args, ctx):
    url = args.get("url") or (args.get("args", {}).get("url", "") if isinstance(args.get("args"), dict) else "")
    if not url or not str(url).startswith(("http", "https")):
        raise ValueError(f"URL 格式不对：{url}")

    result = run_cli(build_open_js(url))
    if result.get("error"):
        raise RuntimeError(result["error"])
    text = (result.get("text", "") or "").strip()
    title = result.get("title", "")
    if not text:
        text = "(无内容，可能被反爬)"
    return ToolResult(text=f"已在后台为你打开该网页。\n标题：{title}\n---\n提取到的内容：\n{text[:4000]}")


# ─── 工具注册 ───────────────────────────────────────────────────

def register_all():
    register(Tool(name="browser_tabs", title="列出浏览器标签页", perm="Visitor",
        desc="列出当前浏览器打开的所有标签页。", usage="{}", handler=_tabs))

    register(Tool(name="browser_read", title="读取网页内容", perm="Visitor",
        desc="读取当前标签页的网页文本。", usage="{}", handler=_read))

    register(Tool(name="browser_open", title="打开网页并读取", perm="Visitor",
        desc="在浏览器中打开指定网址并读取正文。",
        usage='{"url":"https://example.com"}',
        required={"url": "string"}, handler=_open))
