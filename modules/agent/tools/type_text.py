
import logging
import platform
import subprocess

logger = logging.getLogger('AgentTools.type_text')


def type_text(agent_tools, text: str) -> str:
    """Send keystrokes to the active window.

    Delegates to ``agent_tools.action_executor`` when available, falling
    back to a lightweight pyautogui/PowerShell implementation otherwise.
    """
    logger.debug(f"type_text() agent_tools={agent_tools!r} text={text!r}")
    try:
        if hasattr(agent_tools, 'action_executor') and agent_tools.action_executor:
            return agent_tools.action_executor.type_text(text)

        # attempt to use pyautogui first, since it handles focus and delays
        try:
            import pyautogui  # type: ignore
            # try to activate a notepad-like window or one containing the
            # target text; this resolves issues when the target app isn't on
            # top and keystrokes go elsewhere.
            try:
                wins = (
                    pyautogui.getWindowsWithTitle('无标题')
                    or pyautogui.getWindowsWithTitle('Notepad')
                    or pyautogui.getWindowsWithTitle(text[:10])
                )
                if wins:
                    win = wins[0]
                    win.activate()
                    pyautogui.sleep(0.5)
            except Exception:
                pass
            # if text contains non-ascii characters, use clipboard paste
            if any(ord(c) > 127 for c in text):
                try:
                    import pyperclip
                    pyperclip.copy(text)
                    pyautogui.hotkey('ctrl', 'v')
                    return f"pasted:{text} (clipboard)"
                except Exception:
                    # clipboard paste failed, fall back to write
                    pass
            pyautogui.write(text, interval=0.02)
            return f"typed:{text} (pyautogui)"
        except Exception as py_err:  # pragma: no cover - environment dependent
            logger.warning("pyautogui unavailable or failed: %s", py_err)

        # fallback to PowerShell SendKeys on Windows
        if platform.system() == 'Windows':
            try:
                esc = text.replace("'", "''")
                cmd = (
                    "powershell -NoProfile -Command "
                    f"Add-Type -AssemblyName System.Windows.Forms; "
                    f"[System.Windows.Forms.SendKeys]::SendWait('{esc}')"
                )
                subprocess.Popen(cmd, shell=True)
                return f"typed:{text} (powershell)"
            except Exception as ps_err:
                logger.exception("powershell SendKeys fallback failed")
                return f"❌ type_text failed: {ps_err}"
        return f"(no executor) typed:{text}"
    except Exception as e:
        logger.exception("type_text() failed")
        return f"❌ type_text executed failed: {e}"
