import os
from .tools import REGISTRY, PERM_LEVEL, PERM_NAME
from .config import CONFIG


def get_workspace_snapshot():
    try:
        items = []
        for entry in os.scandir(CONFIG.WORKDIR):
            if entry.name.startswith('.'):
                continue
            tag = "📁" if entry.is_dir() else "📄"
            size = f" ({entry.stat().st_size} B)" if entry.is_file() else ""
            items.append(f"{tag} {entry.name}{size}")
        if not items:
            return "当前工作区为空。"
        return "当前工作区文件列表：\n" + "\n".join(items[:30])
    except Exception:
        return ""


def build_system_prompt(cfg):
    base = (cfg.get("system") or CONFIG.DEFAULT_SYS).strip()
    workspace_info = get_workspace_snapshot()

    # ── 沙箱模式：二元开关，比 permission 下拉更简单直观 ──
    # sandbox=true  → 强制上限 User（Root 工具不可用）
    # sandbox=false → 用户选什么 permission 就用什么
    sandbox = bool(cfg.get("sandbox_mode", True))
    user_perm = str(cfg.get("permission") or "User")
    if sandbox:
        # 沙箱内：封顶 User，run_cmd / terminal_* / file_delete / http_serve 等 Root 工具被屏蔽
        effective_perm = user_perm if PERM_LEVEL.get(user_perm, 1) < PERM_LEVEL["Root"] else "User"
    else:
        effective_perm = user_perm
    have = int(PERM_LEVEL.get(effective_perm, 1))

    enabled_list = cfg.get("enabled_tools")
    if enabled_list is None:
        enabled_list = list(REGISTRY.keys())

    available = []
    blocked = []
    for t in REGISTRY.values():
        if t.name not in enabled_list:
            continue
        need = int(PERM_LEVEL.get(t.perm or "read", 0))
        if need <= have:
            available.append(t)
        else:
            blocked.append(t)

    # ── System Prompt 拼装 ──
    lines = [base, ""]

    # 沙箱状态横幅（醒目的警告/说明）
    if sandbox:
        lines.append(
            "## 🛡️ 你当前在 **沙箱模式** 下运行"
        )
        lines.append("")
        lines.append(
            "你的执行权限被限制在工作区内。"
            "以下 **高危工具不可用**：Shell 命令执行、进程管理、文件删除、静态服务器。"
        )
        lines.append(
            "如果任务需要这些能力，请提示用户关闭沙箱模式后重试。"
        )
        lines.append("")
        lines.append("**安全执行范围**：")
        lines.append("• ✅ 读文件 / 搜索 / HTTP 请求 / 浏览器读取")
        lines.append("• ✅ 写文件 / Git 提交 / 精准编辑")
        lines.append("• ❌ 执行 Shell / PowerShell 命令")
        lines.append("• ❌ 启动后台进程（开发服务器、worker 等）")
        lines.append("• ❌ 删除文件 / 目录")
        lines.append("• ❌ 暴露静态服务器端口")
        lines.append("")
    else:
        lines.append("## ⚡ 你当前拥有 **完整权限**")
        lines.append("")
        lines.append(
            "⚠️ 可以执行 Shell 命令、启动后台进程、删除文件等高危操作。"
            "请小心：一旦删除文件或启动了错误的进程，后果由你承担。"
            "不确定时优先在沙箱模式下执行。"
        )
        lines.append("")

    # 多模态告知
    lines.append("## 🖼️ 关于图片/视频")
    lines.append("")
    lines.append(
        "用户可能会发送图片或视频（视频会自动抽取关键帧）。"
        "你可以直接看图理解内容、OCR 文字、分析图表等。"
    )
    lines.append("")

    # 工具调用铁律
    lines.extend([
        "## 🚨 工具调用格式（必须绝对遵守，不可擅自修改）",
        "你是一个执行系统的 AI。要执行功能，你**必须**严格按照以下格式输出：",
        "",
        "```xml",
        '<tool name="工具名" args=\'{"参数名":"参数值"}\'/>',
        "```",
        "",
        "### ⚠️ 绝对禁止事项：",
        "1. **禁止用 JSON 格式返回！** 绝对不要输出类似 `{\"tool\": \"xxx\", \"params\": {}}` 或 `{\"name\": \"xxx\", \"args\": {}}` 的 JSON 代码块！系统只认上面示范的 XML 标签格式！",
        "2. **禁止输出空参数或空代码块**，必须填满必填参数！",
        "3. **禁止输出普通文本代码块**（如 ```json 或 ```javascript）来假装执行！",
        "4. **禁止输出 [等待执行中] 等过渡废话**，直接输出 xml 标签即可。",
        "5. **如果用户询问「查看插件」「有什么功能」「你能做什么」，请直接调用 `list_tools` 工具！绝对不要去调用 `file_read` 瞎找配置文件，系统没有这个文件！**",
        "",
        f"## 当前环境状态\n{workspace_info}",
        "",
        "## 你当前可用的真实工具",
    ])

    if not available:
        lines.append("（你当前没有任何可用工具，请直接回答用户。）")
    else:
        for t in available:
            fields = ", ".join(t.required.keys()) if t.required else "无"
            lines.append(f"- **{t.name}**（{t.title}）：{t.desc}")
            lines.append(f"  ⚠️ 必填参数：{fields}")
            if t.usage:
                lines.append(f"  👉 正确示范：")
                lines.append(f"  ```xml")
                lines.append(f"  <tool name=\"{t.name}\" args='{t.usage}'/>")
                lines.append(f"  ```")

    if blocked:
        lines.append("\n## 当前权限不可用的工具")
        for t in blocked:
            lines.append(f"- {t.name}（需要更高权限）")

    return "\n".join(lines)
