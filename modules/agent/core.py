"""
ManusAgent — 基于 ReAct 的简单智能体主循环实现

行为模型：
- 每次向 LLM 请求时，强制 LLM 以 JSON 格式回复：
  {"thought": "...", "tool": "<tool-name>", "args": <string|object>}。
- 解析 LLM 输出的 tool 并调用 AgentTools 执行，获取 observation 后将其反馈给 LLM
- 最多迭代 max_iterations 次（默认 10）

注意：该模块为同步实现，适合在主线程或阻塞 worker 中运行。
"""
from typing import Optional, List
import re
import json


class ManusAgent:
    """Manus 风格的本地智能体（ReAct loop）

    llm_fn: 可调用对象，签名与 modules.llm.call_llm 保持一致：
        llm_fn(system_prompt, model_name, prompt, memory_context="") -> str
    tools: AgentTools 实例
    """

    def __init__(self, llm_fn, tools, model_name: str, system_prompt: str = "", max_iterations: int = 10):
        self.llm_fn = llm_fn
        self.tools = tools
        self.model_name = model_name
        self.system_prompt = (system_prompt or "")
        self.max_iterations = max_iterations

        # 为 Agent 专门准备的 system prompt 片段（强制 LLM 严格只输出 JSON）
        self.agent_system_prompt = (
            "你是 Agent，一个本地 ReAct 智能体。\n"
            "【强制规则】当你作为 Agent 响应时，**必须且只能输出一个 JSON 对象**，不得包含任何额外文字、注释、解释、或 Markdown/代码围栏。\n"
            "输出必须严格遵循下列 JSON 模式（字段顺序不限）：\n"
            "{" + '"thought": "<解释你的下一步思路>", "tool": "<工具名>", "args": <字符串或对象>' + "}\n"
            "可用工具（严格）：search, browse, read_file, write_file, open_local_app, click_screen, dom_open, dom_query, dom_preview, dom_click, dom_open_and_click, dom_fill, dom_eval, dom_status, final_answer。\n"            "重要：**绝对不要**在 thought 或 args 中提及或使用 Google 搜索（google.com / google.*）。如需检索，请使用 `search` 工具或 `https://www.baidu.com/s?wd=...`（默认使用百度）。\n"            "此外：**不要使用或生成 `open_browser` 指令**——该指令已从系统移除；遇到网页交互请使用 `dom_open`（Playwright）。\n"            "示例（严格，输出中不得有其他任何字符）：\n"
            "{\"thought\":\"我要先搜索相关新闻\",\"tool\":\"search\",\"args\":\"DeepSeek 新闻\"}\n"
            "完成任务时请使用 tool=\"final_answer\" 并在 args 中放最终结果（字符串或 JSON 对象）。\n"
            "如果你无法完成某步，请仍然返回符合格式的 JSON（例如使用 tool=\"search\" 或返回空的 args），不要返回纯文本解释。"
        )

    def _clean_markdown(self, text: str) -> str:
        """清洗 LLM 输出中的 Markdown 包装符号，保留代码块内的原始内容。

        - 去掉 ```code``` 或 ```json``` 等围栏，但保留围栏内文本（常见于 LLM 将 JSON 放入代码块的情况）
        - 去掉单反引号包裹的 inline code
        - 移除行首的 Markdown 引用符号（>）、标题符号（#）、列表标记（-/*/数字.）
        - 移除简单的 HTML <code>/<pre> 标签
        目的是避免 Markdown 符号干扰后续的 JSON 正则/解析。
        """
        if not text:
            return text

        # 1) 保留代码块内部内容，去除 ``` ``` 围栏
        def _unbox_code_block(m):
            block = m.group(0)
            # 删除开头的 ```json 或 ```lang 行，以及结尾的 ```
            block = re.sub(r'^```[^\n]*\n', '', block)
            block = re.sub(r'\n```$', '', block)
            return block

        text = re.sub(r'```[\s\S]*?```', _unbox_code_block, text)

        # 2) 去除单反引号的 inline code（保留内容）
        text = re.sub(r'`([^`]*)`', r"\1", text)

        # 3) 移除常见 Markdown 装饰（行首的 >, #, 列表标记）
        text = re.sub(r'^\s*>+\s?', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*#{1,6}\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)

        # 4) 删除简单的 HTML 标签 <pre>, <code>
        text = re.sub(r'</?pre>|</?code>', '', text, flags=re.IGNORECASE)

        return text.strip()

    def _extract_json(self, text: str) -> Optional[dict]:
        """更健壮地从 LLM 输出中抽取第一个 JSON 对象并解析为 dict。

        - 先做 Markdown 清洗（去除代码围栏等）。
        - 使用配对花括号扫描（可正确处理嵌套 JSON）代替简单正则。
        - 提供若干宽松解析回退：去掉尾随逗号、使用 ast.literal_eval 解析 Python 风格字面量、
          最后尝试安全替换单引号为双引号作为兜底。
        """
        if not text:
            return None

        # 清洗常见 Markdown 包装与 Unicode 控制字符
        text = self._clean_markdown(text)
        text = re.sub(r'[\u200b\ufeff\u00a0]', '', text)  # 去除零宽/NBSP 等
        # 规范化智能引号为 ASCII 引号，减少 LLM 使用“”导致解析失败的情况
        text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")

        # 找到第一个左花括号并做平衡括号扫描以正确抽取嵌套 JSON
        start = text.find('{')
        if start == -1:
            return None

        i = start
        depth = 0
        in_string = False
        string_char = None
        escape = False
        js_text = None
        while i < len(text):
            ch = text[i]
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif in_string:
                if ch == string_char:
                    in_string = False
                    string_char = None
            elif ch == '"' or ch == "'":
                in_string = True
                string_char = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    js_text = text[start:i+1]
                    break
            i += 1

        if js_text is None:
            # 未找到匹配的闭合花括号，退回到从 start 到末尾的尝试（仍可尝试解析）
            js_text = text[start:]

        # 将字符串内部的真实控制字符（未被转义的换行/回车/制表）替换为 JSON 转义序列，
        # 以处理 LLM 有时在字符串中插入未转义换行的情况（非法 JSON）
        def _escape_unescaped_control_chars(s: str) -> str:
            out = []
            in_str = False
            esc = False
            str_ch = None
            for ch in s:
                if esc:
                    out.append(ch)
                    esc = False
                    continue
                if ch == '\\':
                    out.append(ch)
                    esc = True
                    continue
                if in_str:
                    if ch == str_ch:
                        in_str = False
                        str_ch = None
                        out.append(ch)
                        continue
                    if ch == '\n':
                        out.append('\\n')
                        continue
                    if ch == '\r':
                        out.append('\\r')
                        continue
                    if ch == '\t':
                        out.append('\\t')
                        continue
                    out.append(ch)
                else:
                    out.append(ch)
                    if ch == '"' or ch == "'":
                        in_str = True
                        str_ch = ch
            return ''.join(out)

        # 先尝试严格解析（对原始 js_text 做最小量的规范化）
        try:
            sanitized = _escape_unescaped_control_chars(js_text)
            return json.loads(sanitized)
        except Exception:
            pass

        # 回退 1：删除可能的尾随逗号并再次尝试
        safe = re.sub(r',\s*(\}|\])', r'\1', js_text)
        safe = _escape_unescaped_control_chars(safe)

        # 回退 2：若更像 Python 字面量（包含 True/False/None 或单引号）, 尝试 ast.literal_eval
        try:
            import ast
            if ('True' in safe) or ('False' in safe) or ('None' in safe) or ("'" in safe and '"' not in safe):
                obj = ast.literal_eval(safe)
                if isinstance(obj, dict):
                    return obj
        except Exception:
            pass

        # 回退 3：将单引号替换为双引号后尝试 JSON 解析（最后手段）
        try:
            alt = safe.replace("'", '"')
            return json.loads(alt)
        except Exception:
            return None

    def run_task(self, task_description: str) -> str:
        """执行给定任务（同步、阻塞）并返回最终结果字符串。"""
        history: List[str] = []
        system_prompt = (self.system_prompt + "\n\n" + self.agent_system_prompt).strip()

        for step in range(1, self.max_iterations + 1):
            # 构造 prompt：包含任务、历史与当前要求
            prompt_parts = [f"任务: {task_description}", "\n历史记录（最近动作 -> 观察）："]
            if history:
                prompt_parts.append('\n'.join(history[-6:]))
            prompt_parts.append(
                "\n请仅以 JSON 格式输出下一步的思考与要执行的工具调用。示例：{\"thought\":\"...\",\"tool\":\"search\",\"args\":\"查询内容\"}"
            )
            prompt = '\n'.join(prompt_parts)

            raw = self.llm_fn(system_prompt, self.model_name, prompt)
            if not raw:
                return "❌ LLM 未返回内容"

            parsed = self._extract_json(raw)
            if not parsed:
                # 如果首次解析失败，允许有限次数的格式修正尝试：提示 LLM 只输出纯 JSON
                correction_attempts = 2
                corrected_raw = raw
                for attempt in range(correction_attempts):
                    correction_prompt = (
                        "上一条回复不是一个有效的纯 JSON 对象（请不要包含任何额外文本或 Markdown）。\n"
                        "请**仅**返回一个严格的 JSON 对象，格式为：{\"thought\":\"...\",\"tool\":\"<tool>\",\"args\":<string|object>}。\n"
                        "下面是模型的原始输出，请从中直接返回合法 JSON：\n" + corrected_raw
                    )
                    corrected_raw = self.llm_fn(system_prompt, self.model_name, correction_prompt)
                    if not corrected_raw:
                        break
                    parsed = self._extract_json(corrected_raw)
                    if parsed:
                        raw = corrected_raw
                        break

                if not parsed:
                    # 最终失败：记录原始响应并返回错误
                    return f"❌ LLM 未返回可解析 JSON（尝试修正失败），原始内容：{raw}"

            thought = parsed.get('thought', '')
            tool = (parsed.get('tool') or '').strip()
            args = parsed.get('args')

            # 兼容回退：若模型仍然使用已移除的 `open_browser`，自动改写为 `dom_open`（保留 url 参数）
            if tool == 'open_browser':
                tool = 'dom_open'
                # 保持 args 的形式（字符串或对象），并在 history 中记录改写
                history.append(f"NOTE: 将已弃用的 open_browser 自动改写为 dom_open，args={args}")

            # 安全策略：若 LLM 在 thought/args 中使用了 google.com / google.*，自动改写为百度（www.baidu.com 优先）
            def _rewrite_google_to_baidu_in_value(val):
                try:
                    from urllib.parse import urlparse, parse_qs, urlencode
                    if isinstance(val, str) and 'google.' in val:
                        p = urlparse(val)
                        hostname = (p.hostname or '').lower()
                        path = p.path or ''
                        if 'google.' in hostname and path.startswith('/search'):
                            qval = parse_qs(p.query).get('q', [''])[0]
                            return 'https://www.baidu.com/s?' + urlencode({'wd': qval}) if qval else 'https://www.baidu.com'
                        # 非 search 的 google 链接改写为百度主页加原路径（best-effort）
                        return 'https://www.baidu.com' + (p.path or '') + (('?' + p.query) if p.query else '')
                    return val
                except Exception:
                    return val

            # 如果 args 是字符串或 dict，递归检查并替换 google URL
            if isinstance(args, str):
                if 'google.' in args:
                    args = _rewrite_google_to_baidu_in_value(args)
                    thought = (thought or '').replace('Google', 'Baidu').replace('google', 'baidu')
            elif isinstance(args, dict):
                for k, v in list(args.items()):
                    if isinstance(v, str) and 'google.' in v:
                        args[k] = _rewrite_google_to_baidu_in_value(v)
                        thought = (thought or '').replace('Google', 'Baidu').replace('google', 'baidu')

            # 记录思考
            history.append(f"Thought: {thought} | Action: {tool} | Args: {args}")

            # 处理终结条件
            if tool in ('final_answer', 'final', 'done'):
                # 直接返回 args（如果是对象则转换为 JSON 字符串，字符串直接返回）
                if isinstance(args, str):
                    return args
                try:
                    return json.dumps(args, ensure_ascii=False)
                except Exception:
                    return str(args)

            # 否则调用工具执行 action
            observation = self.tools.execute(tool, args)

            # 如果工具返回明显的失败/网络错误或空响应，立即作为最终结果返回，避免 Agent 无输出
            if isinstance(observation, str):
                lower_obs = observation.lower()
                if observation.startswith('❌') or observation.startswith('⚠️') or observation.startswith('🔍') \
                   or '无法获取' in observation or '未提供' in observation or 'connection' in lower_obs:
                    return f"❌ 工具执行失败或网络不可用：{observation}"
                if observation.strip() == '':
                    return f"⚠️ 工具返回空响应：{tool}"

            # 记录观察结果并继续下轮
            history.append(f"Observation: {observation}")

        # 达到最大迭代次数仍未结束
        last_obs = history[-1] if history else "无观察结果"
        return f"⚠️ 达到最大迭代次数（{self.max_iterations}），最近观察：{last_obs}"
