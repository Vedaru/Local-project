"""
轻量级 WebSurfer（requests + BeautifulSoup / 可选 DrissionPage 回退）
- 使用静态抓取（requests + BeautifulSoup）作为首选（无需浏览器内核、适合国内网络）
- 若页面高度依赖 JS，可尝试使用 DrissionPage（若用户安装并可用）

返回：{'url': url, 'title': title, 'text': cleaned_text}
"""
from typing import Optional, Dict
import requests
from bs4 import BeautifulSoup
import re

# DrissionPage 是可选依赖；若可用可用于动态页面抓取
try:
    from drission import DrissionPage
except Exception:
    DrissionPage = None


class WebSurfer:
    """同步的网页抓取器，优先使用 requests + BeautifulSoup。

    设计为同步接口以便在主线程或阻塞工作线程中直接调用。
    """

    def __init__(self, prefer_drission: bool = False, timeout: int = 10):
        """初始化

        Args:
            prefer_drission: 如果为 True 且 DrissionPage 可用，则优先使用 DrissionPage
            timeout: requests 超时时间（秒）
        """
        self.prefer_drission = prefer_drission and (DrissionPage is not None)
        self.timeout = timeout
        self._dp = None
        if self.prefer_drission:
            try:
                self._dp = DrissionPage()
            except Exception:
                self._dp = None
                self.prefer_drission = False

    def browse(self, url: str) -> Dict[str, Optional[str]]:
        """访问网页并返回清洗后的正文（静态抓取为主，必要时回退到 DrissionPage）"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/115.0 Safari/537.36'
        }

        html = None
        # 优先静态抓取（requests）——国内直连速度快且不依赖浏览器
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            html = resp.text
        except Exception:
            # 若静态抓取失败且用户允许使用 DrissionPage，则尝试回退
            if self._dp:
                try:
                    self._dp.get(url)
                    html = self._dp.source
                except Exception:
                    html = None

        if not html:
            return {'url': url, 'title': None, 'text': f"[浏览失败] 无法获取页面内容（静态/Drission 回退均失败）: {url}"}

        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string.strip() if soup.title and soup.title.string else ''

        # 优先尝试常见正文标签，再回退到 body
        selectors = ['article', 'main', 'div[id*=content]', 'div[class*=content]', 'div[class*=article]', 'body']
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator='\n', strip=True)
                if text:
                    return {'url': url, 'title': title, 'text': self._clean_text(text)}

        # 回退
        fallback = soup.get_text(separator='\n', strip=True)
        return {'url': url, 'title': title, 'text': self._clean_text(fallback)}

    def _clean_text(self, text: str) -> str:
        """简单清洗：压缩多重空行并去除首尾空白"""
        cleaned = re.sub(r"\n{2,}", '\n\n', text)
        return cleaned.strip()

    def close(self):
        """释放 DrissionPage（如果创建过）"""
        try:
            if self._dp:
                self._dp.close()
        except Exception:
            pass
