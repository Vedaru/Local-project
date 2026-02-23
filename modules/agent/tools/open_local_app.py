import os
import logging
import platform
import subprocess
import time

logger = logging.getLogger('AgentTools.open_local_app')

def open_local_app(agent_tools, app_path: str) -> str:
    """打开本地应用或浏览器。如果传入 URL 会走浏览器。"""
    logger.debug(f"open_local_app() app_path={app_path}")
    try:
        # 如果参数看起来像 URL，优先交给新的 browse 方法
        if isinstance(app_path, str) and app_path.startswith(('http://','https://')):
            try:
                logger.debug(f"open_local_app() treating url as browse: {app_path}")
                return agent_tools.browse(app_path)
            except Exception as e:
                logger.error(f"browse failed for {app_path}: {e}", exc_info=True)
                # fall through to default behavior

        # the action executor is deprecated; open the application
        # directly using the OS facilities instead.
        # before calling startfile, check whether the path exists or is resolvable
        if not os.path.isabs(app_path) and not os.path.exists(app_path):
            # try resolving via PATH
            import shutil
            exe = shutil.which(app_path)
            if exe:
                app_path = exe
            else:
                msg = f"未找到可执行文件: {app_path}"
                logger.error(msg)
                return f"❌ 启动应用失败: {msg}"
        try:
            # mimic ActionExecutor behaviour: on Windows use startfile,
            # otherwise spawn subprocess
            if platform.system() == 'Windows':
                os.startfile(app_path)
            else:
                subprocess.Popen([app_path])
            # give the application a moment to appear
            time.sleep(0.8)
            return f"已启动: {app_path}"
        except Exception as e:
            logger.error(f"local startfile failed for {app_path}: {e}", exc_info=True)
            return f"❌ 启动应用失败: {e}"
    except Exception as e:
        logger.error(f"open_local_app() failed app_path={app_path}: {e}", exc_info=True)
        return f"❌ 启动应用失败: {str(e)}"
