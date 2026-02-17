"""dom_utils.py

帮助函数：URL 规范化与 dom_click 候选 selector 生成。
将这些辅助逻辑提取到独立模块以缩短 `executor.py` 的体积。
"""
from urllib.parse import urlparse, parse_qs, urlencode
from typing import List, Optional


def canonical_search_url(url: Optional[str]) -> Optional[str]:
    """若 URL 为搜索页面或裸词，返回规范化的百度搜索 URL，否则返回原 URL。"""
    try:
        if not url:
            return None
        p = urlparse(url)
        # 裸词 -> 转为百度搜索
        if not p.scheme or not p.netloc:
            return 'https://www.baidu.com/s?' + urlencode({'wd': url})
        hostname = (p.hostname or '').lower()
        path = p.path or ''
        if 'google.' in hostname and path.startswith('/search'):
            qs = parse_qs(p.query)
            qval = qs.get('q', [''])[0]
            return 'https://www.baidu.com/s?' + urlencode({'wd': qval}) if qval else 'https://www.baidu.com'
        if 'bing.com' in hostname:
            qs = parse_qs(p.query)
            qval = qs.get('q', [''])[0] if 'q' in qs else None
            if qval:
                return 'https://www.baidu.com/s?' + urlencode({'wd': qval})
        return url
    except Exception:
        return url


def generate_click_candidates(selector: str) -> List[str]:
    """根据原始 selector 生成一组回退候选 selector（供 dom_click 使用）。"""
    candidates = [selector]
    # 特定站点 / 模式的优化
    if "href^=\"https://www.bilibili.com/video/\"" in selector or "href^=\'https://www.bilibili.com/video/\'" in selector:
        candidates += [
            "a[href^='/video/']",
            "a[href*='/video/']",
            "a[class*='bili-video-card__image--link']",
            "a.bili-video-card__image--link",
        ]
    else:
        candidates += [
            "a[href*='/video/']",
            "a[class*='bili-video-card__image--link']",
            "a.bili-video-card__image--link",
        ]
    # 保证不重复
    seen = set()
    out = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out