import os
import subprocess
import logging
from typing import Dict, Any

logger = logging.getLogger("mcp_workspace")
logging.basicConfig(level=logging.INFO)

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")


def get_workspace_root() -> str:
    return os.path.abspath(WORKSPACE_ROOT)


def write_to_file(path: str, content: str, workspace_root: str = WORKSPACE_ROOT) -> Dict[str, Any]:
    """Writes content to target path inside workspace root."""
    try:
        norm_workspace = os.path.abspath(workspace_root)
        if os.path.isabs(path):
            abs_path = os.path.abspath(path)
        else:
            abs_path = os.path.abspath(os.path.join(norm_workspace, path))

        if not abs_path.startswith(norm_workspace):
            raise PermissionError(f"Security error: path '{path}' escapes workspace '{norm_workspace}'.")

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Successfully wrote {len(content)} bytes to {abs_path}")
        return {"status": "success", "path": abs_path, "bytes_written": len(content)}
    except Exception as e:
        logger.error(f"Failed writing file {path}: {e}")
        return {"status": "error", "path": path, "error": str(e)}


def run_command(command: str, workspace_root: str = WORKSPACE_ROOT, timeout: int = 60) -> Dict[str, Any]:
    """Runs shell command safely inside workspace root."""
    try:
        norm_workspace = os.path.abspath(workspace_root)
        os.makedirs(norm_workspace, exist_ok=True)

        # Executing model-generated shell commands is the core purpose of direct mode.
        # Commands are screened by browser_extractor.validate_commands() before reaching here
        # and always run with cwd pinned to the workspace root.
        res = subprocess.run(  # nosec B602
            command,
            shell=True,
            cwd=norm_workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "status": "success" if res.returncode == 0 else "failed",
            "command": command,
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "command": command,
            "error": f"Command timed out after {timeout} seconds.",
        }
    except Exception as e:
        logger.error(f"Error executing command '{command}': {e}")
        return {
            "status": "error",
            "command": command,
            "error": str(e),
        }
