"""
Windows 桌面 UI 自动化插件（纯 ctypes + Win32 API，零 pywin32 依赖）
-------------------------------------------------------------------
pywin32 在 Python 3.14 上 DLL 加载失败，所以直接调用 Win32 API。

3 个工具，一个模块：
  uia_list   — 列出桌面上所有顶层窗口的子控件
  uia_find   — 按标题/类名搜索控件
  uia_action — click / double_click / right_click / long_click /
               set_text / get_text / get_rect / minimize / maximize / close / focus

权限：list / find → Visitor；action → Root

⚠️ 非 Windows 环境：工具会注册但调用时返回清晰的降级提示，不 crash。
"""

import sys
import time

from .base import Tool, ToolResult
from . import register

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wt
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
else:
    user32 = None
    EnumWindowsProc = EnumChildProc = None


def _ensure_windows() -> ToolResult | None:
    """非 Windows 环境下调用时返回友好提示，Windows 下返回 None 继续"""
    if not _IS_WINDOWS or user32 is None:
        return ToolResult(text=(
            "❌ uia_* 工具仅在 Windows 系统上可用（需要 Win32 API）。\n"
            "在 Docker / Linux / macOS 容器里，你可以用：\n"
            "  • run_cmd（Shell 命令）\n"
            "  • terminal_run（启动后台进程）\n"
            "  • web_fetch + browser_open（浏览器自动化）\n"
            "等跨平台工具替代。"
        ))
    return None


def _get_all_top_windows() -> list[int]:
    """返回所有可见、有标题的顶层窗口句柄列表"""
    handles = []

    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            # 排除 message-only window（HWND_MESSAGE）
            if user32.GetParent(hwnd) == 0:
                handles.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return handles


def _get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or ""


def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value or ""


def _get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def _is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


def _get_all_children(parent: int) -> list[int]:
    """递归枚举 parent 的所有直接子窗口句柄"""
    handles = []

    def _cb(hwnd, _lparam):
        handles.append(hwnd)
        # 递归孙子
        try:
            grandchildren = _get_all_children(hwnd)
            handles.extend(grandchildren)
        except Exception:
            pass
        return True

    user32.EnumChildWindows(parent, EnumChildProc(_cb), 0)
    return handles


# ─── 动作实现 ────────────────────────────────────────────────────

def _click_at(x: int, y: int, button: str = "left", times: int = 1):
    """在 (x,y) 坐标处点击"""
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_DOUBLECLICK = 0x0002  # 模拟双击就两次

    # 先把光标移过去
    # 用 SetCursorPos 比 mouse_event 的 move 更简单（mouse_event 需要绝对坐标转换）
    user32.SetCursorPos(x, y)
    time.sleep(0.02)

    if button == "left":
        dn = MOUSEEVENTF_LEFTDOWN
        up = MOUSEEVENTF_LEFTUP
    elif button == "right":
        dn = MOUSEEVENTF_RIGHTDOWN
        up = MOUSEEVENTF_RIGHTUP
    else:
        raise ValueError(f"未知鼠标按键：{button}")

    for _ in range(times):
        user32.mouse_event(dn, 0, 0, 0, None)
        time.sleep(0.02)
        user32.mouse_event(up, 0, 0, 0, None)
        time.sleep(0.02)


def _long_click_at(x: int, y: int, hold_ms: int):
    """长按"""
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    user32.SetCursorPos(x, y)
    time.sleep(0.02)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(hold_ms / 1000.0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)


def _send_text(hwnd: int, text: str):
    """向控件发送文本（WM_SETTEXT + WM_CHAR）"""
    WM_SETTEXT = 0x000C
    # 先清空
    user32.SendMessageW(hwnd, WM_SETTEXT, 0, "")
    # 逐字符发送
    WM_CHAR = 0x0102
    for ch in text:
        vk = ord(ch)
        user32.SendMessageW(hwnd, WM_CHAR, vk, 0)
        time.sleep(0.005)


def _send_enter(hwnd: int):
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    VK_RETURN = 0x0D
    user32.SendMessageW(hwnd, WM_KEYDOWN, VK_RETURN, 0)
    user32.SendMessageW(hwnd, WM_KEYUP, VK_RETURN, 0)


def _find_window_by_criteria(title: str = "", class_name: str = "",
                             automation_id: str = "", control_type: str = "") -> tuple[int, str]:
    """
    按条件定位一个窗口控件。先匹配顶层窗口，再递归子窗口。
    返回 (hwnd, description)。找不到抛 RuntimeError。
    """
    top_wins = _get_all_top_windows()
    for top_hwnd in top_wins:
        # 先看顶层窗口本身
        top_text = _get_window_text(top_hwnd)
        top_cls = _get_class_name(top_hwnd)

        # 顶层窗口匹配
        top_match = True
        if title and title.lower() not in top_text.lower():
            top_match = False
        if class_name and class_name.lower() not in top_cls.lower():
            top_match = False

        if top_match:
            if not automation_id and not control_type:
                return top_hwnd, f"顶层窗口: {top_text} [class={top_cls}]"

        # 递归子窗口匹配
        children = _get_all_children(top_hwnd)
        for hwnd in children:
            try:
                c_text = _get_window_text(hwnd)
                c_cls = _get_class_name(hwnd)
            except Exception:
                continue

            match = True
            if title and title.lower() not in c_text.lower():
                match = False
            if class_name and class_name.lower() not in c_cls.lower():
                match = False
            if automation_id:
                # Win32 没 AutomationId 概念，跳过
                pass

            if match:
                return hwnd, f"子控件: '{c_text}' [class={c_cls}] 所属窗口='{top_text}'"

    raise RuntimeError(
        f"找不到匹配控件。条件：title='{title}', class_name='{class_name}'。\n"
        f"提示：用 uia_list 先看看桌面上都有什么窗口和子控件。"
    )


# ─── uia_list ──────────────────────────────────────────────────

def _list_all_windows(args, ctx):
    """列出桌面顶层窗口 + 子控件"""
    guard = _ensure_windows()
    if guard:
        return guard
    show_hidden = bool(args.get("show_hidden", False))
    max_windows = int(args.get("max_windows") or 15)
    max_depth = int(args.get("max_depth") or 2)

    top_wins = _get_all_top_windows()
    visible = []
    for hwnd in top_wins:
        try:
            text = _get_window_text(hwnd)
            if not text:
                continue
            if not show_hidden and _is_minimized(hwnd):
                continue
            visible.append((text, hwnd))
        except Exception:
            continue

    visible.sort(key=lambda x: x[0])
    visible = visible[:max_windows]

    if not visible:
        return ToolResult(text="📭 没有可见的顶层窗口。\n（可以设 show_hidden=true 包含隐藏/最小化窗口）")

    lines = [f"🖥️ 桌面窗口（{len(visible)} 个）", "=" * 40]

    for title, hwnd in visible:
        try:
            l, t, w, h = _get_window_rect(hwnd)
            cls = _get_class_name(hwnd)
        except Exception:
            continue

        lines.append(f"\n📁 **{title}**  class=`{cls}`  ({l},{t}) {w}x{h}")

        if max_depth >= 1:
            children = _get_all_children(hwnd)
            for child_hwnd in children[:max_depth * 30]:  # 限每个窗口最多列 60 个子控件
                try:
                    c_text = _get_window_text(child_hwnd)
                    c_cls = _get_class_name(child_hwnd)
                    c_l, c_t, c_w, c_h = _get_window_rect(child_hwnd)
                    if not c_text and c_w == 0 and c_h == 0:
                        continue  # 跳过不可见/零尺寸
                    lines.append(f"  ○ {c_cls} '{c_text[:50]}'  ({c_l},{c_t}) {c_w}x{c_h}")
                except Exception:
                    continue

    result = "\n".join(lines)
    if len(result) > 20000:
        result = result[:20000] + "\n\n... (输出过长，建议用 uia_find 精准搜索)"
    return ToolResult(text=result)


# ─── uia_find ──────────────────────────────────────────────────

def _find_ctrl(args, ctx):
    """按条件搜索控件，列出所有匹配"""
    guard = _ensure_windows()
    if guard:
        return guard
    keyword = args.get("keyword") or args.get("text") or ""
    by_title = args.get("title") or keyword
    by_class = args.get("class_name") or args.get("class") or ""
    max_results = int(args.get("max_results") or 30)

    if not (by_title or by_class):
        raise ValueError("至少提供一个过滤条件：keyword / title / class_name")

    top_wins = _get_all_top_windows()
    found = []

    def _add_if_match(hwnd, owner_window):
        try:
            text = _get_window_text(hwnd)
            cls = _get_class_name(hwnd)
            l, t, w, h = _get_window_rect(hwnd)
        except Exception:
            return

        if by_title and by_title.lower() not in text.lower():
            return
        if by_class and by_class.lower() not in cls.lower():
            return
        if not text and not by_class:
            return

        found.append({
            "hwnd": hwnd, "text": text[:80], "class": cls,
            "pos": (l, t, w, h), "window": owner_window,
        })

    for top_hwnd in top_wins:
        top_text = _get_window_text(top_hwnd)
        _add_if_match(top_hwnd, top_text)

        children = _get_all_children(top_hwnd)
        for ch in children:
            if len(found) >= max_results:
                break
            _add_if_match(ch, top_text)
        if len(found) >= max_results:
            break

    if not found:
        criteria = []
        if by_title: criteria.append(f"text='{by_title}'")
        if by_class: criteria.append(f"class='{by_class}'")
        return ToolResult(text=f"🔍 未找到匹配控件（条件：{', '.join(criteria)}）")

    lines = [f"🔍 找到 {len(found)} 个匹配控件：", "---"]
    for i, c in enumerate(found, 1):
        lines.append(f"{i}. **{c['class']}** `{c['text'] or '(无文本)'}`")
        lines.append(f"   位置: ({c['pos'][0]},{c['pos'][1]}) {c['pos'][2]}x{c['pos'][3]}")
        lines.append(f"   所属窗口: `{c['window']}`")
        lines.append(f"   定位用：```json\n{{\"title\":\"{c['text'][:20].replace(chr(34),chr(39))}\"}}\n```")

    return ToolResult(text="\n".join(lines))


# ─── uia_action ────────────────────────────────────────────────

def _action(args, ctx):
    guard = _ensure_windows()
    if guard:
        return guard
    action = (args.get("action") or args.get("op") or "").strip().lower()
    if not action:
        raise ValueError("必须提供 action 参数")

    title = args.get("title") or args.get("keyword") or ""
    class_name = args.get("class_name") or args.get("class") or ""
    if not title and not class_name:
        raise ValueError("至少提供 title 或 class_name 来定位控件")

    # 先聚焦窗口（SetForegroundWindow）
    try:
        hwnd, desc = _find_window_by_criteria(title=title, class_name=class_name)
    except RuntimeError as e:
        return ToolResult(text=f"❌ {e}")

    # 把所属窗口拉到前台
    try:
        # 找顶级窗口（往上回溯）
        root = hwnd
        while True:
            parent = user32.GetAncestor(root, 2)  # GA_ROOT
            if parent:
                root = parent
            else:
                break
        user32.ShowWindow(root, 9)  # SW_RESTORE
        user32.SetForegroundWindow(root)
        time.sleep(0.1)
    except Exception:
        pass

    try:
        l, t, w, h = _get_window_rect(hwnd)
        cx, cy = l + w // 2, t + h // 2
    except Exception:
        cx, cy = 500, 300

    try:
        if action in ("click", "single_click"):
            _click_at(cx, cy, "left", 1)
            return ToolResult(text=f"✅ 已点击：{desc}")

        elif action in ("double_click", "dblclick"):
            _click_at(cx, cy, "left", 2)
            return ToolResult(text=f"✅ 已双击：{desc}")

        elif action in ("right_click", "context_click"):
            _click_at(cx, cy, "right", 1)
            return ToolResult(text=f"✅ 已右键点击：{desc}")

        elif action in ("long_click", "hold"):
            hold_ms = int(args.get("hold_ms") or 800)
            _long_click_at(cx, cy, hold_ms)
            return ToolResult(text=f"✅ 已长按 {hold_ms}ms：{desc}")

        elif action in ("set_text", "type"):
            new_text = args.get("text") or args.get("value") or ""
            if not new_text:
                raise ValueError("set_text 需要 text 参数")
            _send_text(hwnd, new_text)
            if args.get("press_enter", False):
                _send_enter(hwnd)
            return ToolResult(text=f"✅ 已设置文本：`{new_text[:80]}`")

        elif action == "get_text":
            text = _get_window_text(hwnd)
            return ToolResult(text=f"📄 控件文本：\n```\n{text}\n```")

        elif action in ("get_rect", "get_position"):
            l, t, w, h = _get_window_rect(hwnd)
            return ToolResult(text=f"📍 控件位置：({l},{t})  {w}x{h}")

        elif action == "minimize":
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return ToolResult(text=f"⬇️ 已最小化：{desc}")

        elif action == "maximize":
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            return ToolResult(text=f"⬆️ 已最大化：{desc}")

        elif action == "close":
            WM_CLOSE = 0x0010
            user32.SendMessageW(hwnd, WM_CLOSE, 0, 0)
            return ToolResult(text=f"❌ 已关闭：{desc}")

        elif action in ("focus", "set_focus"):
            user32.SetFocus(hwnd)
            return ToolResult(text=f"🎯 已聚焦：{desc}")

        else:
            raise ValueError(
                f"未知 action：{action}。支持："
                f"click / double_click / right_click / long_click / "
                f"set_text / get_text / get_rect / minimize / maximize / close / focus"
            )

    except Exception as e:
        return ToolResult(text=f"❌ 动作执行失败：{type(e).__name__}: {e}")


# ─── 注册 ──────────────────────────────────────────────────────

def register_all():
    register(Tool(
        name="uia_list", title="列出桌面控件树", perm="Visitor",
        desc=(
            "列出桌面上所有顶层窗口及其子控件。"
            "显示窗口标题、Win32 类名、位置坐标。"
            "可用 max_windows / max_depth / show_hidden 控制范围。"
        ),
        usage='{"max_windows": 10, "max_depth": 2}',
        handler=_list_all_windows,
    ))

    register(Tool(
        name="uia_find", title="搜索桌面控件", perm="Visitor",
        desc=(
            "在所有窗口里搜索控件。"
            "支持按 title / class_name 模糊匹配，返回匹配位置和所属窗口。"
        ),
        usage='{"keyword":"保存","max_results":10}',
        handler=_find_ctrl,
    ))

    register(Tool(
        name="uia_action", title="操作桌面控件", perm="Root",
        desc=(
            "对指定控件执行桌面操作。先按 title / class_name 定位，然后执行："
            "click / double_click / right_click / long_click / "
            "set_text / get_text / get_rect / minimize / maximize / close / focus"
        ),
        usage='{"action":"click","title":"保存"}',
        required={"action": "string"}, handler=_action,
    ))
