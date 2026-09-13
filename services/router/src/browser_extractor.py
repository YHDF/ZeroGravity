import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger("browser_extractor")
logging.basicConfig(level=logging.INFO)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:1.5b")
WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")

# Dangerous command patterns to block during safety validation
DANGEROUS_COMMAND_PATTERNS = [
    r"\brm\s+-rf\s+/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\(\)\{\s*:\|:&\s*\};:", # fork bomb
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bchmod\s+-R\s+777\s+/",
]


def clean_web_scraping_artifacts(raw_html_or_text: str) -> str:
    """Strips common web-scraping artifacts, HTML buttons, UI labels from Gemini web output."""
    if not raw_html_or_text:
        return ""
    
    text = raw_html_or_text
    # Remove HTML tags if present while keeping code content
    # Handle pre/code tags specifically
    text = re.sub(r'<button[^>]*>.*?</button>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<div class="[^"]*action[^"]*"[^>]*>.*?</div>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<span class="[^"]*icon[^"]*"[^>]*>.*?</span>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove HTML tags if string contains HTML elements
    if "<" in text and ">" in text:
        # Convert <br> and </p> to newlines
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
        # Strip remaining HTML tags except code blocks if any
        text = re.sub(r'<pre><code[^>]*>', '```\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</code></pre>', '\n```', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
    
    # Clean UI text fragments
    ui_junk = ["Copy code", "Edit prompt", "Share & export", "View draft", "Show thinking"]
    for junk in ui_junk:
        text = text.replace(junk, "")

    return text.strip()


def validate_file_path(target_path: str, workspace_root: str = WORKSPACE_ROOT) -> tuple[bool, str]:
    """
    Validates that target_path is safe, does not attempt path traversal (../),
    and resides strictly inside workspace_root.
    """
    if not target_path or not target_path.strip():
        return False, "Empty file path specified."

    # Normalize backslashes to forward slashes for uniform path checking
    normalized = target_path.replace("\\", "/").strip()

    # Reject leading slashes for absolute paths outside workspace or Windows drive letters
    if normalized.startswith("/") and not normalized.startswith(workspace_root):
        # Allow relative paths that don't start with drive letters or root
        pass

    # Check for path traversal attempts
    path_parts = [p for p in normalized.split("/") if p]
    if ".." in path_parts:
        return False, f"Path traversal attack detected in '{target_path}'."

    if ":" in normalized and not normalized.startswith(workspace_root):
        # Windows absolute path drive letter like C:/...
        return False, f"Absolute host path outside workspace detected in '{target_path}'."

    # Resolve relative to workspace_root
    try:
        norm_workspace = os.path.normpath(workspace_root)
        if os.path.isabs(normalized):
            resolved = os.path.normpath(normalized)
        else:
            resolved = os.path.normpath(os.path.join(norm_workspace, normalized))

        if not resolved.startswith(norm_workspace):
            return False, f"Resolved path '{resolved}' escapes workspace root '{norm_workspace}'."
    except Exception as e:
        return False, f"Path validation error for '{target_path}': {e}"

    return True, "Path within workspace bounds."


def validate_commands(commands: Optional[List[str]]) -> tuple[bool, str]:
    """Validates that scheduled commands do not contain dangerous/destructive operations."""
    if not commands:
        return True, "No commands scheduled."
    for cmd in commands:
        for pattern in DANGEROUS_COMMAND_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return False, f"Dangerous command blocked: '{cmd}' matching pattern '{pattern}'."
    return True, "Commands verified safe."


import ast


def check_syntax_sanity(filepath: str, content: str) -> tuple[bool, str]:
    """Validates basic syntax sanity for Python and JSON code blocks."""
    if not content or not content.strip():
        return False, f"File '{filepath}' has empty content."

    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".py":
        try:
            ast.parse(content, filename=filepath)
        except SyntaxError as se:
            return False, f"Python SyntaxError in '{filepath}' line {se.lineno}: {se.msg}"
    elif ext == ".json":
        try:
            json.loads(content)
        except Exception as je:
            return False, f"JSON SyntaxError in '{filepath}': {je}"

    return True, "Syntax sanity check passed."



def extract_filename_from_context(preceding_text: str, first_line_of_code: str, lang: str, index: int, user_prompt: str = "") -> Optional[str]:
    """Detects filename from preceding text, first line of code, or prompt."""
    filename_pattern = r'([a-zA-Z0-9_\-./]+\.(?:py|js|ts|jsx|tsx|html|css|json|sh|bash|md|txt|yml|yaml|toml|sql|env|dockerfile|Dockerfile))'

    # 1. Check first line of code block (e.g. # main.py or // src/utils.ts or # filepath: main.py)
    if first_line_of_code:
        m = re.search(r'^(?:#|//|/\*|<!--|;\s*)\s*(?:(?:file|filename|path):\s*)?' + filename_pattern, first_line_of_code.strip(), re.IGNORECASE)
        if m:
            return m.group(1)

    # 2. Check preceding markdown context (within ~200 chars before code block)
    if preceding_text:
        # Check bold: **main.py** or `main.py` or ### main.py or File: main.py
        patterns = [
            r'\*\*(?:(?:File|file):\s*)?' + filename_pattern + r'\*\*',
            r'`' + filename_pattern + r'`',
            r'(?:(?:File|file|filename|Path|path):\s*)`?' + filename_pattern + r'`?',
            r'###?\s+`?' + filename_pattern + r'`?',
        ]
        for pat in patterns:
            matches = re.findall(pat, preceding_text, re.IGNORECASE)
            if matches:
                return matches[-1]

    # 3. Check user prompt for target filename (e.g. "Create a file main.py")
    if user_prompt:
        matches = re.findall(filename_pattern, user_prompt, re.IGNORECASE)
        if matches:
            # If multiple code blocks and prompt mentioned multiple, match by index if possible
            if index < len(matches):
                return matches[index]
            return matches[0]

    return None


def clean_code_preamble(content: str) -> str:
    """Strips conversational intro phrases and tags before the actual code starts."""
    lines = content.splitlines()
    start_idx = 0
    found = False
    for idx, line in enumerate(lines):
        l = line.strip()
        if not l:
            continue
        # Skip header metadata lines like [file-tag: ...] or bare language headers
        if re.match(r'^(?:\[file-tag:|^python$|^javascript$|^bash$|^html$)', l, re.IGNORECASE):
            continue
        # Check if line looks like actual code or valid comment
        if re.match(r'^(?:#|//|/\*|<!--|import\s+|from\s+|def\s+|class\s+|const\s+|let\s+|var\s+|function\s+|if\s+__name__|print\()', l):
            start_idx = idx
            found = True
            break
    if found and start_idx > 0:
        return "\n".join(lines[start_idx:]).strip()
    return content.strip()


def extract_code_blocks(text: str, user_prompt: str = "") -> Dict[str, Any]:
    """
    Direct, deterministic parser that extracts all code blocks and shell commands
    reliably without depending on external LLMs.
    """
    files = []
    commands = []

    ext_map = {
        "python": ".py", "py": ".py",
        "javascript": ".js", "js": ".js",
        "typescript": ".ts", "ts": ".ts",
        "html": ".html", "css": ".css",
        "json": ".json", "sh": ".sh", "bash": ".sh",
        "yaml": ".yaml", "yml": ".yml",
        "markdown": ".md", "md": ".md",
        "text": ".txt", "txt": ".txt",
        "sql": ".sql",
    }

    # Find all code blocks with their preceding context
    pattern = re.compile(r"```(?:([a-zA-Z0-9_\-]+))?(?:[ \t]+([^\n]+))?\n(.*?)```", re.DOTALL)
    
    pos = 0
    idx = 0
    for match in pattern.finditer(text):
        lang = (match.group(1) or "").strip().lower()
        fence_extra = (match.group(2) or "").strip()
        content = match.group(3)
        
        preceding_chunk = text[pos:match.start()]
        pos = match.end()

        lines = content.splitlines()
        first_line = lines[0].strip() if lines else ""

        # Determine filename
        filename = None
        # Check fence extra (e.g. ```python # main.py or ```python file:src/app.py or ../../etc/passwd)
        if fence_extra:
            m = re.search(r'(?:#|//|file:)?\s*([a-zA-Z0-9_\-./]+)', fence_extra, re.IGNORECASE)
            if m and m.group(1).strip():
                candidate = m.group(1).strip()
                if candidate not in ["python", "bash", "sh", "javascript", "js"]:
                    filename = candidate

        if not filename:
            filename = extract_filename_from_context(preceding_chunk[-300:], first_line, lang, idx, user_prompt)

        # Infer default filename if still undetected
        default_ext = ext_map.get(lang, ".py")
        if not filename:
            if default_ext == ".py":
                filename = "main.py" if idx == 0 else f"module_{idx+1}.py"
            elif default_ext == ".html":
                filename = "index.html"
            elif default_ext == ".css":
                filename = "styles.css"
            elif default_ext == ".js":
                filename = "index.js"
            elif default_ext == ".sh":
                filename = "run.sh"
            else:
                filename = f"file_{idx+1}{default_ext}"

        # Clean content
        clean_content = clean_code_preamble(content)
        if not clean_content:
            continue

        # Separate shell scripts / installation commands from regular files
        if filename.endswith(".sh") or lang in ["bash", "sh"] or any(cmd_kw in clean_content for cmd_kw in ["npm install", "pip install"]):
            for line in clean_content.splitlines():
                l = line.strip()
                if l and not l.startswith("#") and not l.startswith("//"):
                    commands.append(l)
            # If it's an explicit script file, also write the file
            if filename and filename != "run.sh":
                files.append({"path": filename, "content": clean_content})
        else:
            files.append({"path": filename, "content": clean_content})

        idx += 1

    # If no markdown fenced code blocks were found, check for "File: <path>" headers
    if not files:
        file_header_pattern = re.compile(
            r'(?:^|\n)(?:###\s*|\*\*|#\s*)?File:\s*`?([a-zA-Z0-9_\-./]+)`?',
            re.IGNORECASE
        )
        file_matches = list(file_header_pattern.finditer(text))
        if file_matches:
            for i, f_match in enumerate(file_matches):
                fpath = f_match.group(1).strip()
                content_start = f_match.end()
                if i + 1 < len(file_matches):
                    content_end = file_matches[i + 1].start()
                else:
                    content_end = len(text)

                chunk = text[content_start:content_end].strip()

                # Check if the chunk contains a command section like "Bash\n<command>"
                cmd_match = re.search(r'\n(?:Bash|Shell|Terminal)\s*\n(.*)$', chunk, re.IGNORECASE | re.DOTALL)
                if cmd_match:
                    cmd_text = cmd_match.group(1).strip()
                    for cline in cmd_text.splitlines():
                        cl = cline.strip()
                        if cl and not cl.startswith("#") and not cl.startswith("//"):
                            commands.append(cl)
                    chunk = chunk[:cmd_match.start()].strip()

                # Remove leading language name line if present (e.g. "Plaintext\n", "Python\n")
                known_langs = {
                    "python", "py", "javascript", "js", "typescript", "ts",
                    "html", "css", "json", "bash", "sh", "shell", "sql",
                    "plaintext", "text", "yaml", "yml", "markdown", "md"
                }
                lines = chunk.splitlines()
                if lines and lines[0].strip().lower() in known_langs:
                    chunk = "\n".join(lines[1:]).strip()

                clean_content = clean_code_preamble(chunk)
                if clean_content:
                    files.append({"path": fpath, "content": clean_content})

    # Fallback: only if text has real code statements (not conversational prose or system prompts)
    if not files:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        code_lines = [l for l in lines if re.match(r'^(?:def\s+|import\s+|from\s+\w+\s+import|class\s+|const\s+|let\s+|var\s+|function\s+|print\()', l)]
        if len(code_lines) >= 2 and not any(kw in text for kw in ["### Task:", "### Guidelines:", "About Gemini", "Sign in"]):
            target_name = "main.py"
            if user_prompt:
                m = re.search(r'([a-zA-Z0-9_\-./]+\.(?:py|js|ts|html|css|json|sh))', user_prompt, re.IGNORECASE)
                if m:
                    target_name = m.group(1)
            files.append({"path": target_name, "content": clean_code_preamble(text)})

    return {
        "explanation": f"Extracted {len(files)} code file(s) and {len(commands)} command(s).",
        "files_to_write": files,
        "commands_to_run": commands,
        "valid": True,
        "validation_notes": "Deterministic extraction successful.",
    }


def synthesize_chunk_with_ollama(path: str, raw_content: str, turn_record: Optional[Any] = None) -> str:
    """
    Feeds a code chunk to local Ollama (qwen2.5-coder) to produce pristine, clean code
    without conversational fluff, markdown backticks, or introductory prose.
    Logs the input and output to turn_record for auditing.
    """
    ollama_prompt = f"""You are the local code compiler and executor in the ZeroGravity pipeline.
The Lead Architect provided the following specification and code for file '{path}':

{raw_content}

Task:
Extract and output the COMPLETE, fully implemented source code for '{path}', including all imports, functions, classes, and __main__ execution blocks.
- Strip all conversational remarks, introductory text, and markdown backtick fences.
- Output pure code ready to be saved directly to the file.
- Do NOT add explanations before or after the code.
"""

    cleaned_code = ""
    status = "fallback"
    try:
        url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": ollama_prompt,
            "stream": False,
        }
        res = httpx.post(url, json=payload, timeout=90.0)
        if res.status_code == 200:
            resp_text = res.json().get("response", "").strip()
            # Strip any markdown code fence if Ollama included them
            fence_match = re.search(r"```(?:[a-zA-Z0-9_\-]+)?\n(.*?)```", resp_text, re.DOTALL)
            if fence_match:
                resp_text = fence_match.group(1).strip()
            if resp_text:
                cleaned_code = clean_code_preamble(resp_text)
                status = "success"
    except Exception as e:
        logger.warning(f"Ollama chunk synthesis error for '{path}': {e}")

    # Fallback to direct preamble cleaning if Ollama failed or returned empty
    if not cleaned_code:
        cleaned_code = clean_code_preamble(raw_content)

    if turn_record and hasattr(turn_record, "log_ollama_chunk"):
        turn_record.log_ollama_chunk(path, raw_content, cleaned_code, status=status)

    return cleaned_code


def extract_and_validate_code(
    raw_browser_output: str,
    workspace_context: Optional[Dict[str, Any]] = None,
    user_prompt: str = "",
    turn_record: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Extracts code blocks and commands from Gemini browser output.
    Sends extracted chunks through local Ollama for clean synthesis,
    logging telemetry to turn_record.
    """
    cleaned_input = clean_web_scraping_artifacts(raw_browser_output)

    # 1. Primary Chunking & Extraction
    extracted = extract_code_blocks(cleaned_input, user_prompt=user_prompt)
    raw_files = extracted.get("files_to_write", [])
    commands = extracted.get("commands_to_run", [])
    explanation = extracted.get("explanation", "Extracted code files.")

    # 2. Ollama Chunk-by-Chunk Synthesis
    processed_files = []
    for file_entry in raw_files:
        path = file_entry.get("path", "").strip()
        raw_code = file_entry.get("content", "")
        # Synthesize clean code via Ollama only for source code files
        # Plain text/config files (.txt, .json, .yaml, .md, .env) don't need code synthesis
        raw_ext = os.path.splitext(path)[1].lower()
        if raw_ext in [".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".go", ".rs", ".java", ".c", ".cpp"]:
            clean_code = synthesize_chunk_with_ollama(path, raw_code, turn_record=turn_record)
        else:
            clean_code = clean_code_preamble(raw_code)
            if turn_record and hasattr(turn_record, "log_ollama_chunk"):
                turn_record.log_ollama_chunk(path, raw_code, clean_code, status="direct_text")
        processed_files.append({"path": path, "content": clean_code})

    # 3. Path Safety & Bounds Validation
    safe_files = []
    validation_notes = []
    is_valid = True

    for file_entry in processed_files:
        path = file_entry.get("path", "").strip()
        content = file_entry.get("content", "")
        path_ok, path_msg = validate_file_path(path)
        if not path_ok:
            is_valid = False
            validation_notes.append(path_msg)
        else:
            syntax_ok, syntax_msg = check_syntax_sanity(path, content)
            if not syntax_ok:
                validation_notes.append(f"Warning: {syntax_msg}")
            safe_files.append({"path": path, "content": content})

    # 4. Command Safety Validation
    cmd_ok, cmd_msg = validate_commands(commands)
    if not cmd_ok:
        is_valid = False
        validation_notes.append(cmd_msg)

    if not validation_notes:
        validation_notes.append("All file paths and commands verified safe.")

    return {
        "explanation": explanation,
        "files_to_write": safe_files if is_valid else [],
        "commands_to_run": commands if cmd_ok else [],
        "valid": is_valid,
        "validation_notes": " | ".join(validation_notes),
    }


def fallback_regex_extraction(text: str) -> Dict[str, Any]:
    """Backwards-compatible wrapper for extract_code_blocks."""
    return extract_code_blocks(text)
