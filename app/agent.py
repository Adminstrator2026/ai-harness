import json
from .llm import stream_chat
from .parser import ToolParser, ThinkParser
from .prompt import build_system_prompt
from .tools import REGISTRY, PERM_LEVEL, PERM_NAME
from .tools.base import ToolResult
from .config import CONFIG

def _validate_args(tool, args):
    for k, t in (tool.required or {}).items():
        if k not in args or args[k] is None:
            raise ValueError(f'你漏掉了必填参数 "{k}"！请重新输出完整指令。示范：<tool name="{tool.name}" args=\'{tool.usage}\'/>')
        v = args[k]
        if t == "string" and not isinstance(v, str):
            raise ValueError(f'参数 "{k}" 必须是字符串')
        if t == "array" and not isinstance(v, list):
            raise ValueError(f'参数 "{k}" 必须是数组')

def run_agent(cfg, messages, session):
    system_prompt = build_system_prompt(cfg)
    full_messages = [{"role": "system", "content": system_prompt}] + list(messages)

    enabled_list = cfg.get("enabled_tools")
    if enabled_list is None:
        enabled_list = list(REGISTRY.keys())

    tool_names = [n for n in enabled_list if n in REGISTRY] if cfg.get("tools_enabled") else []
    
    max_rounds = int(CONFIG.MAX_ROUNDS or 20)
    permission = str(cfg.get("permission") or "workspace")
    perm_have = int(PERM_LEVEL.get(permission, 1))

    retried_413 = False

    for round_idx in range(1, max_rounds + 1):
        yield {"type": "round", "round": round_idx, "max": max_rounds}

        parser = ToolParser(tool_names) if tool_names else None
        think_parser = ThinkParser()
        full_text = ""
        full_reasoning = ""
        xml_tool_calls = []

        for chunk in stream_chat(cfg, full_messages):
            if "error" in chunk:
                msg = chunk["error"]
                if "413" in msg and not retried_413:
                    retried_413 = True
                    keep = [m for m in full_messages if m["role"] == "user" and not m.get("hidden")]
                    full_messages = [full_messages[0]] + keep[-1:]
                    yield {"type": "notice", "text": "请求体过大，已自动压缩历史重试…"}
                    break
                yield {"type": "error", "message": msg}
                return
                
            if "reasoning" in chunk:
                full_reasoning += chunk["reasoning"]
                yield {"type": "reasoning", "text": chunk["reasoning"]}
            
            if "text" in chunk:
                txt = chunk["text"]
                plain_txt, reasoning_txt = think_parser.feed(txt, final=False)
                if reasoning_txt:
                    full_reasoning += reasoning_txt
                    yield {"type": "reasoning", "text": reasoning_txt}
                
                if plain_txt:
                    if parser:
                        plain, calls = parser.feed(plain_txt, final=False)
                        if plain:
                            full_text += plain
                            yield {"type": "token", "text": plain}
                        xml_tool_calls.extend(calls)
                    else:
                        full_text += plain_txt
                        yield {"type": "token", "text": plain_txt}

        # 收尾
        plain_txt, reasoning_txt = think_parser.feed("", final=True)
        if reasoning_txt:
            full_reasoning += reasoning_txt
            yield {"type": "reasoning", "text": reasoning_txt}
        if plain_txt:
            if parser:
                plain, calls = parser.feed(plain_txt, final=True)
                if plain:
                    full_text += plain
                    yield {"type": "token", "text": plain}
                xml_tool_calls.extend(calls)
            else:
                full_text += plain_txt
                yield {"type": "token", "text": plain_txt}

        if parser:
            plain, calls = parser.feed("", final=True)
            if plain:
                full_text += plain
                yield {"type": "token", "text": plain}
            xml_tool_calls.extend(calls)
            tail = parser.flush()
            if tail:
                full_text += tail
                yield {"type": "token", "text": tail}

        # 如果没有解析到任何工具标签，说明是一轮普通的对话，直接结束
        if not xml_tool_calls:
            yield {"type": "done", "text": full_text, "reasoning": full_reasoning}
            return

        # 把本轮 AI 的完整输出（含 XML 标签）写回上下文
        assistant_text = full_text
        for c in xml_tool_calls:
            assistant_text += f'\n<tool name="{c.name}" args=\'{json.dumps(c.args, ensure_ascii=False)}\'/>'
        full_messages.append({"role": "assistant", "content": assistant_text})

        results = []
        task_done = False
        task_summary = ""

        # 执行工具
        for i, call in enumerate(xml_tool_calls):
            tid = f"xml_{round_idx}_{i}"
            tool = REGISTRY.get(call.name)

            yield {"type": "tool_start", "id": tid, "name": call.name, "title": tool.title if tool else call.name, "args": call.args}

            if not tool or call.name not in tool_names:
                err = f"未知工具或该工具未启用：{call.name}"
                yield {"type": "tool_end", "id": tid, "ok": False, "result": err}
                results.append(f"[tool:error] {err}")
                continue

            need = int(PERM_LEVEL.get(tool.perm or "read", 0))
            if perm_have < need:
                msg = f"权限不足：需要「{PERM_NAME.get(tool.perm, tool.perm)}」"
                yield {"type": "tool_end", "id": tid, "ok": False, "result": msg}
                results.append(f"[tool:error] {msg}")
                continue

            if tool.interactive:
                aid, waiter = session.new_ask()
                questions = call.args.get("questions") or []
                yield {"type": "ask", "id": aid, "tool_id": tid, "questions": questions}
                answers = waiter.wait(timeout=600)
                if answers is None:
                    msg = "用户未回答（超时）"
                    yield {"type": "tool_end", "id": tid, "ok": False, "result": msg}
                    results.append(f"[tool:error] {msg}")
                else:
                    txt = "\n\n".join([f"Q{qi+1}: {q.get('text','')}\nA{qi+1}: {a}" for qi, (q, a) in enumerate(zip(questions, answers))])
                    yield {"type": "tool_end", "id": tid, "ok": True, "result": txt}
                    results.append(f"[用户回答]\n{txt}")
                continue

            try:
                _validate_args(tool, call.args or {})
                res = tool.handler(call.args or {}, {"cfg": cfg})
                if res is None: res = ToolResult(text="已完成")
                if not isinstance(res, ToolResult): res = ToolResult(text=str(res))
                results.append(res.text or "（无返回）")
                
                end_ev = {"type": "tool_end", "id": tid, "ok": True, "result": res.text}
                if res.ui_event: end_ev["ui_event"] = res.ui_event
                yield end_ev
                
                if call.name == "task_complete":
                    task_done = True
                    task_summary = call.args.get("summary") or ""
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                results.append(f"[tool:error] {msg}")
                yield {"type": "tool_end", "id": tid, "ok": False, "result": msg}

        if task_done:
            yield {"type": "task_complete", "summary": task_summary}
            return

        # 把工具的结果作为隐藏的 user 消息回传
        tool_msg = "[系统] 以下是工具返回结果"
        if any(r.startswith("[tool:error]") for r in results):
            tool_msg += "（含失败，请分析原因并修正参数或换工具）"
        tool_msg += "：\n\n" + "\n\n".join(results)
        
        full_messages.append({"role": "user", "content": tool_msg})

    yield {"type": "round_limit", "max": max_rounds}