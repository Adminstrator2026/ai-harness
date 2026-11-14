import json, re

class ToolCall:
    __slots__ = ("name", "args")
    def __init__(self, name, args):
        self.name = name
        self.args = args

class ThinkParser:
    def __init__(self):
        self.in_think = False
        self.buf = ""

    def feed(self, text, final=False):
        self.buf += text
        plain, reasoning = [], []
        while self.buf:
            if not self.in_think:
                idx = self.buf.find("<think>")
                if idx >= 0:
                    plain.append(self.buf[:idx])
                    self.buf = self.buf[idx+7:]
                    self.in_think = True
                else:
                    if final:
                        plain.append(self.buf)
                        self.buf = ""
                    else:
                        keep = 0
                        for i in range(1, min(len(self.buf), 7)+1):
                            if "<think>".startswith(self.buf[-i:]):
                                keep = i
                        if keep > 0:
                            plain.append(self.buf[:-keep])
                            self.buf = self.buf[-keep:]
                        else:
                            plain.append(self.buf)
                            self.buf = ""
                        break
            else:
                idx = self.buf.find("</think>")
                if idx >= 0:
                    reasoning.append(self.buf[:idx])
                    self.buf = self.buf[idx+8:]
                    self.in_think = False
                else:
                    if final:
                        reasoning.append(self.buf)
                        self.buf = ""
                    else:
                        keep = 0
                        for i in range(1, min(len(self.buf), 8)+1):
                            if "</think>".startswith(self.buf[-i:]):
                                keep = i
                        if keep > 0:
                            reasoning.append(self.buf[:-keep])
                            self.buf = self.buf[-keep:]
                        else:
                            reasoning.append(self.buf)
                            self.buf = ""
                        break
        return "".join(plain), "".join(reasoning)


class ToolParser:
    def __init__(self, tool_names):
        self.tool_names = set(tool_names)
        self.buf = ""
        self.max_buf = 128 * 1024
        self.awaiting_fence_close = False

    def feed(self, text, final=False):
        self.buf += text
        plain, calls = [], []
        
        while True:
            # 1. 如果刚提取完被代码块包裹的工具，吞掉尾部冗余的 ```
            if self.awaiting_fence_close:
                idx = self.buf.find("```")
                if idx >= 0:
                    pre = self.buf[:idx]
                    if pre.strip(): plain.append(pre)
                    self.buf = self.buf[idx+3:]
                    self.awaiting_fence_close = False
                else:
                    if final:
                        plain.append(self.buf); self.buf = ""
                        self.awaiting_fence_close = False
                    else:
                        break
                continue

            # 2. 寻找工具标签
            idx_tool = self._find_start(self.buf)
            
            # 💡 核心修复：这里可能返回 None，必须用 is not None 判断，不能用 >= 0
            if idx_tool is not None:
                call, used = self._try_parse(self.buf[idx_tool:])
                if call:
                    pre = self.buf[:idx_tool]
                    # 检查工具标签前是否跟着 ``` 或 ```xml，如果是，说明是被包裹的，剥离它们
                    m = re.search(r'```[a-zA-Z0-9_-]*\s*\n?$', pre)
                    if m:
                        pre = pre[:m.start()]
                        self.awaiting_fence_close = True
                    
                    if pre: plain.append(pre)
                    calls.append(call)
                    self.buf = self.buf[idx_tool+used:]
                    continue
                else:
                    if final:
                        plain.append(self.buf); self.buf = ""
                    break
            
            # 3. 处理普通文本
            if final:
                plain.append(self.buf); self.buf = ""
                break
                
            keep = self._partial_suffix(self.buf)
            if keep > 0:
                plain.append(self.buf[:-keep]); self.buf = self.buf[-keep:]
            else:
                plain.append(self.buf); self.buf = ""
            break

        return "".join(plain), calls

    def flush(self):
        if self.buf:
            out, self.buf = self.buf, ""
            return out
        return ""

    def _find_start(self, s):
        for m in re.finditer(r"<([a-zA-Z_][\w-]*)", s):
            n = m.group(1)
            if n == "tool" or n in self.tool_names:
                return m.start()
        return None

    def _partial_suffix(self, s):
        i = s.rfind("<")
        if i < 0: return 0
        tail = s[i:]
        if ">" in tail: return 0
        m = re.match(r"<([a-zA-Z_][\w-]*)$", tail)
        if not m: return 0
        n = m.group(1)
        for tn in self.tool_names:
            if tn.startswith(n) or n.startswith(tn):
                return len(tail)
        if "tool".startswith(n): return len(tail)
        return 0

    def _try_parse(self, s):
        m = re.match(r"<tool\s+name\s*=\s*(?:\"([^\"]*)\"|'([^']*)')\s*", s, re.I)
        if m:
            name = m.group(1) or m.group(2)
            end = s.find(">", m.end())
            if end < 0: return None, 0
            head = s[m.end():end]
            is_self = head.rstrip().endswith("/")
            attr_area = head.rstrip().rstrip("/").strip()
            args = self._parse_kv(attr_area)
            am = re.search(r"args\s*=\s*(\"([\s\S]*?)\"|'([\s\S]*?)')", attr_area)
            if am:
                body_json = am.group(2) if am.group(2) is not None else am.group(3)
                try:
                    obj = json.loads(body_json)
                    if isinstance(obj, dict): args.update(obj)
                except Exception: pass
                attr_area = re.sub(r"args\s*=\s*(\"[\s\S]*?\"|'[\s\S]*?')", "", attr_area)
                args.update(self._parse_kv(attr_area))
            if is_self:
                return ToolCall(name, args), end + 1
            close = s.find("</tool>", end)
            if close < 0: return None, 0
            body = s[end + 1:close].strip()
            body = re.sub(r"^```(?:json)?\s*", "", body)
            body = re.sub(r"\s*```$", "", body)
            try:
                obj = json.loads(body)
                if isinstance(obj, dict): args.update(obj)
            except Exception: pass
            return ToolCall(name, args), close + len("</tool>")

        m = re.match(r"<([a-zA-Z_][\w-]*)", s)
        if m and m.group(1) in self.tool_names:
            name = m.group(1)
            end = s.find(">", m.end())
            if end < 0: return None, 0
            attr_area = s[m.end():end].rstrip().rstrip("/").strip()
            return ToolCall(name, self._parse_kv(attr_area)), end + 1
        return None, 0

    def _parse_kv(self, text):
        out = {}
        for m in re.finditer(r"([a-zA-Z_][\w-]*)\s*=\s*(\"([^\"]*)\"|'([^']*)')", text):
            k = m.group(1)
            v = m.group(3) if m.group(3) is not None else m.group(4)
            try: out[k] = json.loads(v)
            except Exception: out[k] = v
        return out