"""
ANSI 彩虹 + ASCII 大字引擎 —— 纯 Python，零依赖

核心特性（这次新加的！）：
  ✅ 动态探测终端宽度（shutil.get_terminal_size）
  ✅ ANSI 感知的 visual_len() — 转义序列不算显示宽度
  ✅ ANSI 感知的截断 — 不会把 \\033[38;2;255;0;0m 剪半截
  ✅ 自动降级：终端 < 60 列 → 去掉 figlet 大字，纯文字版
  ✅ 路径自动缩短：超长路径用中间省略号
  ✅ Windows 10+ 自动开 VT 模式

lolcatcat (busyloop/lolcatcat) 原理：
  给每行文字按字符位置映射 HSV→RGB，24-bit ANSI 前景色。
figlet (cmatsuoka/figlet) 原理：
  .flf 字体文件，每个字符是多行 ASCII 图形。
"""

import sys
import re
import math
import shutil
import os


# ═══════════════════════════════════════════════════════════════════
# 0. 终端探测 + Windows VT 模式
# ═══════════════════════════════════════════════════════════════════

def _detect_width():
    """获取终端宽度，失败返回默认值"""
    try:
        size = shutil.get_terminal_size(fallback=(80, 24))
        w = size.columns
        # 最小 40（再窄就降级），最大 120（太宽的横幅也难看）
        return max(40, min(w, 120))
    except Exception:
        return 62


def _supports_color():
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if sys.platform == "win32":
        return True
    return sys.stdout.isatty()


# Windows 强制开 VT 模式（让 cmd/powershell 能显示 24-bit 颜色）
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 0x0007)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# 1. ANSI 工具：visual_len / ansi_truncate / ansi_strip
# ═══════════════════════════════════════════════════════════════════

# ANSI 转义序列正则（CSI 序列：\033[...m 这种）
_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


def visual_len(s):
    """计算字符串的**显示宽度**（ANSI 转义序列不算）"""
    if not s:
        return 0
    return len(_ANSI_RE.sub('', s))


def ansi_strip(s):
    """去掉所有 ANSI 转义序列，返回纯文本"""
    return _ANSI_RE.sub('', s)


def ansi_truncate(s, max_width, pad="…"):
    """
    按**显示宽度**截断字符串（ANSI 安全）。
    比如 ansi_truncate("\033[38;2;255;0;0mhello world\033[0m", 8)
    → "\033[38;2;255;0;0mhello …\033[0m"  （保留了原始颜色！）
    """
    if visual_len(s) <= max_width:
        return s

    # 提取前缀（所有前导 ANSI 序列）和后缀（末尾 reset）
    prefix_match = re.match(r'^(\x1b\[[0-9;?]*[A-Za-z])+', s)
    suffix_match = re.search(r'(\x1b\[[0-9;?]*[A-Za-z])+$', s)
    prefix = prefix_match.group(0) if prefix_match else ""
    suffix = suffix_match.group(0) if suffix_match else ""

    # 中间纯文本部分
    stripped = ansi_strip(s)
    target = max_width - len(pad)
    truncated_text = stripped[:target] + pad

    return prefix + truncated_text + suffix


def ansi_center(text, width):
    """
    ANSI 感知的居中。
    纯文字算 visual_len，padding 按实际显示宽度。
    """
    vlen = visual_len(text)
    if vlen >= width:
        return ansi_truncate(text, width)

    # 从 text 里提取前导 ANSI 前缀
    prefix_match = re.match(r'^(\x1b\[[0-9;?]*[A-Za-z])+', text)
    prefix = prefix_match.group(0) if prefix_match else ""
    plain_text = ansi_strip(text)

    pad = (width - vlen) // 2
    return " " * pad + prefix + plain_text


def shorten_path(path, max_len=20):
    """把超长路径用中间省略号截断"""
    if len(path) <= max_len:
        return path
    # 尝试找最后一个分隔符
    sep = "\\" if "\\" in path else "/"
    parts = path.split(sep)
    if len(parts) <= 2:
        return path[:max_len - 1] + "…"
    # 保留首段和末段
    head = parts[0] + sep
    tail = sep.join(parts[-1:])
    mid_len = max_len - len(head) - len(tail) - 1
    if mid_len <= 0:
        return path[:max_len - 1] + "…"
    return head + "…" + path[-mid_len - len(tail):]


# ═══════════════════════════════════════════════════════════════════
# 2. LOLCAT — 彩虹着色（同前）
# ═══════════════════════════════════════════════════════════════════

_RESET = "\033[0m"
_BOLD = "\033[1m"


def _rgb(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"


def _hsv_to_rgb(h, s, v):
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    switch = i % 6
    if switch == 0: r, g, b = v, t, p
    elif switch == 1: r, g, b = q, v, p
    elif switch == 2: r, g, b = p, v, t
    elif switch == 3: r, g, b = p, q, v
    elif switch == 4: r, g, b = t, p, v
    else:             r, g, b = v, p, q
    return int(r * 255), int(g * 255), int(b * 255)


def lolcat_line(text, freq=0.12, offset=0, bold=False):
    """给一行文字叠彩虹（ANSI 安全）"""
    out = []
    for i, ch in enumerate(text):
        if ch == "\n":
            out.append("\n")
            continue
        hue = (i * freq + offset) % 1.0
        r, g, b = _hsv_to_rgb(hue, 1.0, 1.0)
        out.append(_BOLD + _rgb(r, g, b) if bold else _rgb(r, g, b))
        out.append(ch)
    out.append(_RESET)
    return "".join(out)


def lolcat_block(text, freq=0.12, bold_first_line=True):
    """多行叠彩虹，每行 offset 递增"""
    lines = text.split("\n")
    out = []
    for idx, line in enumerate(lines):
        b = bold_first_line and idx == 0
        offset = idx * 0.06
        out.append(lolcat_line(line, freq=freq, offset=offset, bold=b))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════════
# 3. FIGLET — 内置字体（同前）
# ═══════════════════════════════════════════════════════════════════

_FONT = {
    "A": ["  ██████  ", " ██    ██", " ████████", " ██    ██", " ██    ██"],
    "B": [" ████████ ", " ██    ██", " ████████ ", " ██    ██", " ████████ "],
    "C": ["  ███████", " ██      ", " ██      ", " ██      ", "  ███████"],
    "D": [" ████████ ", " ██    ██ ", " ██    ██ ", " ██    ██ ", " ████████ "],
    "E": [" ████████", " ██      ", " ███████ ", " ██      ", " ████████"],
    "F": [" ████████", " ██      ", " ███████ ", " ██      ", " ██      "],
    "G": ["  ███████", " ██      ", " ██ ████ ", " ██    ██", "  ███████"],
    "H": [" ██    ██", " ██    ██", " ████████", " ██    ██", " ██    ██"],
    "I": ["   ███   ", "    █    ", "    █    ", "    █    ", "   ███   "],
    "J": ["      ███", "       █ ", "       █ ", " ██    █ ", "  █████  "],
    "K": [" ██    ██", " ██  ██  ", " ████    ", " ██  ██  ", " ██    ██"],
    "L": [" ██      ", " ██      ", " ██      ", " ██      ", " ████████"],
    "M": [" ██    ██", " ████  ████", " ██ ████ ██", " ██  ██  ██", " ██      ██"],
    "N": [" ██    ██", " ████   ██", " ██ ██  ██", " ██  ██ ██", " ██   ████"],
    "O": ["  █████  ", " ██   ██ ", " ██   ██ ", " ██   ██ ", "  █████  "],
    "P": [" ███████ ", " ██    ██", " ███████ ", " ██      ", " ██      "],
    "Q": ["  █████  ", " ██   ██ ", " ██ █ ██ ", " ██  ███ ", "  ███ ██ "],
    "R": [" ███████ ", " ██    ██", " ███████ ", " ██  ██  ", " ██   ██ "],
    "S": ["  ███████", " ██      ", "  ██████ ", "      ██ ", " ███████ "],
    "T": [" ████████", "    █    ", "    █    ", "    █    ", "    █    "],
    "U": [" ██    ██", " ██    ██", " ██    ██", " ██    ██", "  █████  "],
    "V": [" ██    ██", " ██    ██", " ██    ██", "  ██  ██ ", "   ████  "],
    "W": [" ██      ██", " ██  ██  ██", " ██ ████ ██", " ██ ████ ██", " ██      ██"],
    "X": [" ██    ██", "  ██  ██  ", "   ████   ", "  ██  ██  ", " ██    ██"],
    "Y": [" ██    ██", "  ██  ██  ", "   ████   ", "    ██    ", "    ██    "],
    "Z": [" ████████", "    ██    ", "   ██     ", "  ██      ", " ████████"],
    "0": ["  █████  ", " ██   ██ ", " ██   ██ ", " ██   ██ ", "  █████  "],
    "1": ["   ███   ", "    █    ", "    █    ", "    █    ", " ███████ "],
    "2": [" ███████ ", "      ██ ", "  ██████ ", " ██      ", " ████████"],
    "3": [" ███████ ", "      ██ ", "   █████ ", "      ██ ", " ███████ "],
    "4": ["    ██   ", "   ████  ", "  ██ ██  ", " ██  ██  ", "      ██ "],
    "5": [" ███████ ", " ██      ", " ██████  ", "      ██ ", " ███████ "],
    "6": ["  █████  ", " ██      ", " ██████  ", " ██   ██ ", "  █████  "],
    "7": [" ████████", "      ██ ", "     ██  ", "    ██   ", "    ██   "],
    "8": ["  █████  ", " ██   ██ ", "  █████  ", " ██   ██ ", "  █████  "],
    "9": ["  █████  ", " ██   ██ ", "  ██████ ", "      ██ ", "  █████  "],
    " ": ["   ", "   ", "   ", "   ", "   "],
    "-": ["   ", "   ", "███", "   ", "   "],
    "_": ["   ", "   ", "   ", "   ", "███"],
    ".": ["   ", "   ", "   ", "   ", " █ "],
    ":": ["   ", " █ ", "   ", " █ ", "   "],
    "/": ["    █", "   █ ", "  █  ", " █   ", "█    "],
}


def figlet(text):
    lines = [""] * 5
    for ch in text.upper():
        glyph = _FONT.get(ch, _FONT[" "])
        for i in range(5):
            lines[i] += glyph[i] + "  "
    lines = [l.rstrip() for l in lines]
    return "\n".join(lines)


# figlet 大字的显示宽度（用于判断终端够不够）
def figlet_width(text):
    return max((len(line) for line in figlet(text).split("\n")), default=0)


# ═══════════════════════════════════════════════════════════════════
# 4. 服务端横幅 — 完整组装 + 终端自适应
# ═══════════════════════════════════════════════════════════════════

MIN_WIDTH_FOR_LAYOUT = 40   # 小于这个就极简模式


def _pick_title(width):
    """
    根据终端宽度选标题文本 + 是否用 figlet。
    四档自适应（用户指定的！）：
      ≥ 118  → figlet "DEEPHUB MAX"   (大字模式，117 cols)
      ≥  77  → figlet "DEEPHUB"       (中大字， 76 cols)
      ≥  62  → figlet "DH MAX"        (窄大字， 61 cols)
      ≥  40  → 纯文字  "DH MAX"
      <  40  → 纯文字  "DH"
    """
    if width >= 118:
        return "DEEPHUB MAX", True
    elif width >= 77:
        return "DEEPHUB", True
    elif width >= 62:
        return "DH MAX", True
    elif width >= 40:
        return "DH MAX", False
    else:
        return "DH", False


def build_banner(host, port, workdir, token_enabled, os_info, version="3.0", tools=None):
    """
    组装启动横幅 — 模仿参考截图风格，**全部彩虹字**：
      ┌──────────────────────┐
      │  [figlet 大字标题]    │
      │  ─ ─ ─ ─ ─ ─ 虚线    │
      │  简介                │
      │  插件列表: ...       │
      │  运行状况: ...       │
      │         │  ← 小 logo │
      └──────────────────────┘
    """
    width = _detect_width()
    title_text, use_figlet = _pick_title(width)

    # ── 虚线分隔（参考截图的短横间隙风格）────────────────
    dashed = "─ " * (width // 2)
    dashed = dashed.strip().ljust(width)[:width]
    rainbow_dash = lolcat_line(dashed, freq=0.04, offset=0.5)

    parts = []

    # ① 大字标题（全部彩虹）
    if use_figlet:
        parts.append(figlet_rainbow(title_text, freq=0.08))
    else:
        parts.append(lolcat_line(title_text.center(width), freq=0.08, offset=0.2, bold=True))

    # ② 虚线分隔（彩虹）
    parts.append(rainbow_dash)
    parts.append("")

    # ③ 简介（彩虹粗体）
    subtitle = f"  {version}  Agent Runtime for LLM"
    parts.append(ansi_truncate(lolcat_line(subtitle, freq=0.10, offset=0.3, bold=True), width))
    parts.append("")

    # ④ 插件列表（显示真实注册的工具）
    if tools:
        tool_names = [t.name for t in tools.values()] if hasattr(tools, "values") else list(tools)
        n = len(tool_names)
        plugins_title = f"  工具 [{n}]"
        parts.append(lolcat_line(plugins_title, freq=0.08, offset=0.1, bold=True))
        # 每行最多放多少个名字（按宽度估算，每个 name ≈ 8 字 + 空格）
        per_row = max(4, width // 12)
        rows = []
        for i in range(0, n, per_row):
            rows.append("    " + "  ".join(tool_names[i:i+per_row]))
        for row in rows[:6]:  # 最多 6 行，防止刷屏
            parts.append(ansi_truncate(lolcat_line(row, freq=0.08, offset=0.25), width))
        if n > 6 * per_row:
            parts.append(ansi_truncate(lolcat_line(f"    … 共 {n} 个", freq=0.08, offset=0.25), width))
    else:
        parts.append(lolcat_line("  工具 [0]", freq=0.08, offset=0.1, bold=True))
        parts.append(lolcat_line("    （无）", freq=0.08, offset=0.25))
    parts.append("")

    # ⑤ 运行状况（彩虹）
    token_icon = "●" if token_enabled else "○"
    run_line = f"  运行状况: http://{host}:{port} token={token_icon} {os_info}"
    parts.append(ansi_truncate(lolcat_line(run_line, freq=0.08, offset=0.45, bold=True), width))
    short_workdir = shorten_path(str(workdir), max_len=max(10, width - 14))
    parts.append(ansi_truncate(lolcat_line(f"    workdir: {short_workdir}", freq=0.08, offset=0.55), width))

    parts.append("")

    # ⑥ 底部小 logo + 提示（参考截图右下角装饰）
    tip_raw = "Ctrl+C 停止  ·  /api/chat /api/tools /api/health"
    tip = lolcat_line(tip_raw, freq=0.05, offset=0.6)
    parts.append(ansi_truncate(tip, width))

    # 最底部那条短 logo 竖线（参考截图右下角装饰）
    parts.append("")
    logo = "│".center(width // 4).ljust(width)
    parts.append(lolcat_line(logo, freq=0.03, offset=0.7))

    return "\n".join(parts)


def figlet_rainbow(text, freq=0.10):
    """figlet 大字 + 彩虹（用 lolcat_block，第一行粗体）"""
    art = figlet(text)
    return lolcat_block(art, freq=freq, bold_first_line=True)


# ═══════════════════════════════════════════════════════════════════
# 5. 快速测试
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    w = _detect_width()
    print(f"(终端宽度 {w} 列)", file=sys.stderr)
    print(build_banner("0.0.0.0", 8765, "/workspace", True, sys.platform))
