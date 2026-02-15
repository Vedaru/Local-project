"""
ManusAgent — 基于 ReAct 的简单智能体主循环实现

行为模型：
- 每次向 LLM 请求时，强制 LLM 以 JSON 格式回复：
  {"thought": "...", "tool": "<tool-name>", "args": <string|object>}。
- 解析 LLM 输出的 tool 并调用 AgentTools 执行，获取 observation 后将其反馈给 LLM
- 最多迭代 max_iterations 次（默认 10）

注意：该模块为同步实现，适合在主线程或阻塞 worker 中运行。
"""
from typing import Any, Optional, List
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
            "你是 ManusAgent，一个本地 ReAct 智能体。\n"
            "【强制规则】当你作为 Agent 响应时，**必须且只能输出一个 JSON 对象**，不得包含任何额外文字、注释、解释、或 Markdown/代码围栏。\n"
            "输出必须严格遵循下列 JSON 模式（字段顺序不限）：\n"
            "{" + '"thought": "<解释你的下一步思路>", "tool": "<工具名>", "args": <字符串或对象>' + "}\n"
            "可用工具（严格）：search, browse, read_file, write_file, open_local_app, click_screen, ocr_scan, ocr_click, final_answer。\n"
            "示例（严格，输出中不得有其他任何字符）：\n"
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
        """尝试从 LLM 原始输出中抽取第一个 JSON 对象并解析为 dict。

        在解析前先做 Markdown 清洗，去除常见的代码围栏与标记，避免 LLM 用 Markdown 包裹 JSON 导致解析失败。
        """
        if not text:
            return None

        # 先清洗 Markdown 包装（例如 ```json ... ```）
        text = self._clean_markdown(text)

        # 尝试用正则捕获第一个花括号包裹的对象
        m = re.search(r'(\{(?:.|\n)*?\})', text)
        if not m:
            return None
        js_text = m.group(1)

        try:
            return json.loads(js_text)
        except json.JSONDecodeError:
            # 宽松解析尝试（替换单引号为双引号、删除不可见字符）作为最后手段
            try:
                safe = js_text.replace("'", '"')
                safe = re.sub(r'\u200b|\ufeff', '', safe)  # 移除零宽字符
                return json.loads(safe)
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
