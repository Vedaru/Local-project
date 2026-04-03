import os
import subprocess
import sys
from pathlib import Path
from typing import Dict

from app.config import config
from app.tool.base import BaseTool


class PythonExecute(BaseTool):
    """A tool for executing Python code with timeout and safety restrictions."""

    name: str = "python_execute"
    description: str = (
        "Executes Python code string. Note: Only print outputs are visible, "
        "function return values are not captured. Use print statements to see results. "
        "For PPT/Word/PDF tasks, prefer using `document_skill` first. "
        "If custom Python rendering is needed, follow a CSS-first workflow: generate "
        "a local style draft (for example theme.css) and then map it in Python to "
        "python-pptx/python-docx/reportlab objects to export binary files."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute.",
            },
        },
        "required": ["code"],
    }

    async def execute(
        self,
        code: str,
        timeout: int = 30,
    ) -> Dict:
        """
        Executes the provided Python code with a timeout.
        All file operations default to the workspace directory.

        Args:
            code (str): The Python code to execute.
            timeout (int): Execution timeout in seconds.

        Returns:
            Dict: Contains 'output' with execution output or error message and 'success' status.
        """
        # 确保workspace目录存在
        workspace_path = config.workspace_root
        workspace_path.mkdir(parents=True, exist_ok=True)

        try:
            env = os.environ.copy()
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("PYTHONUTF8", "1")
            # 设置工作目录为workspace，所有文件操作默认在这里
            env["WORKSPACE_DIR"] = str(workspace_path)

            completed = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=str(workspace_path),  # 将工作目录设为workspace
            )

            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()
            success = completed.returncode == 0

            if success:
                return {
                    "observation": stdout,
                    "success": True,
                }

            observation = stderr if stderr else stdout
            if not observation:
                observation = f"Python process exited with code {completed.returncode}"
            return {
                "observation": observation,
                "success": False,
            }
        except subprocess.TimeoutExpired:
            return {
                "observation": f"Execution timeout after {timeout} seconds",
                "success": False,
            }
