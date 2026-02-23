"""包级接口，导出拆分后的工具函数供旧代码使用。"""
from .process_command import process_command
from .read_file import read_file
from .open_local_app import open_local_app
# NOTE: open_app used to be a separate tool but its functionality has been
# merged into open_local_app.  The module ``open_app`` still exists for
# backward compatibility and will forward to ``open_local_app``.
from .type_text import type_text
from .press_key import press_key
from .save_note import save_note_to_desktop

# browser interaction tools
from .browse import browse
from .scan_page import scan_page
from .click_element import click_element
from .final_answer import final_answer

__all__ = [
    "process_command",
    "read_file",
    "open_local_app",
    # "open_app",  # deprecated, no longer exported by default
    "type_text",
    "press_key",
    "save_note_to_desktop",
    "browse",
    "scan_page",
    "click_element",
    "final_answer",
]
