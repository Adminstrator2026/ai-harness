import requests
import re
import ipaddress
from urllib.parse import urlparse
from .base import Tool, ToolResult
from . import register

def _is_safe_url(url):
    """防止 SSRF 攻击（禁止访问内网 IP）"""
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'): return False
        host = p.hostname
        if not host: return False
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback:
                return False
        except ValueError:
            pass
        return True
    except Exception:
        return False

def _fetch(args, ctx):
    url = args.get("url")
    if not url or not isinstance(url, str):
        raise ValueError("必须提供 url 参数")
    if not _is_safe_url(url):
        raise ValueError("禁止访问的 URL（仅允许 http/https，且禁止访问内网）")

    method = str(args.get("method") or "GET").upper()
    
    # 处理 Headers
    headers = args.get("headers")
    if not isinstance(headers, dict): 
        headers = {}
    if not any(k.lower() == 'user-agent' for k in headers):
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    try: timeout = int(args.get("timeout") or 15)
    except: timeout = 15
    try: max_chars = int(args.get("max_chars") or 8000)
    except: max_chars = 8000

    req_kwargs = {
        "method": method,
        "url": url,
        "headers": headers,
        "timeout": timeout,
    }

    # 💡 核心逻辑：智能识别发送内容
    # 1. 优先处理 JSON 请求
    if args.get("json") is not None:
        req_kwargs["json"] = args.get("json")
        if not any(k.lower() == "content-type" for k in headers):
            req_kwargs["headers"]["Content-Type"] = "application/json"
            
    # 2. 其次处理表单/Data 数据
    elif args.get("data") is not None:
        req_kwargs["data"] = args.get("data")
        
    # 3. 兼容大模型有时会习惯性用 body 字段
    elif args.get("body") is not None:
        req_kwargs["data"] = args.get("body")

    try:
        resp = requests.request(**req_kwargs)
    except Exception as e:
        raise RuntimeError(f"请求失败：{e}")

    resp.encoding = resp.apparent_encoding or 'utf-8'
    text = resp.text
    
    # 💡 如果响应是 HTML 网页，强制剥离脚本和样式，只留纯文本
    content_type = resp.headers.get("Content-Type", "").lower()
    if "text/html" in content_type:
        text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
        text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text)

    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n... (内容过长，已截断)"

    return ToolResult(text=f"HTTP {resp.status_code}\nURL: {url}\n\n{text}")

def register_all():
    register(Tool(
        name="web_fetch", 
        title="发送网络请求", 
        perm="Visitor",
        desc="发送 HTTP 请求访问互联网，获取数据或调用 API。支持各种请求方法和参数格式。",
        usage='{"url":"https://httpbin.org/post","method":"POST","json":{"name":"AI"}}', 
        required={"url": "string"}, 
        handler=_fetch
    ))