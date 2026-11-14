"""
Web 搜索工具
-----------
调用 DuckDuckGo 免费 instant answer API（无需 Key）。
AI 拿到 [title, url, snippet] 列表后，可以挑选感兴趣的用 web_fetch 深入。
"""

import json
import re
from urllib.parse import quote
from .base import Tool, ToolResult
from . import register
from .web import _is_safe_url  # 复用 SSRF 防护


def _search(args, ctx):
    query = (args.get("query") or "").strip()
    if not query:
        raise ValueError("必须提供 query 参数")

    max_results = int(args.get("max_results") or 10)
    max_results = min(max(max_results, 1), 30)

    # DuckDuckGo 官方 API（无需 Key，轻量 JSON 格式）
    url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_redirect=1&no_html=1"

    try:
        import requests
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AI-Harness/3.0)"
        })
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"搜索请求失败：{e}")

    results = []

    # 先取 Instant Answer（直接答案）
    if data.get("AbstractText"):
        abstract = data["AbstractText"].strip()
        if abstract:
            results.append({
                "title": data.get("Heading") or "直接答案",
                "url": data.get("AbstractURL") or "",
                "snippet": _strip_html(abstract),
            })

    # RelatedTopics（二级相关条目）
    for topic in data.get("RelatedTopics", [])[: max_results - len(results)]:
        if len(results) >= max_results:
            break
        # 有些 topic 是个分组（包含 Topics 子数组）
        if "Topics" in topic:
            for sub in topic["Topics"][:3]:
                if len(results) >= max_results:
                    break
                _append_topic(results, sub)
        else:
            _append_topic(results, topic)

    # 没有 RelatedTopics → 兜底用 text 提示 AI 直接 web_fetch 具体网站
    if not results:
        # 尝试 DuckDuckGo HTML 版本的轻量搜索（更宽松）
        _fallback_search(results, query, max_results)

    if not results:
        return ToolResult(text=f"未找到相关结果：{query}\n（可尝试更精确的关键词，或用 web_fetch 直接访问已知 URL）")

    # 过滤不安全 URL（理论上 DuckDuckGo 不会返回内网，但双重保险）
    safe_results = [r for r in results if not r["url"] or _is_safe_url(r["url"])]

    lines = [f"🔍 搜索：{query}（{len(safe_results)} 条）", "---"]
    for i, r in enumerate(safe_results, 1):
        lines.append(f"{i}. **{r['title']}**")
        if r["url"]:
            lines.append(f"   🔗 {r['url']}")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
        lines.append("")

    return ToolResult(text="\n".join(lines).rstrip())


def _append_topic(results, topic):
    title = topic.get("Text", "")
    url = topic.get("FirstURL", "")
    if title:
        # title 里通常自带 snippet，拆分一下
        parts = title.split(" — ", 1) if " — " in title else title.split(" - ", 1)
        main_title = parts[0]
        snippet = parts[1] if len(parts) > 1 else ""
        results.append({
            "title": main_title,
            "url": url,
            "snippet": snippet[:200],
        })


def _fallback_search(results, query, max_results):
    """DuckDuckGo 无结果时的极简 fallback（从 HTML 页面扒前几个链接）"""
    try:
        import requests
        html = requests.get(
            f"https://duckduckgo.com/html/?q={quote(query)}",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        ).text
        # 解析前 5 个 result-link
        for m in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html
        ):
            if len(results) >= max_results:
                break
            url = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2))
            if url and title:
                results.append({
                    "title": title.strip(),
                    "url": url,
                    "snippet": "",
                })
    except Exception:
        pass  # fallback 也失败就空


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def register_all():
    register(Tool(
        name="web_search", title="搜索互联网", perm="Visitor",
        desc="通过 DuckDuckGo 搜索，返回 [标题 / URL / 摘要] 列表。AI 可挑选感兴趣的再用 web_fetch 深入。",
        usage='{"query":"Python 异步编程最佳实践"}',
        required={"query": "string"}, handler=_search,
    ))
