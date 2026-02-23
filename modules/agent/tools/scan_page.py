import logging

logger = logging.getLogger('AgentTools.scan_page')


def scan_page(agent_tools) -> str:
    """Return a summary of all visible elements on the current browser page.

Previously the tool only listed links and buttons; it now reports any element
with visible content or identifying attributes, along with its tag name,
text and common attributes (href/class/id). This richer output is produced
by ``agent_tools.scan_page`` and merely forwarded here.
"""
    logger.debug("scan_page()")
    try:
        return agent_tools.scan_page()
    except Exception as e:
        logger.exception("scan_page() failed")
        return f"❌ 扫描页面失败: {e}"
