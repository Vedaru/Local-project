import logging

logger = logging.getLogger('AgentTools.browse')


def browse(agent_tools, url: str) -> str:
    """Open a URL using AgentTools' built-in browser logic."""
    logger.debug(f"browse() url={url}")
    try:
        return agent_tools.browse(url)
    except Exception as e:
        logger.exception("browse() failed")
        return f"❌ 打开网页失败: {e}"
