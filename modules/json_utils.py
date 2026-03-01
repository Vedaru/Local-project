"""
共享 JSON 解析工具 — 从 LLM 原始输出中提取 JSON 对象

将 main.py 和 agent/core.py 中重复的 balanced-brace 扫描、宽松解析逻辑
统一提取到此处，避免代码重复并集中维护。
"""
import re
import json
import ast
from typing import Optional, List


def parse_loose(js_text: str) -> Optional[dict]:
    """尝试多种宽松 JSON 解析策略，返回 dict 或 None。

    依次尝试：
    1. 标准 ``json.loads``
    2. 提取 Markdown 代码围栏中的内容后再解析
    3. 去除尾随逗号 + 智能引号规范化
    4. 替换单引号为双引号
    5. ``ast.literal_eval`` 处理 Python 风格字面量
    """
    if not js_text:
        return None

    # 1) 直接尝试
    try:
        obj = json.loads(js_text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 2) 提取代码围栏
    m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', js_text, re.IGNORECASE)
    candidate = m.group(1) if m else js_text

    # 3) 去除尾随逗号 + 规范化智能引号
    cand = re.sub(r',\s*(\}|\])', r'\1', candidate)
    cand = cand.replace('\u201c', '"').replace('\u201d', '"')

    try:
        obj = json.loads(cand)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 4) 单引号 → 双引号
    try:
        obj = json.loads(cand.replace("'", '"'))
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 5) ast.literal_eval（Python 风格字面量）
    try:
        obj = ast.literal_eval(candidate)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    return None


def _scan_balanced_brace(s: str, start: int) -> Optional[str]:
    """从 ``s[start]`` 开始扫描一对平衡花括号，返回匹配的子串（含花括号）或 None。

    正确处理嵌套大括号、字符串内的转义字符与引号。
    """
    length = len(s)
    if start >= length or s[start] != '{':
        return None

    depth = 0
    in_str = False
    esc = False
    quote_ch = None
    j = start

    while j < length:
        ch = s[j]
        if esc:
            esc = False
        elif ch == '\\':
            esc = True
        elif in_str:
            if ch == quote_ch:
                in_str = False
                quote_ch = None
        elif ch in ('"', "'"):
            in_str = True
            quote_ch = ch
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return s[start:j + 1]
        j += 1

    return None


def extract_all_jsons(s: str) -> List[dict]:
    """返回文本中所有可解析为 dict 的 JSON 对象（列表，保持顺序）。

    1. 优先提取 ``[ACTION]...[/ACTION]`` 块中的 JSON
    2. 然后做平衡花括号扫描提取裸 JSON
    """
    if not s:
        return []

    results: List[dict] = []
    seen_spans: list = []  # 记录已消费的字符范围，避免重复

    # 1) 提取所有 [ACTION] 块
    for m in re.finditer(r'\[ACTION\](.*?)\[/ACTION\]', s, re.DOTALL):
        txt = m.group(1).strip()
        if not txt:
            continue
        parsed = parse_loose(txt)
        if isinstance(parsed, dict):
            results.append(parsed)
            seen_spans.append((m.start(), m.end()))

    # 2) 平衡花括号扫描提取裸 JSON
    i = 0
    length = len(s)
    while i < length:
        try:
            i = s.index('{', i)
        except ValueError:
            break

        # 跳过已被 [ACTION] 块消费的区域
        if any(start <= i < end for start, end in seen_spans):
            i += 1
            continue

        matched = _scan_balanced_brace(s, i)
        if matched:
            parsed = parse_loose(matched)
            if isinstance(parsed, dict):
                results.append(parsed)
            i += len(matched)
        else:
            i += 1

    return results


def extract_first_json(s: str) -> Optional[dict]:
    """返回文本中第一个可解析为 dict 的 JSON 对象，或 None。"""
    objs = extract_all_jsons(s)
    return objs[0] if objs else None
