# DeepHub MAX

> **轻量级 AI Agent 执行框架 · 本地优先 · 插件可扩展**
> 一个 ReAct 循环的极简实现：**用户提问 → AI 思考 → 输出工具调用 → 执行 → 结果回传 → 继续思考 → 任务完成**。
>
> - 🌐 **浏览器 SPA**：原生 ES Modules + SSE，打开即用
> - 💻 **命令行 REPL**：Tab 补全 + Minecraft 风格指令循环 + `/ai` 命令行版 Agent
> - 🧩 **双轨插件体系**：Tool（AI 调用）+ Command（REPL 斜杠指令），插件可同时注册
> - 🛡️ **信任弹窗**：导入插件前 AST 扫描副作用 + GUI/CLI 双模式确认（默认拒绝）
> - 🎨 **自适应彩虹横幅**：figlet 大字 + HS224 彩虹 + 5 档终端宽度自适应

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" />
  <img src="https://img.shields.io/badge/Flask-3.x-black.svg" />
  <img src="https://img.shields.io/badge/Docker-ready-blue.svg" />
  <img src="https://img.shields.io/badge/License-MIT-green.svg" />
  <img src="https://img.shields.io/badge/Tools-45-orange.svg" />
</p>

---

## 📋 目录

- [快速开始](#-快速开始)
- [功能一览](#-功能一览)
- [REPL 指令行](#-repl-指令行)
- [插件开发](#-插件开发)
- [内置工具清单](#-内置工具清单-45-个)
- [架构](#-架构)
- [安全设计](#-安全设计)
- [API 端点](#-api-端点)

---

## 🚀 快速开始

### 方式一：Docker（推荐）

```bash
docker compose up -d
# http://localhost:8765
```

### 方式二：本地运行

```bash
python -m venv .venv && .\.venv\Scripts\Activate.ps1   # Windows
pip install -r requirements.txt
python -m app.server
# http://localhost:8765
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AIH_API_URL` | 空 | LLM API 地址（REPL `/ai` 需要） |
| `AIH_API_KEY` | 空 | LLM API Key |
| `AIH_MODEL` | 空 | 模型名 |
| `AIH_HOST` | `0.0.0.0` | 监听地址 |
| `AIH_PORT` | `8765` | 监听端口 |
| `AIH_WORKDIR` | `os.getcwd()` | 工作目录（文件工具被限制在此目录内） |
| `AIH_TOKEN` | 空 | API 认证 Token（设置后所有 `/api/*` 需 `Authorization: Bearer`） |
| `TABBIT_CLI` | 自动查找 | Tabbit 浏览器 CLI 路径 |

### 启动终端横幅

```
 ████████    ████████   ████████   ███████    ██    ██   ██    ██   ████████
 ██    ██    ██         ██         ██    ██   ██    ██   ██    ██   ██    ██
 ██    ██    ███████    ███████    ███████    ████████   ██    ██   ████████
 ██    ██    ██         ██         ██         ██    ██   ██    ██   ██    ██
 ████████    ████████   ████████   ██         ██    ██    █████     ████████
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─

  3.0  Agent Runtime for LLM

  工具 [45]
    ask_user  browser_open  browser_read  browser_tabs  code_edit  env_get  env_set
    file_append  file_delete  file_exists  file_list  file_mkdir  file_move  file_patch
    ...

  运行状况: http://0.0.0.0:8765  token=●  win32
    workdir: D:\ai-harness

  Ctrl+C 停止  ·  /api/chat /api/tools /api/health

         │

💬 AI Harness 指令模式  ·  45 个工具就绪
  Tab 补全 ✅  单 Tab 补全  双 Tab 列候选
  Ctrl+C 或 /quit 退出 REPL（Flask 继续运行）

>>
```

横幅自适应 5 档终端宽度（≥118 / ≥77 / ≥62 / ≥40 / <40），永远不溢出。

---

## ✨ 功能一览

| 能力 | 说明 |
|------|------|
| 🔄 **多轮自动执行** | ReAct 循环，最多 20 轮直到任务完成 |
| 💭 **思考过程可见** | `<think>` 标签自动提取，折叠展示 AI 推理 |
| ⚡ **流式 SSE 输出** | token 级别实时渲染到浏览器 |
| 🧩 **45 内置工具** | 文件 / Shell / 浏览器 / Git / 终端 / 代码 / Python / UI 自动化 |
| 🖥️ **命令行 REPL** | Tab 补全 + Minecraft 风格循环切换 + `/ai` 命令行版 Agent |
| 🔌 **插件双轨扩展** | Tool（AI 调用）+ Command（REPL 斜杠指令），插件可同时注册 |
| 🔐 **三级权限模型** | Visitor(0) / User(1) / Root(2)，Sandbox 模式自动锁死 |
| 🛡️ **插件信任确认** | AST 预扫副作用 + GUI messagebox / CLI y/N（默认拒绝） |
| 🎨 **自适应彩虹横幅** | figlet 大字 + HS224 24-bit ANSI 彩虹 + 5 档宽度 |
| 🐳 **Docker 多阶段** | `read_only:true` + `cap_drop: ALL` + tmpfs + 健康检查 |
| 🎨 **纯原生前端** | ES Modules，无 React/Vue，打开即用 |
| 📝 **富文本渲染** | Markdown + 代码高亮 + KaTeX 公式 + Mermaid |
| 🖼️ **Windows UI 自动化** | 纯 ctypes 实现，零 pywin32 依赖 |

---

## 💻 REPL 指令行

启动后自动进入 REPL 模式（daemon 线程，不阻塞 Flask）。

### 指令清单

```
可用指令：
  /help                       显示这个帮助
  /ai <消息>                  让 AI 执行任务（Agent 模式）
  /addplugin [name]           弹出文件选择框导入 .py 插件
  /removeplugin <name>        直接删除插件文件
  /reload [name | all]        热重载插件（不指定=全部）
  /list                       列出所有插件文件
  /tools                      列出所有已注册工具
  /quit  (或 Ctrl+C)          退出 REPL（Flask 继续跑）

AI 配置（/ai 需要）：
  export AIH_API_URL=https://.../v1
  export AIH_API_KEY=sk-...
  export AIH_MODEL=gpt-4o
```

### Tab 补全（Minecraft 风格）

| 输入 | 单 Tab | 连续 Tab |
|------|--------|----------|
| `/h` | `/help` 自动补全 | （唯一匹配） |
| `/r` | → `/removeplugin` | 再次 Tab → `/reload` 循环切换 |
| 空开头 | → 工具名循环（git_* / file_* / run_* ...） | 同左 |
| `/reload ` | → 插件名 / `all` | 循环切换 |

### `/ai` 命令行版 Agent

```
>> /ai 帮我创建 hello.py 然后运行它

🤖  AI [gpt-4o]: 帮我创建 hello.py 然后运行它
  ↻ 第 1/20 轮
  🔧 调用 file_write {'path': 'hello.py', 'content': 'print("hello")'}
     ✅ 已写入
  ↻ 第 2/20 轮
  🔧 调用 run_cmd {'command': 'python hello.py'}
     ✅ hello
📊 本轮调用了 2 个工具
```

### 插件也能注册斜杠指令

```python
# plugins/my_plugin.py
register_command(Command(
    name="email",                        # 用户打 /email 参数
    help="发送邮件 /email <目标>",
    handler=_cmd_email,
))
```

插件指令自动出现在 Tab 补全里、`/help` 里、`_resolve_handler` 分发表里。

---

## 🧩 插件开发

### 插件文件结构

```python
# plugins/my_plugin.py
from ..base import Tool, ToolResult, Command
from .. import register, register_command

# ═══════ Tool：AI Agent 可调用 ═══════
def _send_email(args, ctx):
    """Tool handler 签名：handler(args: dict, ctx: dict) → ToolResult"""
    to = args.get("to", "")
    subject = args.get("subject", "")
    return ToolResult(text=f"📧 邮件已发送到 {to}")

# ═══════ Command：REPL 里的 /斜杠指令 ═══════
def _cmd_email(arg):
    """Command handler 签名：handler(arg: str) → None"""
    # arg 是 /email 后面的所有文本
    print(f"📧 发送邮件: {arg}", file=sys.__stdout__)

def register_all():
    # 同时注册 Tool 和 Command —— 插件可以只注册一个，也可以都注册
    register(Tool(
        name="send_email",
        title="发送邮件",
        desc="通过 SMTP 发送邮件",
        usage='{"to":"user@example.com","subject":"Hello"}',
        required={"to": "string"},
        perm="Root",
        handler=_send_email,
    ))
    register_command(Command(
        name="email",
        help="发送邮件 /email <目标邮箱>",
        handler=_cmd_email,
    ))
```

### 加载机制

```
AIH AI 创建插件 → AST 安全扫描（block subprocess/exec/eval/import）
                  → _rewrite_imports 自动修 from .base → from ..base
                  → 落盘到 app/tools/plugins/my_plugin.py
                  → exec() + sys.modules 注入 + __package__ 修复
                  → register_all() 自动把 Tool + Command 都注册进去

手动导入插件 → /addplugin（GUI 文件选择框） 或 /addplugin <name>（CLI 粘贴）
                  → AST 副作用扫描（Tool/Command 数量 + 风险关键词）
                  → 信任弹窗（GUI messagebox 默认 NO / CLI y/N 默认 N）
                  → 通过后才加载
```

### 信任弹窗内容（GUI messagebox）

```
┌─────────────────────────────────────────────┐
│ 🔐 信任新插件？                              │
├─────────────────────────────────────────────┤
│ 插件文件：malicious.py                       │
│ 将注册：1 个工具 + 2 个斜杠指令              │
│ ⚠️  检测到可能风险：subprocess, token        │
│                                             │
│ 此插件将加载到 DeepHub MAX，可能：           │
│   • 访问本地文件 / 执行系统命令              │
│   • 发起网络请求                             │
│   • 向 AI Agent 注册新能力                   │
│                                             │
│ 只信任来自可信来源的插件。                    │
│ 是否继续加载此插件？        [否]  [是]        │
└─────────────────────────────────────────────┘
```

---

## 🛠️ 内置工具清单（45 个）

### 📂 文件系统

| 工具 | 说明 |
|------|------|
| `file_read` | 读取文本文件（2MB 限制） |
| `file_write` | 覆盖写入，自动建父目录 |
| `file_append` | 追加到文件末尾 |
| `file_list` | 列出目录 |
| `file_exists` | 判断路径存在 |
| `file_mkdir` | 递归创建目录 |
| `file_move` | 移动 / 重命名 |
| `file_delete` | 删除（需 confirm:true） |
| `file_patch` | 类 git apply 补丁 |
| `read_file_range` | 按行号范围读取 |
| `code_edit` | 类 VS Code 精确编辑 |

### 💻 Shell / 终端

| 工具 | 说明 |
|------|------|
| `run_cmd` | Windows cmd.exe 命令 |
| `run_powershell` | PowerShell 命令 |
| `terminal_run` | 持久终端会话（多行） |
| `terminal_stop` | 停止终端 |
| `terminal_list` | 列出活跃终端 |
| `python_eval` | Python 代码执行 |

### 🌐 网络 / 浏览器

| 工具 | 说明 |
|------|------|
| `web_fetch` | HTTP 请求（SSR 防护 + UA 伪装） |
| `web_search` | 搜索引擎 |
| `browser_tabs` | 列出浏览器标签 |
| `browser_read` | 读取网页正文 |
| `browser_open` | 打开并读取 |
| `http_serve` | 起临时 HTTP 服务器 |

### 📊 Git

| 工具 | 说明 |
|------|------|
| `git_status` | git status |
| `git_diff` | git diff |
| `git_log` | git log |
| `git_commit` | git commit |

### 🖼️ Windows UI 自动化（纯 ctypes，零 pywin32）

| 工具 | 说明 |
|------|------|
| `uia_action` | UI 自动化动作 |
| `uia_find` | 查找 UI 元素 |
| `uia_list` | 列出窗口 |

### 🔎 搜索 / 开发辅助

| 工具 | 说明 |
|------|------|
| `grep_search` | 内容搜索 |
| `port_check` | 端口占用检查 |
| `wait` | 延时等待 |
| `sys_info` | 系统信息 |
| `env_get` / `env_set` | 环境变量 |

### 🧩 插件管理（Agent 可动态增删）

| 工具 | 说明 |
|------|------|
| `plugin_create` | 让 AI 写 .py 插件并落盘 |
| `plugin_reload` | 热重载插件 |
| `plugin_list` | 列出已安装插件 |

### 🎨 内置交互

| 工具 | 说明 |
|------|------|
| `get_time` | 服务器当前时间 |
| `list_tools` | 列出 AI 当前可用工具 |
| `ask_user` | 交互式提问（暂停等待回答） |
| `show_note` | Markdown 卡片 |
| `show_steps` | 多步骤清单 |
| `task_complete` | 结束执行循环 |

---

## 🏗️ 架构

```
┌──────────────────────────────────────────────────────────────┐
│                        浏览器 SPA / REPL                      │
│  index.html + ES6 Modules     │   app/cli.py (daemon 线程)    │
│  SSE fetch / fetch()          │   readline + Tab 补全         │
└────────────────────────────┬─┴───────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────┐
│                  Flask Server (:8765)                          │
│  /api/chat · /api/tools · /api/models · /api/plugin/*          │
│  before_request: AIH_TOKEN 校验                                │
│  redirect_stdout/stderr: Flask 全部静默                        │
└────────────────────────────┬──────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────┐
│                     Agent Loop 引擎                            │
│                                                               │
│  prompt.py ──► llm.py (stream) ──► parser.py (XML + Think)      │
│       │                                │                       │
│       ▼                                ▼                       │
│  工作区快照                        REGISTRY / COMMAND_REGISTRY  │
│  工具列表注入                              │                   │
│  权限过滤                              Tool 调用链             │
│                                        │                       │
│                                    ┌───┴───┐                   │
│                                    │ 安全   │ AST 扫描          │
│                                    │ 校验   │ 信任确认          │
│                                    └───┬───┘                   │
│                                        │                       │
│                           app/tools/plugins/*.py               │
└───────────────────────────────────────────────────────────────┘
```

### 目录结构

```
deephub-max/
├── Dockerfile                   # 多阶段（builder + runtime）
├── docker-compose.yml           # 编排（read_only + tmpfs + 健康检查）
├── .dockerignore
├── .env.example
├── requirements.txt             # flask + requests + pyreadline3(Windows)
├── README.md
│
└── app/
    ├── __init__.py
    ├── agent.py                 # 🔄 Agent 核心循环（ReAct）
    ├── art.py                   # 🎨 彩虹横幅 + figlet 大字 + 自适应宽度
    ├── cli.py                   # 💻 REPL 指令行 + Tab 补全 + 信任弹窗
    ├── config.py                # 环境变量配置
    ├── llm.py                   # LLM API 流式调用
    ├── parser.py                # XML 工具标签 + Think 标签解析器
    ├── prompt.py                # System Prompt 构造
    ├── server.py                # Flask HTTP + SSE 端点
    ├── sessions.py              # 会话管理
    │
    ├── static/                  # 前端（无构建工具）
    │   ├── index.html
    │   ├── style.css
    │   ├── tabbit.js
    │   └── js/
    │       ├── app.js           # SSE 事件处理 + 渲染
    │       ├── state.js         # 状态 + localStorage
    │       ├── ui.js            # DOM 组件工厂
    │       ├── markdown.js      # Markdown + 代码高亮 + KaTeX + Mermaid
    │       ├── utils.js
    │       └── plugins.js
    │
    └── tools/                   # 插件工具层（可扩展）
        ├── base.py              # ⭐ Tool / ToolResult / Command 基类 + 注册
        ├── __init__.py          # REGISTRY + COMMAND_REGISTRY
        │
        ├── plugin.py            # 🔐 AI 自举插件系统（安全扫描 + 加载）
        │   └── plugins/         # AI 动态创建的 .py 插件
        │
        ├── files.py             # 文件工具（11 个）
        ├── shell.py             # Shell 工具
        ├── tabbit.py            # 浏览器工具
        ├── web.py               # HTTP 工具
        ├── git_tools.py         # Git 工具
        ├── terminal.py          # 持久终端会话
        ├── uia.py               # Windows UI 自动化（纯 ctypes）
        ├── python_eval.py       # Python 执行
        ├── search.py / grep.py  # 搜索
        ├── builtin.py           # 内置交互工具
        ├── ...                  # 其他
```

---

## 🛡️ 安全设计

| 风险 | 防护措施 |
|------|----------|
| 路径穿越 | `Path.resolve()` + `relative_to(WORKDIR)` 强制约束 |
| SSRF 攻击 | `_is_safe_url()` 禁止内网 IP / localhost |
| 误删 | `file_delete` 需 `confirm:true`，目录还需 `recursive:true` |
| 高危命令 | `run_cmd` / `run_powershell` 归为 Root 权限 |
| LLM 幻觉 | System Prompt 强制 XML 格式，禁止 JSON / 空参数 |
| 死循环 | `MAX_ROUNDS = 20` 硬上限 |
| 插件注入 | AST 扫描 `subprocess`/`exec`/`eval`/`__import__` + 黑名单拦截 |
| 插件信任 | GUI messagebox askyesno（default=no）+ CLI y/N（默认 N） |
| 插件持久化 | 自动修正 `from .base` → `from ..base`，注入 `__package__` |
| Docker 风险 | `read_only:true` + `cap_drop: ALL` + tmpfs `/tmp` + 非 root 用户 + pids_limit + mem_limit |
| API 暴露 | `AIH_TOKEN` 设置后所有 `/api/*` 强制 Bearer 认证 |

### 三级权限

```python
PERM_LEVEL = {"Visitor": 0, "User": 1, "Root": 2}
```

| 级别 | 能力 | 对应工具示例 |
|------|------|-------------|
| **Visitor** | 只读查看 | `file_read` `web_fetch` `get_time` `ask_user` |
| **User** | 工作区内修改 | `file_write` `file_append` `file_mkdir` `file_move` |
| **Root** | 完全权限 | `run_cmd` `file_delete` `browser_open` `plugin_create` |

---

## 🔌 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查（始终开放） |
| GET | `/api/tools` | 列出所有已注册工具 spec |
| POST | `/api/models` | 发现可用模型列表 |
| POST | `/api/chat` | 核心端点，SSE 流式 Agent 循环 |
| POST | `/api/save_file` | 保存代码块到工作区 |
| POST | `/api/ask/<aid>` | 回答 `ask_user` 交互式提问 |
| POST | `/api/plugin/exec` | 前端插件执行 Shell |
| POST | `/api/plugin/file` | 前端插件文件操作 |
| POST | `/api/plugin/tabbit` | 前端插件浏览器操作 |

---

## 📝 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11+ / Flask 3.x |
| Agent | 自研 ReAct + XML 工具标签协议 |
| REPL | readline / pyreadline3 |
| 前端 | 原生 ES Modules + marked.js + DOMPurify + highlight.js + KaTeX + Mermaid |
| 部署 | Docker / Docker Compose |
| Windows 特有 | 纯 ctypes UI 自动化（零 pywin32 依赖） |

---

## 📄 License

MIT © DeepHub MAX Team
