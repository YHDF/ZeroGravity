import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger("history_manager")
logging.basicConfig(level=logging.INFO)

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")
HISTORY_DIR_NAME = ".gemini-history"


class TurnRecord:
    def __init__(self, turn_id: str, turn_dir: str, timestamp: str, prompt: str, gemini_raw: str):
        self.turn_id = turn_id
        self.turn_dir = turn_dir
        self.timestamp = timestamp
        self.prompt = prompt
        self.gemini_raw = gemini_raw
        self.ollama_logs: List[Dict[str, Any]] = []
        self.files_written: List[Dict[str, Any]] = []
        self.commands: List[str] = []

    def log_ollama_chunk(self, file_path: str, raw_chunk: str, ollama_output: str, status: str = "success"):
        self.ollama_logs.append({
            "target_file": file_path,
            "raw_architect_chunk": raw_chunk,
            "ollama_synthesized_code": ollama_output,
            "status": status,
            "timestamp": datetime.now().isoformat(),
        })

    def save_ollama_log(self):
        log_path = os.path.join(self.turn_dir, "03_ollama_executor_log.json")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(self.ollama_logs, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write Ollama log {log_path}: {e}")

    def finalize(self, files_written: List[Dict[str, Any]], commands: List[str]):
        self.files_written = files_written
        self.commands = commands
        self.save_ollama_log()

        # Write 04_applied_files.md
        applied_md_path = os.path.join(self.turn_dir, "04_applied_files.md")
        try:
            lines = [
                f"# Applied Changes - Turn {self.turn_id}",
                f"**Timestamp**: {self.timestamp}\n",
                "## Files Written to Workspace",
            ]
            if files_written:
                for f in files_written:
                    status = f.get("status", "unknown")
                    p = f.get("path", "")
                    b = f.get("bytes_written", 0)
                    lines.append(f"- `{p}` ({status}) - {b} bytes")
            else:
                lines.append("*No files written.*")

            lines.append("\n## Shell Commands Scheduled")
            if commands:
                for c in commands:
                    lines.append(f"- `{c}`")
            else:
                lines.append("*No shell commands.*")

            with open(applied_md_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception as e:
            logger.error(f"Failed writing applied files md: {e}")


def get_history_dir(workspace_root: str = WORKSPACE_ROOT) -> str:
    h_dir = os.path.join(workspace_root, HISTORY_DIR_NAME)
    os.makedirs(h_dir, exist_ok=True)
    return h_dir


def create_turn_record(prompt: str, gemini_raw: str, workspace_root: str = WORKSPACE_ROOT) -> TurnRecord:
    history_dir = get_history_dir(workspace_root)
    turns_dir = os.path.join(history_dir, "turns")
    os.makedirs(turns_dir, exist_ok=True)

    # Determine turn number
    existing = [d for d in os.listdir(turns_dir) if os.path.isdir(os.path.join(turns_dir, d))]
    turn_num = len(existing) + 1
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    turn_id = f"turn_{turn_num:03d}_{ts_str}"

    turn_path = os.path.join(turns_dir, turn_id)
    os.makedirs(turn_path, exist_ok=True)

    # 1. Save 01_user_prompt.md
    prompt_file = os.path.join(turn_path, "01_user_prompt.md")
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(f"# User Prompt ({ts_str})\n\n{prompt}\n")

    # 2. Save 02_gemini_architect_raw.md
    gemini_file = os.path.join(turn_path, "02_gemini_architect_raw.md")
    with open(gemini_file, "w", encoding="utf-8") as f:
        f.write(f"# Gemini Architect Raw Output ({ts_str})\n\n{gemini_raw}\n")

    logger.info(f"Initialized turn record {turn_id} at {turn_path}")
    return TurnRecord(turn_id, turn_path, ts_str, prompt, gemini_raw)


def update_history_index(record: TurnRecord, workspace_root: str = WORKSPACE_ROOT):
    history_dir = get_history_dir(workspace_root)
    index_md = os.path.join(history_dir, "history_index.md")
    index_json = os.path.join(history_dir, "history_index.json")

    # Update JSON
    records_data = []
    if os.path.exists(index_json):
        try:
            with open(index_json, "r", encoding="utf-8") as f:
                records_data = json.load(f)
        except Exception:
            records_data = []

    written_paths = [f.get("path") for f in record.files_written if f.get("status") == "success"]
    records_data.append({
        "turn_id": record.turn_id,
        "timestamp": record.timestamp,
        "prompt_summary": record.prompt[:80].replace("\n", " ") + ("..." if len(record.prompt) > 80 else ""),
        "gemini_raw_chars": len(record.gemini_raw),
        "ollama_chunks_count": len(record.ollama_logs),
        "files_written": written_paths,
        "turn_dir": record.turn_dir,
    })

    with open(index_json, "w", encoding="utf-8") as f:
        json.dump(records_data, f, indent=2)

    # Update human-readable history_index.md
    table_rows = [
        "# ZeroGravity Generation Telemetry Log\n",
        "This directory tracks the handoff between Gemini (Lead Architect) and the code extractor (optional Ollama executor).\n",
        "| Turn | Timestamp | Prompt Summary | Raw Chars | Ollama Chunks | Files Written | Details |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in records_data:
        tid = r.get("turn_id", "")
        ts = r.get("timestamp", "")
        summary = r.get("prompt_summary", "").replace("|", "-")
        raw_chars = r.get("gemini_raw_chars", 0)
        chunks = r.get("ollama_chunks_count", 0)
        fw = ", ".join([os.path.basename(p) for p in r.get("files_written", [])]) or "None"
        rel_path = f"turns/{tid}/"
        table_rows.append(f"| `{tid}` | {ts} | {summary} | {raw_chars} | {chunks} | `{fw}` | [View Turn]({rel_path}) |")

    with open(index_md, "w", encoding="utf-8") as f:
        f.write("\n".join(table_rows) + "\n")

    logger.info(f"Updated history index with turn {record.turn_id}")
