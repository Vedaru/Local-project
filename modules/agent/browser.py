"""
轻量级 WebSurfer（requests + BeautifulSoup / 可选 DrissionPage 回退）
- 使用静态抓取（requests + BeautifulSoup）作为首选（无需浏览器内核、适合国内网络）
- 若页面高度依赖 JS，可尝试使用 DrissionPage（若用户安装并可用）

返回：{'url': url, 'title': title, 'text': cleaned_text}
"""
from playwright.sync_api import sync_playwright
import time

class WebSurfer:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None

    def start(self):
        """启动浏览器 (如果还没启动)"""
        if not self.page:
            self.playwright = sync_playwright().start()
            # headless=False 让你能看到浏览器动作
            self.browser = self.playwright.chromium.launch(headless=False)
            self.page = self.browser.new_page()

    def browse(self, url):
        """访问网页"""
        self.start()
        print(f"🌐 正在访问: {url}")
        self.page.goto(url, wait_until="domcontentloaded")
        time.sleep(2) # 等待动态内容加载 (如B站视频列表)
        return "网页已打开。"

    def get_interactive_elements(self):
        """
        核心功能：获取页面上重要的可点击元素
        这相当于给 AI 一份“菜单”，告诉它页面上有啥。
        """
        # NOTE: 公共 API — 可能被 Agent / 外部调用（运行时动态使用）
        if not self.page:
            return "浏览器未启动"

        # 使用 JS 注入，提取页面上所有可见的链接和按钮
        # 针对 B站 做了优化，专门提取视频卡片
        elements_info = self.page.evaluate("""() => {
            let items = [];
            // 1. 查找 B站视频卡片 (新版 UI)
            document.querySelectorAll('.bili-video-card, .video-card').forEach((el, index) => {
                let titleEl = el.querySelector('h3') || el.querySelector('.bili-video-card__info--tit');
                let title = titleEl ? titleEl.innerText : '未知视频';
                if(title) items.push(`[ID: video_${index}] 视频: ${title}`);
            });
            
            // 2. 查找普通链接和按钮 (作为补充)
            if (items.length === 0) {
                document.querySelectorAll('a, button').forEach((el, index) => {
                    let text = el.innerText.replace(/\\s+/g, ' ').trim();
                    if (text.length > 2 && el.offsetParent !== null) { // 只取可见且有文字的
                        items.push(`[ID: el_${index}] ${text}`);
                    }
                });
            }
            
            // 只返回前 20 个结果，防止 Token 爆炸
            return items.slice(0, 20).join('\\n');
        }""")

        return elements_info

    def click_element(self, selector_id):
        """
        根据 ID 点击元素
        """
        # NOTE: 公共 API — 可能被 Agent / 外部调用（运行时动态使用）
        if not self.page:
            return "浏览器未启动"

        try:
            if "video_" in selector_id:
                # 点击第 N 个视频
                index = int(selector_id.split('_')[1])
                # Playwright 选择器：匹配 B站视频卡片
                self.page.locator('.bili-video-card, .video-card').nth(index).click()
                return f"已点击第 {index+1} 个视频"

            elif "el_" in selector_id:
                # 点击普通文本链接 (模糊匹配)
                # 实际生产中建议用更精确的 XPath，这里为了演示简化
                index = int(selector_id.split('_')[1])
                self.page.locator('a, button').nth(index).click()
                return "已点击目标元素"

            # 兜底：尝试直接通过文本点击
            else:
                self.page.get_by_text(selector_id).first.click()
                return f"已尝试点击文本: {selector_id}"

        except Exception as e:
            return f"点击失败: {e}"
