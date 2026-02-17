import re, json, ast


def extract_first_json(s: str):
    if not s:
        return None

    def _parse_loose(js_text: str):
        try:
            return json.loads(js_text)
        except Exception:
            pass
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', js_text, re.IGNORECASE)
        candidate = m.group(1) if m else js_text
        cand = re.sub(r',\s*(\}|\])', r'\1', candidate)
        cand = cand.replace('“', '"').replace('”', '"')
        try:
            return json.loads(cand)
        except Exception:
            pass
        try:
            cand2 = cand.replace("'", '"')
            return json.loads(cand2)
        except Exception:
            try:
                obj = ast.literal_eval(candidate)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                return None

    if '[ACTION]' in s:
        for block in re.findall(r'\[ACTION\](.*?)\[/ACTION\]', s, re.DOTALL):
            txt = block.strip()
            if not txt:
                continue
            parsed = _parse_loose(txt)
            if isinstance(parsed, dict):
                return parsed

    candidates = []
    i = 0
    L = len(s)
    while True:
        try:
            i = s.index('{', i)
        except ValueError:
            break
        depth = 0
        in_str = False
        esc = False
        quote_ch = None
        j = i
        while j < L:
            ch = s[j]
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif in_str:
                if ch == quote_ch:
                    in_str = False
                    quote_ch = None
            elif ch == '"' or ch == "'":
                in_str = True
                quote_ch = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    js_text = s[i:j+1]
                    parsed = _parse_loose(js_text)
                    if isinstance(parsed, dict):
                        if 'tool' in parsed or 'action' in parsed:
                            return parsed
                        candidates.append(parsed)
                    break
            j += 1
        i = i + 1

    if candidates:
        return candidates[0]
    return None


cases = [
    'Some noise before {"thought":"x","tool":"search","args":"hi"} after',
    '```json\n{"thought":"a","tool":"dom_open","args":"https://a"}\n```',
    'Text [ACTION]{"action":"dom_open","url":"https://ex"}[/ACTION] tail',
    'Messy { "tool": "dom_click", "args": {"id": 1,}, } trailing',
    "Single quotes {'tool':'search','args':'abc'} end",
]

for c in cases:
    print('----')
    print('input:', c)
    print('parsed ->', extract_first_json(c))
