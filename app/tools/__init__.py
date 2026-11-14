from .base import (
    Tool, ToolResult, Command, PERM_LEVEL, PERM_NAME,
    REGISTRY, COMMAND_REGISTRY, register, register_command,
)

# Tool 注册表别名（保持向后兼容）
from .base import COMMAND_REGISTRY  # noqa: F401 — 显式 re-export

# ─── 第一批：内置 + 文件 + Shell + 浏览器 + Web ───
from . import builtin, files, shell, tabbit, web
builtin.register_all()
files.register_all()
shell.register_all()
tabbit.register_all()
web.register_all()

# ─── 第二批：搜索 / 编辑 / Git / 等待 ───
from . import grep, edit, search, git_tools, wait_tool
grep.register_all()
edit.register_all()
search.register_all()
git_tools.register_all()
wait_tool.register_all()

# ─── 第三批：高级 Agent 能力 ───
from . import range_read, sysinfo, terminal, pyeval
range_read.register_all()
sysinfo.register_all()
terminal.register_all()
pyeval.register_all()

# ─── 第四批：补丁 / 端口 / HTTP 预览 / 配置 ───
from . import patch, port, httpserve, env_tools
patch.register_all()
port.register_all()
httpserve.register_all()
env_tools.register_all()

# ─── 第五批：Windows 桌面 UI 自动化（pywinauto） ───
from . import uia
uia.register_all()

# ─── 第六批：AI 自举插件系统（AI 可以写新插件） ───
from . import plugin
plugin.register_all()

# ─── 启动时自动扫描 plugins/ 目录下 AI 生成的插件 ───
plugin.auto_discover()
