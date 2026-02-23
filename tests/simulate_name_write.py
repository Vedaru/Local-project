import sys, json, os
sys.path.append(r'd:\Personal_Files\Projects\Github\Local-project')
from modules.agent import agent_tools, core

responses = []
responses.append(json.dumps({"thought":"open","tool":"open_local_app","args":"notepad"}))
responses.append("写好啦~我的名字是洛可！[开心]")
responses.append(json.dumps({"thought":"","tool":"final_answer","args":"done"}))

count = 0

def fake_llm(sp, mn, prompt, mc=""):
    global count
    out = responses[count]
    count += 1
    return out

at = agent_tools.AgentTools()
# provide dummy executor so type_text will "work"
class DummyExec:
    def __init__(self):
        try:
            import pyautogui
            self._gui = pyautogui
        except ImportError:
            self._gui = None
    def type_text(self, text):
        print(f"[DummyExec] typing: {text}")
        # try pyautogui first
        if self._gui:
            try:
                # bring notepad window to front if possible
                try:
                    wins = self._gui.getWindowsWithTitle('无标题') or self._gui.getWindowsWithTitle('Notepad')
                    if wins:
                        wins[0].activate()
                        self._gui.sleep(0.5)
                except Exception:
                    pass
                self._gui.write(text)
                return f"typed:{text}"
            except Exception as e:
                print(f"pyautogui error {e}")
        # fallback: send via PowerShell AppActivate+SendKeys
        try:
            # attempt to activate notepad by title
            ps = (
                "$ws = New-Object -ComObject WScript.Shell;"
                "$ws.AppActivate('无标题 - 记事本')|Out-Null;"
                f"$ws.SendKeys('{text}')"
            )
            os.system(f"powershell -Command \"{ps}\"")
            return f"typed_via_powershell:{text}"
        except Exception as e:
            return f"typed_failed:{e}"
    # open_app may be called by open_local_app fallback
    def open_app(self, path, maximize=False):
        print(f"[DummyExec] opening {path}")
        try:
            os.startfile(path)
            return f"opened:{path}"
        except Exception as e:
            return f"open_failed:{e}"
# although we have a DummyExec defined above, the new tools no longer
# require any executor at all.  We assign None for clarity.
at.action_executor = None
print("[simulate_name_write] running with built-in tools (no executor)")
ag = core.ManusAgent(fake_llm, at, 'test')
print('starting run')
res = ag.run_task('open and write name')
print('result', res)
print('file exists', os.path.exists('note.txt'))
if os.path.exists('note.txt'):
    print('content', open('note.txt','r',encoding='utf-8').read())
