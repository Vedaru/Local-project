"""
轻量级 WebSurfer 类并包含 BrowserAgent 代理。
WebSurfer 提供简单的 Playwright 封装以打开页面、提取元素、点击等。
BrowserAgent 则实现 Observe->Think->Act 循环，使用配置文件中的 LLM 客户端。
"""
from playwright.sync_api import sync_playwright
import time
import os
import json

# 载入环境变量支持
from dotenv import load_dotenv
# 使用 config 中的 LLM 客户端
from modules.config import client as llm_client, MODEL_NAME

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


class BrowserAgent:
    """基于 Playwright 与 OpenAI 的简易浏览器代理。

    实现 Observe -> Think -> Act 循环，使用 data-ai-id 定位元素。
    """

    def __init__(self):
        # 初始化环境变量（如有必要）
        load_dotenv()
        # 使用 config 提供的 LLM 客户端
        self.llm = llm_client
        # 初始化浏览器
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=False)
        self.page = self.browser.new_page()

    def observe(self):
        """执行 DOM 提取脚本，返回结构化 JSON 列表。"""
        from .dom_utils import extract_dom_json
        return extract_dom_json(self.page)

    def think(self, goal: str, dom_json):
        """向 LLM 发送目标与 DOM，获取下一步动作 JSON。"""
        system = (
            "你是一个智能浏览器代理，负责根据给定的高层目标自主规划并执行页面操作。\n"
            "你有四种可用动作：scan, click, type, navigate；每次只能输出一个动作的JSON。\n"
            "可用动作说明：\n"
            "  - scan：扫描当前页面并返回结构化 DOM 列表（id/tag/text/...）。通常在操作前先执行一次。\n"
            "  - click：点击指定 id 的元素。id 对应 scan 输出中的 id 字段。\n"
            "  - type：在指定 id 的输入框或文本区域输入文字（完成后会自动回车并尝试提交）。\n"
            "  - navigate：直接导航到给定 URL，适合跳转到新页面或搜索结果。\n"
            "每次只能输出一个动作的JSON对象。\n"
            "过程由外部循环驱动：它将执行你的动作并再次问你下一步。\n"
            "当你判断目标已成功完成时，输出 {\"action\":\"finish\"}；这将使循环终止。\n"
            "DOM 列表是JSON数组，每个对象包含字段：id, tag, text, type, name, id_attr, duration（如果可用）。\n"
            "在执行任何点击或填充前，通常应先scan获取最新的DOM，除非你已经非常确定目标元素的位置。\n"
            "分析DOM时请用你的推理判断哪些元素与目标相关，例如识别视频时长、标题、按钮等。\n"
            "如果元素包含 duration 字段，请用它来比较时长。\n"
            "例如目标“时长超过10分钟”时，应遍历DOM元素并点击第一个 duration>=600 的视频。\n"
            "请不要点击时长不足的视频；若当前页面无满足条件的元素，可继续scan或结束任务，不要点击其他链接。\n"
            "示例流程：\n"
            "1. scan -> DOM: [{\"id\":1,\"tag\":\"a\",\"text\":\"...\",\"duration\":120}, {\"id\":2,\"tag\":\"a\",\"text\":\"...\",\"duration\":720}]\n"
            "2. 目标含“超过10分钟” -> 输出 {\"action\":\"click\",\"id\":2}\n"
            "不要对输入框执行任何click动作；输入后请直接使用Enter或查找提交按钮来触发搜索。除非目标中明确要求输入关键词，否则不要在搜索框或任何输入框中输入任何内容。\n"
            "一个元素只需type一次；不要重复对同一id执行type操作，如果你发现自己要再次type同一元素，就转向其他动作或直接结束。\n"
            "当需要输入时，优先选择 placeholder 或 value 中包含“搜索”的输入框，这通常是搜索栏。\n"
            "如果目标中指定了关键词，请用该关键词作为输入值，不要使用 placeholder 的内容。仅当目标清楚要求时才执行type动作，否则忽略输入框。\n"
            "输入后无须再次点击输入框本身或其它输入元素；可点击搜索/提交按钮或直接按 Enter。\n"
            "输入完成后不要立即去点击结果列表或页面上的其他链接，先确保搜索请求已经生效并页面已加载结果。\n"
            "高层目标只是指导，应自由规划具体步骤，不需要包含任何特定关键词。\n"
            "不要在链接或按钮上输入文本。不要对同一元素重复执行相同动作。\n"
            "你的回答必须是严格的JSON，仅包含要执行的一个动作。"
        )
        current = self.page.url if hasattr(self.page, 'url') else ''
        prompt = (
            f"Goal: {goal}\n"
            f"Current URL: {current}\n"
            f"DOM: {json.dumps(dom_json, ensure_ascii=False)}"
        )
        try:
            model_name = MODEL_NAME or 'gpt-4o'
            # 直接使用配置客户端
            # 为避免重复导航，可在 system 中说明：
            # 若 current URL 已与目标域名匹配，则不要再导航。
            resp = self.llm.chat.completions.create(
                model=model_name,
                messages=[
                    {'role': 'system', 'content': system + "\n如果当前页面已经是目标地址，请直接执行后续动作，避免再次导航。"},
                    {'role': 'user', 'content': prompt},
                ],
                temperature=0,
            )
            # new API: message is ChatCompletionMessage with .content attribute
            msg = resp.choices[0].message
            content = msg.content if hasattr(msg, 'content') else str(msg)
            # strip markdown fences
            cleaned = content.strip()
            if cleaned.startswith("```"):
                # remove first and last fence lines
                lines = cleaned.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines)
            print("[BrowserAgent] LLM raw message:", content)
            print("[BrowserAgent] cleaned message:", cleaned)
            return cleaned.strip()
        except Exception as e:
            return json.dumps({'action': 'error', 'error': str(e)})

    def act(self, action_json: str):
        """执行 LLM 返回的动作。"""
        try:
            act = json.loads(action_json)
        except Exception as e:
            return f"解析动作失败: {e}: {action_json}"
        a = act.get('action')
        if a == 'scan':
            domjson = self.observe()
            return "SCAN_RESULT:" + json.dumps(domjson, ensure_ascii=False)
        if a == 'navigate':
            url = act.get('url')
            try:
                self.page.goto(url, wait_until='domcontentloaded')
                return f"navigated {url}"
            except Exception as e:
                return f"navigate error: {e}"
        if a == 'click':
            aid = act.get('id') or act.get('element_id')
            sel = f'[data-ai-id="{aid}"]'
            print(f"[BrowserAgent] clicking selector {sel}")
            # if user tries to click an input/textarea, ignore it (search boxes shouldn't be clicked)
            try:
                tag = self.page.evaluate(f"() => document.querySelector('{sel}')?.tagName.toLowerCase()")
            except Exception:
                tag = None
            if tag in ('input','textarea'):
                print(f"[BrowserAgent] ignored click on {tag}")
                return f"ignored_click_{aid}"
            # try to detect if this link points to a video or bangumi
            href = None
            try:
                href = self.page.evaluate(f"() => document.querySelector('{sel}')?.href")
            except Exception:
                href = None
            is_video_link = False
            if href and ("/video/" in href or "/bangumi/" in href):
                is_video_link = True
            try:
                self.page.click(sel)
                try:
                    self.page.wait_for_load_state('networkidle', timeout=5000)
                except Exception:
                    pass
                if is_video_link:
                    return f"clicked_video {aid}"
                return f"clicked {aid}"
            except Exception as e:
                err = str(e)
                if 'Target page, context or browser has been closed' in err:
                    try:
                        ctxs = self.browser.contexts
                        if ctxs:
                            last_ctx = ctxs[-1]
                            if last_ctx.pages:
                                self.page = last_ctx.pages[-1]
                                msg = f"clicked {aid} (switched to new page)"
                                if is_video_link:
                                    msg = msg.replace('clicked', 'clicked_video')
                                return msg
                    except Exception:
                        pass
                return f"click error: {e}"
        elif a == 'type':
            aid = act.get('id') or act.get('element_id')
            val = act.get('text') or act.get('value','')
            sel = f'[data-ai-id="{aid}"]'
            print(f"[BrowserAgent] filling selector {sel} with {val}")
            # 如果元素不是input/textarea ，尝试在DOM中找到一个合适的元素
            try:
                tag = self.page.evaluate(f"() => document.querySelector('{sel}')?.tagName.toLowerCase()")
            except Exception:
                tag = None
            if tag not in ('input','textarea'):
                # 搜索第一个可用输入
                print(f"[BrowserAgent] selected tag {tag} not input/textarea, searching fallback")
                dom = self.observe()
                print(f"[BrowserAgent] DOM list for fallback: {dom}")
                for obj in dom:
                    if obj.get('tag') in ('input','textarea'):
                        alt = obj.get('id')
                        if alt == aid:
                            continue
                        aid = alt
                        sel = f'[data-ai-id="{aid}"]'
                        print(f"[BrowserAgent] fallback to selector {sel} (id {aid})")
                        break
            try:
                self.page.fill(sel, val)
                # after typing, try to submit via Enter on the same element first
                try:
                    self.page.press(sel, 'Enter')
                    self.page.wait_for_load_state('networkidle', timeout=5000)
                except Exception:
                    pass
                # if there is a dedicated search button, click it as well
                self._click_default_search()
                return f"typed {val}"
            except Exception as e:
                return f"type error: {e}"
        elif a == 'finish':
            return 'finished'
        else:
            return f"unknown action: {a}"

    def _click_default_search(self):
        """尝试点击含有百度一下或提交字样的按钮"""
        try:
            # 优先使用看到的 id_attr 或文本
            # 通过DOM JSON查找
            dom = self.observe()
            target_id = None
            for obj in dom:
                if obj.get('tag') == 'button':
                    txt = (obj.get('text') or '').lower()
                    if '百度一下' in txt or 'submit' in (obj.get('id_attr') or '').lower():
                        target_id = obj.get('id')
                        break
            if target_id is not None:
                sel = f'[data-ai-id="{target_id}"]'
                print(f"[BrowserAgent] auto-clicking search button {sel}")
                self.page.click(sel)
                self.page.wait_for_load_state('networkidle')
                return True
        except Exception as e:
            print(f"[BrowserAgent] click default search error: {e}")
        return False

    def close(self):
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            self.playwright.stop()
        except Exception:
            pass
