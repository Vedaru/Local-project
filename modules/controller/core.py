"""
核心调度模块 - 指令解析与调度
负责解析 AI 响应中的控制指令并执行
"""

import json
import re
from typing import Tuple, Optional
from .safety import SafetyGuard
from .executor import ActionExecutor


class ComputerController:
    """
    电脑控制器类
    解析 AI 响应中的控制指令并安全执行
    """

    def __init__(self, safety_guard: SafetyGuard, action_executor: ActionExecutor):
        """
        初始化控制器

        Args:
            safety_guard: 安全守卫实例
            action_executor: 动作执行器实例
        """
        self.safety_guard = safety_guard
        self.action_executor = action_executor

    def process_command(self, response_text: str) -> Tuple[str, str]:
        """
        处理 AI 响应文本，提取并执行控制指令

        Args:
            response_text: AI 返回的完整文本（可能包含对话和指令）

        Returns:
            Tuple[str, str]: (execution_log, clean_text)
                - execution_log: 执行日志，如果无指令则为空字符串
                - clean_text: 去除指令标签后的纯对话文本
        """
        # 查找所有 [ACTION] 标签
        action_pattern = r'\[ACTION\](.*?)\[/ACTION\]'
        matches = re.findall(action_pattern, response_text, re.DOTALL)
        
        if not matches:
            # 无指令，返回原文本
            return "", response_text

        # 执行所有指令
        execution_logs = []
        for action_json in matches:
            try:
                action_data = json.loads(action_json.strip())
                
                # 验证指令格式
                if not isinstance(action_data, dict) or 'action' not in action_data:
                    execution_logs.append("❌ 指令解析失败: 缺少 'action' 字段")
                    continue
                
                # 执行指令
                log = self._execute_action(action_data)
                execution_logs.append(log)
                
            except json.JSONDecodeError as e:
                execution_logs.append(f"❌ 指令解析失败: 无效的 JSON 格式 - {str(e)}")
            except Exception as e:
                execution_logs.append(f"❌ 执行失败: {str(e)}")

        # 合并所有执行日志
        execution_log = " | ".join(execution_logs) if execution_logs else ""

        # 移除所有指令标签，获取纯对话文本
        clean_text = re.sub(action_pattern, '', response_text, flags=re.DOTALL).strip()

        return execution_log, clean_text

    def _execute_action(self, action_data: dict) -> str:
        """
        执行具体动作

        Args:
            action_data: 解析后的指令数据

        Returns:
            str: 执行结果日志
        """
        tool = action_data.get('action')

        try:
            if tool == 'open_app':
                app_path = action_data.get('app_path', '')
                if not app_path:
                    return "❌ 指令错误: open_app 缺少 'app_path' 参数"

                # 安全验证
                safe_path = self.safety_guard.validate_path(app_path)

                # 执行启动
                return self.action_executor.open_app(safe_path)

            elif tool == 'type_text':
                text = action_data.get('text', '')
                if not text:
                    return "❌ 指令错误: type_text 缺少 'text' 参数"

                return self.action_executor.type_text(text)

            elif tool == 'press_key':
                key = action_data.get('key', '')
                if not key:
                    return "❌ 指令错误: press_key 缺少 'key' 参数"

                return self.action_executor.press_key(key)

            elif tool == 'save_note':
                content = action_data.get('content', '')
                filename = action_data.get('filename', None)
                if not content:
                    return "❌ 指令错误: save_note 缺少 'content' 参数"

                return self.action_executor.save_note(content, filename)

            elif tool == 'open_browser':
                url = action_data.get('url', None)
                browser_path = action_data.get('browser_path', None)
                
                return self.action_executor.open_browser(url, browser_path)

            else:
                return f"❌ 未知指令: {tool}"

        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"❌ 执行失败: {str(e)}"