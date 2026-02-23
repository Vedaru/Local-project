import logging

logger = logging.getLogger('AgentTools.click_element')


def click_element(agent_tools, element_id: str) -> str:
    """Click an element previously enumerated by scan_page."""
    logger.debug(f"click_element() id={element_id}")
    try:
        return agent_tools.click_element(element_id)
    except Exception as e:
        logger.exception("click_element() failed")
        return f"❌ 点击元素失败: {e}"
