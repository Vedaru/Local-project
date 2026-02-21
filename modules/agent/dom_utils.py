"""dom_utils — 为 BrowserAgent 提供 DOM 提取脚本和解析函数。"""

from typing import List, Dict, Any

# JavaScript 片段，用于遍历页面 DOM 并标记交互元素
# 返回格式为 Python 可识别的对象列表，包含 id/tag/text/type/name/id_attr 等字段。
DOM_EXTRACT_SCRIPT = r"""
() => {
    const interactive = ['a','button','input','textarea','select'];
    let items = [];
    let idCounter = 1;
    function isVisible(el){
        if (!el.offsetParent) return false;
        const style = window.getComputedStyle(el);
        return !(style.display==='none' || style.visibility==='hidden' || style.opacity==='0');
    }
    // 首先清除旧的标记，避免重复
    document.querySelectorAll('[data-ai-id]').forEach(el => el.removeAttribute('data-ai-id'));
    document.querySelectorAll(interactive.join(',')).forEach(el => {
        if (!isVisible(el)) return;
        let info = {id: idCounter, tag: el.tagName.toLowerCase()};
        info.text = (el.innerText || '').trim();
        // 如果文本中包含时长格式 mm:ss 或 hh:mm:ss，则计算秒数并添加字段
        let durMatch = info.text.match(/(\d+):(\d{2})(?::(\d{2}))?/);
        if (durMatch) {
            let secs = parseInt(durMatch[1], 10) * 60 + parseInt(durMatch[2], 10);
            if (durMatch[3]) secs += parseInt(durMatch[3], 10) * 3600;
            info.duration = secs;
        }
        if (el.tagName.toLowerCase() === 'input' || el.tagName.toLowerCase() === 'textarea') {
            info.type = el.type || '';
            info.name = el.name || '';
            info.placeholder = el.placeholder || '';
            info.value = el.value || '';
        }
        if (el.id) info.id_attr = el.id;
        el.setAttribute('data-ai-id', idCounter);
        items.push(info);
        idCounter++;
    });
    return items;
}
"""


def extract_dom_json(page) -> List[Dict[str, Any]]:
    """在 Playwright page 上执行 DOM_EXTRACT_SCRIPT，返回列表。

    如果执行失败或返回空值，返回空列表。
    """
    try:
        result = page.evaluate(DOM_EXTRACT_SCRIPT)
        return result or []
    except Exception:
        return []
