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
from urllib.parse import urlparse, parse_qs, urlencode
from ..logging_config import get_logger
from ..json_utils import _scan_balanced_brace as scan_balanced_brace

# registry provides dynamic tool descriptions and dispatching
from .registry import registry as tool_registry

# 学习相关
from ..memory.skills import SkillManager

logger = get_logger('ManusAgent')


def _rewrite_google_to_baidu(val: str) -> str:
    """将 google 搜索/链接改写为百度等价 URL（安全策略）。"""
    try:
        if not isinstance(val, str) or 'google.' not in val:
            return val
        p = urlparse(val)
        hostname = (p.hostname or '').lower()
        path = p.path or ''
        if 'google.' in hostname and path.startswith('/search'):
            qval = parse_qs(p.query).get('q', [''])[0]
            return ('https://www.baidu.com/s?' + urlencode({'wd': qval})) if qval else 'https://www.baidu.com'
        return 'https://www.baidu.com' + (p.path or '') + (('?' + p.query) if p.query else '')
    except Exception:
        return val


class ManusAgent:
    """Manus 风格的本地智能体（ReAct loop）

    llm_fn: 可调用对象，签名与 modules.llm.call_llm 保持一致：
        llm_fn(system_prompt, model_name, prompt, memory_context="") -> str
    tools: AgentTools 实例
    """

    def __init__(self, llm_fn, tools, model_name: str, system_prompt: str = "", max_iterations: int = 10, memory_storage=None):
        self.llm_fn = llm_fn
        self.tools = tools
        self.model_name = model_name
        self.system_prompt = (system_prompt or "")
        self.max_iterations = max_iterations
        logger.info(f"ManusAgent initialized (model={model_name}, max_iterations={max_iterations}, tools={getattr(tools, '__class__', tools)})")

        # 学习状态 — 共享 storage 避免 SkillManager 创建额外 ChromaDB 连接
        self.skill_manager = SkillManager(storage=memory_storage)
        self.is_learning = False
        self.learning_buffer: list = []
        self.learning_task_name: str = ""

        # 为 Agent 专门准备的 system prompt 片段（强制 LLM 严格只输出 JSON），
        # 此处工具列表从 registry 自动填充。
        desc = tool_registry.get_prompt_description()
        self.agent_system_prompt = (
            "你是 Agent，一个本地 ReAct 智能体。\n"
            "【强制规则】当你作为 Agent 响应时，**必须且只能输出一个 JSON 对象**，不得包含任何额外文字、注释、解释、或 Markdown/代码围栏。\n"
            "输出必须严格遵循下列 JSON 模式（字段顺序不限）：\n"
            "{" + '"thought": "<解释你的下一步思路>", "tool": "<工具名>", "args": <字符串或对象>' + "}\n"
            f"可用工具如下：\n{desc}\n\n"
            "【核心原则：任务拆解与逐步执行】\n"
            "1. 收到任务后，在第一步的 thought 中将任务拆解为子目标清单（如①②③）\n"
            "2. 每次只执行一个工具调用，等待 Observation 后再决定下一步\n"
            "3. 每步的 thought 中标明「已完成 X/Y，下一步做 Z」的进度\n"
            "4. **只有当所有子目标都已通过工具实际执行并确认成功后**，才使用 final_answer\n"
            "5. 绝不要在 thought 中描述计划然后直接返回 final_answer！必须真正执行每一步\n"
            "6. 不要仅凭「我应该点击」就返回 final_answer，必须实际调用 click_element 并确认\n\n"
            "【通用搜索】使用 web_search 工具可以在百度上搜索：\n"
            '{"thought":"子目标①搜索天气。用web_search","tool":"web_search","args":"北京天气预报"}\n\n'
            "【完整示例：在B站搜索并点击视频】\n"
            "任务：打开B站搜索宋浩然后点击第一个视频\n"
            "子目标：①打开B站 ②用fill_and_submit一步填入搜索词并提交 ③扫描结果 ④点击第一个视频 ⑤确认\n\n"
            "第1步:\n"
            '{"thought":"子目标①打开B站。进度0/5","tool":"browse","args":"https://www.bilibili.com"}\n'
            "第2步（用 fill_and_submit 一次完成：定位输入框+输入+回车，比分三步更可靠）:\n"
            '{"thought":"子目标②填入搜索词并提交。进度1/5","tool":"fill_and_submit","args":"宋浩"}\n'
            "第3步:\n"
            '{"thought":"子目标③扫描搜索结果，找第一个视频的 el_ID。进度2/5","tool":"scan_page","args":""}\n'
            "第4步（关键！从 scan_page 输出找到第一个视频的 el_ID 后点击）:\n"
            '{"thought":"子目标④第一个宋浩视频是 el_XX，点击它。进度3/5","tool":"click_element","args":"el_XX"}\n'
            "第5步:\n"
            '{"thought":"子目标⑤扫描确认视频页已打开。进度4/5","tool":"scan_page","args":""}\n'
            "第6步:\n"
            '{"thought":"所有子目标已执行完毕。进度5/5","tool":"final_answer","args":"已在B站搜索并打开了第一个宋浩视频"}\n\n'
            "【重要提醒】\n"
            "- scan_page 输出中每个元素有 [ID: el_N] 标记，用 click_element 时传入该 ID（如 el_156）\n"
            "- **绝对禁止**使用 el_X、el_XX 等占位符！必须从 scan_page 的实际输出中找到真实的数字编号\n"
            "- 如果 scan_page 没有返回可用的视频/链接元素，先尝试其他方式（如滚动页面或重新搜索），不要猜测编号\n"
            "- 搜索场景优先使用 fill_and_submit（一步完成：定位输入框+输入+回车），比 click+type+Enter 三步更可靠\n"
            "- 完成任务时使用 tool=\"final_answer\"，在 args 中放最终结果\n"
            "- 如果某步失败，在 thought 中说明失败原因，然后尝试其他方法，不要返回纯文本\n"
            "- 不要自己编造 URL，使用 browse 只打开你确定的完整 URL\n"
        )
        # 迁移的动作执行准则
        self.agent_system_prompt += (
            "\n动作执行准则：回复中表示要执行操作时，必须包含对应的工具调用 JSON。"
        )

    # ======= 学习接口 =======
    def start_learning(self, task_name: str) -> str:
        """开启教学模式，清空已有的交互记录。"""
        self.is_learning = True
        self.learning_buffer = []
        self.learning_task_name = task_name or ""
        logger.info(f"进入学习模式，任务={self.learning_task_name}")
        return f"已进入学习模式：{self.learning_task_name}"

    def stop_learning(self) -> str:
        """结束教学模式，将记录的数据提交至 SkillManager。"""
        if not self.is_learning:
            return "学习模式未开启。"
        self.is_learning = False
        logs = self.learning_buffer.copy()
        task = self.learning_task_name
        self.learning_buffer = []
        self.learning_task_name = ""
        try:
            self.skill_manager.learn_new_skill(task, logs)
        except Exception as e:
            logger.error(f"技能学习失败: {e}", exc_info=True)
        return "学习完成，SOP 已归档"

    @staticmethod
    def _clean_markdown(text: str) -> str:
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

        js_text = scan_balanced_brace(text, start)

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
        logger.info(f"ManusAgent.run_task called — task_description={task_description[:200]}")
        history: List[str] = []

        # 尝试从技能库中检索已有 SOP，并将其注入到 system_prompt
        skill_sop = ""
        try:
            sop = self.skill_manager.retrieve_skill(task_description)
            if sop:
                skill_sop = f"\n\n### 📖 参考经验 (SOP)\n{sop}"
        except Exception:
            pass

        system_prompt = (self.system_prompt + skill_sop + "\n\n" + self.agent_system_prompt).strip()

        for step in range(1, self.max_iterations + 1):
            logger.debug(f"Agent iteration {step}/{self.max_iterations} — task='{task_description[:80]}'")
            # 构造 prompt：包含任务、历史与当前要求
            prompt_parts = [f"任务: {task_description}"]
            prompt_parts.append("\n历史记录（已执行的动作与观察）：")
            if history:
                prompt_parts.append('\n'.join(history[-16:]))
            prompt_parts.append(
                "\n请在 thought 中：1) 列出任务的所有子目标 2) 标记已完成/未完成 3) 确定下一步\n"
                "然后输出 JSON：{\"thought\":\"...\",\"tool\":\"<工具名>\",\"args\":\"...\"}\n"
                "只有所有子目标都已实际执行完毕，才能使用 final_answer。"
            )
            prompt = '\n'.join(prompt_parts)

            logger.debug(f"Sending prompt to LLM (truncated): {prompt[:800].replace('\n','\\n')}")
            raw = self.llm_fn(system_prompt, self.model_name, prompt)
            logger.debug(f"LLM raw response (len={len(raw) if raw else 0}): { (raw or '')[:1600].replace('\n','\\n') }")
            if not raw:
                logger.error("LLM returned empty response")
                return "❌ LLM 未返回内容"

            parsed = self._extract_json(raw)
            logger.debug(f"Parsed JSON from LLM: {parsed}")
            # if JSON was extracted, also compute trailing text after the object
            remainder = ''
            if parsed and raw:
                start = raw.find('{')
                if start != -1:
                    matched = scan_balanced_brace(raw, start)
                    if matched:
                        remainder = raw[start + len(matched):].strip()
            # fallback heuristic: if no JSON found or remainder contains action keywords,
            # inject a corresponding JSON so the loop can continue instead of giving up.

            if not parsed:
                    logger.warning("首次解析 LLM 输出为 JSON 失败，尝试进行有限次格式修正。")
                    # 如果首次解析失败，允许有限次数的格式修正尝试：提示 LLM 只输出纯 JSON
                    correction_attempts = 2
                    corrected_raw = raw
                    for attempt in range(correction_attempts):
                        logger.debug(f"格式修正尝试 #{attempt+1}")
                        correction_prompt = (
                            "上一条回复不是一个有效的纯 JSON 对象（请不要包含任何额外文本或 Markdown）。\n"
                            "请**仅**返回一个严格的 JSON 对象，格式为：{\"thought\":\"...\",\"tool\":\"<tool>\",\"args\":<string|object>}。\n"
                            "下面是模型的原始输出，请从中直接返回合法 JSON：\n" + corrected_raw
                        )
                        corrected_raw = self.llm_fn(system_prompt, self.model_name, correction_prompt)
                        logger.debug(f"修正后原始返回 (truncated): {(corrected_raw or '')[:800].replace('\n','\\n')}")
                        if not corrected_raw:
                            logger.error("修正尝试未收到 LLM 响应")
                            break
                        parsed = self._extract_json(corrected_raw)
                        if parsed:
                            raw = corrected_raw
                            logger.info("格式修正成功：已从 LLM 响应中提取到 JSON")
                            break

                    if not parsed:
                        logger.error(f"LLM 输出无法解析为 JSON，原始内容(截断): { (raw or '')[:800].replace('\n','\\n') }")
                        # 最终失败：记录原始响应并返回错误
                        return f"❌ LLM 未返回可解析 JSON（尝试修正失败），原始内容：{raw}"
            thought = parsed.get('thought', '')
            tool = (parsed.get('tool') or '').strip()
            args = parsed.get('args')

            logger.debug(f"LLM produced tool='{tool}' with args={args}")

            # 安全策略：若 LLM 在 thought/args 中使用了 google.com / google.*，自动改写为百度
            if isinstance(args, str):
                if 'google.' in args:
                    args = _rewrite_google_to_baidu(args)
                    thought = (thought or '').replace('Google', 'Baidu').replace('google', 'baidu')
            elif isinstance(args, dict):
                for k, v in list(args.items()):
                    if isinstance(v, str) and 'google.' in v:
                        args[k] = _rewrite_google_to_baidu(v)
                        thought = (thought or '').replace('Google', 'Baidu').replace('google', 'baidu')

            # 记录思考
            logger.debug(f"LLM thought='{thought[:200]}' tool='{tool}' args={str(args)[:400]}")
            history.append(f"Thought: {thought} | Action: {tool} | Args: {args}")

            # 处理终结条件
            if tool in ('final_answer', 'final', 'done'):
                # 对于多步骤任务，验证所有子目标是否已真正完成
                multi_kw = ['并', '然后', '接着', '之后', '再', '同时', '且', '并且', '点击', '打开']
                is_multi = any(kw in task_description for kw in multi_kw)
                already_verified = any('[已验证]' in h for h in history)

                if is_multi and not already_verified and step < self.max_iterations - 1:
                    executed_tools = [h for h in history if h.startswith('Thought:')]
                    verify_prompt = (
                        f"原始任务: {task_description}\n\n"
                        f"你即将返回 final_answer: {args}\n\n"
                        f"已执行的操作:\n" + '\n'.join(executed_tools) + "\n\n"
                        "请逐一对照任务中的每个要求（用「并」「然后」「再」等词连接的子任务），"
                        "检查是否都已通过工具调用实际执行了（不是计划执行，而是真的调用了工具）。\n"
                        "- 如果全部完成: {\"thought\":\"已确认全部完成\",\"tool\":\"final_answer\",\"args\":\"<结果>\"}\n"
                        "- 如果有遗漏: 返回下一步工具调用 JSON 继续执行。"
                    )
                    verify_raw = self.llm_fn(system_prompt, self.model_name, verify_prompt)
                    verify_parsed = self._extract_json(verify_raw) if verify_raw else None
                    if verify_parsed:
                        v_tool = (verify_parsed.get('tool') or '').strip()
                        if v_tool not in ('final_answer', 'final', 'done'):
                            v_thought = verify_parsed.get('thought', '')
                            logger.info(f"任务完成度验证: 发现未完成子目标 — {v_thought[:100]}")
                            history.append(f"[已验证] 系统发现任务未全部完成: {v_thought}")
                            continue  # 返回循环继续执行
                        else:
                            # 验证确认完成，用验证的 args
                            v_args = verify_parsed.get('args', args)
                            if v_args:
                                args = v_args

                logger.info(f"Agent 返回 final_answer，args 类型={type(args)}")
                if isinstance(args, str):
                    return args
                try:
                    return json.dumps(args, ensure_ascii=False)
                except Exception:
                    return str(args)

            # 否则调用工具执行 action
            logger.debug(f"Calling tool: {tool} with args={args}")

            # 空工具名 — LLM输出格式有误，给一次反馈让它重试
            if not tool or not tool.strip():
                logger.warning("LLM 返回了空的工具名")
                observation = "⚠️ 你没有指定工具名。请在 JSON 的 tool 字段中填入一个有效的工具名（如 scan_page、click_element、browse 等）。"
                history.append(f"Observation: {observation}")
                continue

            try:
                observation = tool_registry.dispatch_tool(tool, args, instance=self.tools)
            except KeyError:
                logger.error(f"未知工具请求: {tool}")
                observation = f"⚠️ 未知工具「{tool}」，可用工具请参考系统提示。请在下一步使用正确的工具名。"
            except Exception as e:
                logger.error(f"工具执行抛出异常: {e}", exc_info=True)
                observation = f"⚠️ 工具执行异常：{e}。请在 thought 中分析原因后重试。"

            # 如果工具返回明显的失败/网络错误或空响应，记录但不立即终止——
            # 让 Agent 有机会在下一轮尝试其他方式完成任务。
            if isinstance(observation, str):
                if observation.strip() == '':
                    logger.warning(f"工具返回空响应：{tool}")
                    observation = f"⚠️ 工具 {tool} 返回了空响应，请换一种方式尝试。"

            # 记录观察结果并继续下轮
            logger.debug(f"Appending observation to history: {str(observation)[:400]}")
            history.append(f"Observation: {observation}")
            # 如果正在学习，将本轮交互追加到缓冲
            if self.is_learning:
                entry = (
                    f"Thought: {thought}\n" 
                    f"Action: {tool} {json.dumps(args, ensure_ascii=False)}\n" 
                    f"Observation: {observation}"
                )
                self.learning_buffer.append(entry)

        # 达到最大迭代次数仍未结束
        last_obs = history[-1] if history else "无观察结果"
        logger.warning(f"达到最大迭代次数（{self.max_iterations}），返回最近观察：{last_obs}")
        return f"⚠️ 达到最大迭代次数（{self.max_iterations}），最近观察：{last_obs}"
