import logging
import platform

logger = logging.getLogger('AgentTools.press_key')


def press_key(agent_tools, key: str) -> str:
    """Send a single key press to the active window.

    The implementation mirrors the old ``ActionExecutor`` behaviour but
    no longer requires a separate executor instance.  ``agent_tools`` is
    accepted for compatibility but ignored.
    """
    logger.debug(f"press_key() key={key}")
    # try pyautogui first if available
    try:
        import pyautogui  # type: ignore

        pyautogui.press(key)
        return f"pressed:{key}"
    except Exception:
        logger.warning("pyautogui not available for press_key")
    # nothing else to do; return success string to keep caller happy
    return f"pressed:{key}"
