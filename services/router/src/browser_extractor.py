import os
import re
import ast
import json
import logging
from typing import Dict, Any, List, Optional
import httpx

# LLM output is untrusted: use defusedxml to guard against XML entity-expansion attacks
from defusedxml import ElementTree as ET

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger("browser_extractor")
logging.basicConfig(level=logging.INFO)

# Optional local AI (Ollama) post-processing stage. Disabled by default:
# code blocks extracted from Gemini are cleaned deterministically and written as-is.
# Set ZEROGRAVITY_LOCAL_AI=true (and start the 'local-ai' compose profile) to re-enable.
LOCAL_AI_ENABLED = os.environ.get("ZEROGRAVITY_LOCAL_AI", "false").strip().lower() in ("1", "true", "yes", "on")
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

    # Remove HTML tags if string contains actual HTML elements (avoiding '<' and '>' comparison/arrow operators in code)
    if re.search(r'</?(?:div|span|p|br|pre|code|button|a|ul|ol|li|h[1-6]|strong|em|b|i|table|tr|td|th|section|article|header|footer)\b[^>]*>', text, flags=re.IGNORECASE):
        # Convert <br> and </p> to newlines
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
        # Strip remaining HTML tags except code blocks if any
        text = re.sub(r'<pre><code[^>]*>', '```\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</code></pre>', '\n```', text, flags=re.IGNORECASE)
        text = re.sub(
            r'</?(?:div|span|p|br|pre|code|button|a|ul|ol|li|h[1-6]|strong|em|b|i|table|tr|td|th|section|article|header|footer)\b[^>\n]*>',
            '',
            text,
            flags=re.IGNORECASE,
        )

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


def resolve_java_path(declared_path: str, content: str) -> str:
    """
    If a Java file path is not fully structured (e.g. 'UserController.java' or 'src/UserController.java'),
    inspects 'package com.example.demo.controller;' and maps it to standard Maven convention:
    'src/main/java/com/example/demo/controller/UserController.java' (or src/test/java/ for tests).
    """
    if not declared_path.endswith(".java"):
        return declared_path

    # If it's already a full maven/gradle path, keep it
    if declared_path.startswith("src/main/java/") or declared_path.startswith("src/test/java/"):
        return declared_path

    pkg_match = re.search(r'^\s*package\s+([a-zA-Z0-9_.]+)\s*;', content, re.MULTILINE)
    if not pkg_match:
        return declared_path

    pkg_parts = pkg_match.group(1).split(".")
    pkg_dir = "/".join(pkg_parts)
    filename = os.path.basename(declared_path)

    # Check if it is a test class
    is_test = (
        "Test" in filename or
        bool(re.search(r'@(?:Test|SpringBootTest)', content)) or
        "tests/" in declared_path or
        "test/" in declared_path
    )
    root_dir = "src/test/java" if is_test else "src/main/java"
    return f"{root_dir}/{pkg_dir}/{filename}"


GENERIC_TOP_DIRS = {
    "src", "test", "tests", "lib", "app", "config", "configs", "public",
    "static", "assets", "dist", "build", "target", "out", "bin", "scripts",
    "docs", "doc", "examples", "resources", "cmd", "internal", "pkg", ".github",
}

PROMPT_STOPWORDS = {
    "create", "build", "write", "make", "generate", "implement", "develop",
    "please", "you", "must", "following", "files", "file", "separate", "project",
    "application", "app", "service", "the", "and", "for", "with", "using",
    "under", "base", "package", "that", "from", "into", "new", "simple", "modular",
}


def sanitize_project_name(candidate: str) -> Optional[str]:
    """Normalizes a candidate project folder name into a safe kebab-case directory slug."""
    if not candidate:
        return None
    cleaned = candidate.strip().strip("`'\"/*# ")
    if cleaned.lower().startswith("workspace/"):
        cleaned = cleaned.split("/", 1)[1]
    cleaned = cleaned.split("/")[0].strip()
    if cleaned.startswith("@") and "/" in candidate:
        cleaned = candidate.split("/")[-1].strip()
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", cleaned).strip("-._").lower()
    if not slug or slug in GENERIC_TOP_DIRS or slug in {"workspace", "project", "default", "none", "null"}:
        return None
    if len(slug) > 60:
        slug = slug[:60].rstrip("-._")
    return slug or None


def resolve_project_name(
    raw_text: str,
    files_to_write: List[Dict[str, str]],
    user_prompt: str = "",
    explicit_project: Optional[str] = None,
) -> str:
    """
    Determines the project subfolder name under /workspace/<project-name> from:
    1. Explicit project name in workspace_context (e.g. Turn 2+ of same conversation)
    2. Explicit folder in user_prompt (e.g. 'workspace/my-app' or 'Project: my-app')
    3. Gemini's 'Project: <project-name>' header
    4. Existing non-generic top-level folder shared by all extracted file paths
    5. Project manifest files (package.json name, pom.xml artifactId, settings.gradle, application.yaml)
    6. Fallback slug derived from user_prompt
    """
    # 1. Explicit project from workspace_context
    slug = sanitize_project_name(explicit_project or "")
    if slug:
        return slug

    # 2. Explicit workspace/<folder> or Project: <folder> in user_prompt
    if user_prompt:
        m_ws = re.search(r"(?:workspace[\\/]|(?:\bproject|\bfolder)\s*(?:name)?\s*[:=]\s*`?)([a-zA-Z0-9][a-zA-Z0-9_-]{1,50})", user_prompt, re.IGNORECASE)
        if m_ws:
            slug = sanitize_project_name(m_ws.group(1))
            if slug:
                return slug

    # 3. Gemini's 'Project: <project-name>' header in raw output
    if raw_text:
        m_proj = re.search(
            r"(?:^|\n)\s*(?:###?\s*|\*\*|#\s*)?Project(?:\s+Name|\s+Folder)?\s*:\s*`?([a-zA-Z0-9][a-zA-Z0-9._\-]{1,60})`?",
            raw_text,
            re.IGNORECASE,
        )
        if m_proj:
            slug = sanitize_project_name(m_proj.group(1))
            if slug:
                return slug

    # 4. Check if all extracted files already share a non-generic top-level directory
    top_dirs = set()
    all_have_top_dir = bool(files_to_write)
    for f in files_to_write:
        norm = f.get("path", "").replace("\\", "/").lstrip("/")
        parts = [p for p in norm.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() not in GENERIC_TOP_DIRS:
            top_dirs.add(parts[0])
        else:
            all_have_top_dir = False
            break
    if all_have_top_dir and len(top_dirs) == 1:
        slug = sanitize_project_name(next(iter(top_dirs)))
        if slug:
            return slug

    # 5. Inspect manifest files (package.json, pom.xml, application.yaml)
    for f in files_to_write:
        bname = os.path.basename(f.get("path", "")).lower()
        content = f.get("content", "")
        if bname == "package.json":
            try:
                pkg = json.loads(content)
                slug = sanitize_project_name(str(pkg.get("name", "")))
                if slug:
                    return slug
            except Exception:
                pass
        elif bname == "pom.xml":
            m_art = re.search(r"<artifactId>\s*([a-zA-Z0-9._\-]+)\s*</artifactId>", content)
            if m_art:
                slug = sanitize_project_name(m_art.group(1))
                if slug and "spring-boot" not in slug:
                    return slug
        elif bname in ("application.yaml", "application.yml"):
            m_app = re.search(r"name\s*:\s*['\"]?([a-zA-Z0-9._\-]+)['\"]?", content)
            if m_app:
                slug = sanitize_project_name(m_app.group(1))
                if slug:
                    return slug

    # 6. Derive slug from user_prompt keywords
    if user_prompt:
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", user_prompt.lower())
        keywords = [w for w in words if w not in PROMPT_STOPWORDS][:3]
        if keywords:
            slug = sanitize_project_name("-".join(keywords))
            if slug:
                return slug

    return "zerogravity-project"


def check_syntax_sanity(filepath: str, content: str) -> tuple[bool, str]:
    """Validates syntax sanity for Python, JSON, YAML, XML (pom.xml), Java, and JS/TS."""
    if not content or not content.strip():
        return False, f"File '{filepath}' has empty content."

    ext = os.path.splitext(filepath)[1].lower()
    basename = os.path.basename(filepath).lower()

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
    elif ext in [".yaml", ".yml"]:
        if yaml:
            try:
                yaml.safe_load(content)
            except Exception as ye:
                return False, f"YAML SyntaxError in '{filepath}': {ye}"
    elif ext == ".xml" or basename == "pom.xml":
        try:
            ET.fromstring(content)
        except Exception as xe:
            return False, f"XML SyntaxError in '{filepath}': {xe}"
    elif ext in [".js", ".jsx", ".ts", ".tsx", ".java"]:
        brace_count = content.count("{") - content.count("}")
        if abs(brace_count) > 10:
            return False, f"Syntax warning in '{filepath}': Unbalanced curly braces (diff={brace_count})."

    return True, "Syntax sanity check passed."



def normalize_declared_filepath(raw_path: str) -> str:
    """
    Normalizes a declared file path from Gemini output.
    Restores Python `__init__.py` when Markdown bold formatting stripped
    double underscores from `File: src/__init__.py` -> `File: src/init.py`.
    """
    cleaned = raw_path.strip().strip("`'\"*").replace("\\", "/")
    cleaned = re.sub(r"/init\.py$", "/__init__.py", cleaned)
    return cleaned


def extract_filename_from_context(preceding_text: str, first_line_of_code: str, lang: str, index: int, user_prompt: str = "") -> Optional[str]:
    """Detects filename from preceding text, first line of code, or prompt."""
    filename_pattern = (
        r'((?:\.?[a-zA-Z0-9_\-]+/)*'
        r'(?:\.[a-zA-Z0-9_\-.]+|[a-zA-Z0-9_\-.]+\.(?:json|jsx|js|tsx|ts|yaml|yml|html|css|py|sh|bash|md|markdown|txt|toml|ini|cfg|conf|sql|java|xml|gradle|properties|env|example|local|dockerfile|Dockerfile|gitignore|dockerignore))'
        r'(?![a-zA-Z0-9_]))'
    )

    # 1. Check first line of code block (e.g. # main.py or // src/utils.ts or # filepath: main.py)
    if first_line_of_code:
        m = re.search(r'^(?:#|//|/\*|<!--|;\s*)\s*(?:(?:file|filename|path):\s*)?' + filename_pattern, first_line_of_code.strip(), re.IGNORECASE)
        if m:
            return normalize_declared_filepath(m.group(1))

    # 2. Check preceding markdown context (within ~300 chars before code block)
    if preceding_text:
        # Check bold: **main.py** or `main.py` or ### main.py or File: main.py
        if lang in ("bash", "sh", "shell", "zsh", "console"):
            patterns = [
                r'(?:(?:File|file|filename|Path|path):\s*)`?' + filename_pattern + r'`?',
            ]
        else:
            patterns = [
                r'(?:(?:File|file|filename|Path|path):\s*)`?([^\s`\'\"*<>|]+)`?',
                r'\*\*(?:(?:File|file):\s*)?' + filename_pattern + r'\*\*',
                r'`' + filename_pattern + r'`',
                r'###?\s+`?' + filename_pattern + r'`?',
            ]
        for pat in patterns:
            matches = re.findall(pat, preceding_text, re.IGNORECASE)
            if matches:
                return normalize_declared_filepath(matches[-1])

    # Unlabelled shell blocks are command blocks, not source files from user_prompt
    if lang in ("bash", "sh", "shell", "zsh", "console"):
        return None

    # 3. Check user prompt for target filename (e.g. "Create a file main.py")
    if user_prompt:
        matches = re.findall(filename_pattern, user_prompt, re.IGNORECASE)
        if matches and index < len(matches):
            return normalize_declared_filepath(matches[index])

    return None


def clean_code_preamble(content: str) -> str:
    """Strips conversational intro phrases and tags before the actual code starts."""
    lines = content.splitlines()
    start_idx = 0
    found = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip header metadata lines like [file-tag: ...] or bare language headers
        if re.match(r'^(?:\[file-tag:|^python$|^javascript$|^typescript$|^java$|^bash$|^html$|^css$|^json$|^yaml$|^xml$|^plaintext$|^ini$|^markdown$)', stripped, re.IGNORECASE):
            continue
        # Check if line looks like actual code, docstring, config assignment, markup, or valid comment
        if re.match(
            r'^(?:#|//|/\*|<!--|"""|\'\'\'|import\s+|from\s+|export\s+|package\s+|@\w+|def\s+|class\s+|async\s+|public\s+|private\s+|protected\s+|const\s+|let\s+|var\s+|function\s+|type\s+|interface\s+|if\s+__name__|print\(|<[a-zA-Z0-9_!\-]+|\{|\[|[a-zA-Z0-9_.\-]+\s*(?:[:=]|[><=!~]=))',
            stripped
        ):
            start_idx = idx
            found = True
            break
    if found and start_idx > 0:
        return "\n".join(lines[start_idx:]).strip()
    return content.strip()


# Matches fenced code blocks of 3+ backticks even when the language tag has trailing commas/metadata (e.g. ```ini,)
FENCE_BLOCK_RE = re.compile(
    r"(`{3,})([a-zA-Z0-9_+#.\-]*)[ \t,;:]*([^\n]*)\n(.*?)\1",
    re.DOTALL,
)

KNOWN_LANG_HEADERS = {
    "python", "py", "javascript", "js", "typescript", "ts", "jsx", "tsx",
    "java", "html", "css", "json", "bash", "sh", "shell", "sql",
    "plaintext", "text", "yaml", "yml", "xml", "properties", "gradle", "groovy",
    "markdown", "md", "ini", "toml", "dotenv", "env",
}


def _extract_shell_commands(cmd_block: str, commands: List[str]) -> None:
    """Appends non-comment lines from a shell block to `commands`."""
    for line in cmd_block.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
            commands.append(stripped)


def _find_valid_file_headers(text: str) -> List[re.Match]:
    """
    Finds top-level `File: <path>` section headers that are followed by either
    a fenced code block or a known language label line.
    """
    header_re = re.compile(
        r'(?:^|\n)[ \t]*(?:###?\s*|\*\*|#\s*)?(?:File|Filename|Path)\s*:\s*`?([a-zA-Z0-9_.\-/\\]+)`?\s*\*?\*?[ \t]*(?=\n|$)',
        re.IGNORECASE,
    )
    valid_headers: List[re.Match] = []
    for m in header_re.finditer(text):
        rest = text[m.end():].lstrip("\r\n ")
        if not rest:
            continue
        first_line = rest.splitlines()[0].strip()
        first_token = re.split(r"[\s,;:]+", first_line)[0].lower() if first_line else ""
        if first_line.startswith("```") or first_token in KNOWN_LANG_HEADERS:
            valid_headers.append(m)
    return valid_headers


def extract_code_blocks(text: str, user_prompt: str = "") -> Dict[str, Any]:
    """
    Direct, deterministic parser that extracts all code blocks and shell commands
    reliably without depending on external LLMs.
    Isolates each `File: <path>` section first when present so a malformed or nested
    fence in one file can never shift or corrupt subsequent files.
    """
    files = []
    commands = []

    ext_map = {
        "python": ".py", "py": ".py",
        "javascript": ".js", "js": ".js",
        "typescript": ".ts", "ts": ".ts",
        "jsx": ".jsx", "tsx": ".tsx",
        "java": ".java",
        "html": ".html", "css": ".css",
        "json": ".json", "sh": ".sh", "bash": ".sh",
        "yaml": ".yaml", "yml": ".yml",
        "xml": ".xml", "properties": ".properties", "gradle": ".gradle", "groovy": ".gradle",
        "markdown": ".md", "md": ".md",
        "text": ".txt", "txt": ".txt", "plaintext": ".txt",
        "ini": ".ini", "toml": ".toml",
        "sql": ".sql",
    }

    # Strategy 1: Section-isolated extraction when `File: <path>` headers are present
    file_headers = _find_valid_file_headers(text)
    if file_headers:
        # 1a. Extract any setup shell blocks appearing before the first `File:` header
        preamble_text = text[:file_headers[0].start()]
        for m in FENCE_BLOCK_RE.finditer(preamble_text):
            lang = (m.group(2) or "").strip().lower()
            body = m.group(4).strip()
            if lang in ("bash", "sh", "shell", "zsh", "console") or any(
                kw in body for kw in ("pip install", "npm install", "python3 -m venv")
            ):
                _extract_shell_commands(body, commands)

        # 1b. Parse each `File: <path>` section in complete isolation
        for i, h_match in enumerate(file_headers):
            fpath = normalize_declared_filepath(h_match.group(1))
            sec_start = h_match.end()
            sec_end = file_headers[i + 1].start() if (i + 1 < len(file_headers)) else len(text)
            chunk = text[sec_start:sec_end].strip()

            is_last_section = (i + 1 == len(file_headers))
            is_markdown_file = fpath.lower().endswith((".md", ".markdown"))

            if is_markdown_file:
                # If the last section is a Markdown file followed by a standalone trailing
                # ```bash ... ``` block after the README's closing ``` fence, peel that off first
                if is_last_section:
                    trailing_bash = re.search(
                        r"\n`{3,}\s*\n`{3,}(?:bash|sh|shell)[ \t]*\n(.*?)`{3,}\s*$",
                        chunk,
                        re.IGNORECASE | re.DOTALL,
                    )
                    if trailing_bash:
                        _extract_shell_commands(trailing_bash.group(1), commands)
                        chunk = chunk[:trailing_bash.start()].strip()

                # Strip outer ```markdown / ```md fence wrapping the README content
                chunk = re.sub(r"^`{3,}(?:markdown|md)?[^\n]*\n", "", chunk, flags=re.IGNORECASE)
                chunk = re.sub(r"\n`{3,}\s*$", "", chunk)
                if chunk.strip():
                    files.append({"path": fpath, "content": chunk.strip()})
                continue

            # Non-markdown file section: extract first fenced code block if present
            fenced_matches = list(FENCE_BLOCK_RE.finditer(chunk))
            if fenced_matches:
                primary = fenced_matches[0]
                primary_lang = (primary.group(2) or "").strip().lower()
                primary_body = primary.group(4).strip()
                clean_body = (
                    primary_body
                    if fpath.lower().endswith((".txt", ".env", ".example", ".ini", ".cfg", ".conf", ".properties"))
                    else clean_code_preamble(primary_body)
                )
                if clean_body:
                    if fpath.endswith(".sh") or primary_lang in ("bash", "sh", "shell"):
                        _extract_shell_commands(clean_body, commands)
                        if fpath != "run.sh":
                            files.append({"path": fpath, "content": clean_body})
                    else:
                        files.append({"path": fpath, "content": clean_body})

                # Any subsequent fenced bash/sh block in this section (e.g. after the last file)
                for extra_m in fenced_matches[1:]:
                    extra_lang = (extra_m.group(2) or "").strip().lower()
                    extra_body = extra_m.group(4).strip()
                    if extra_lang in ("bash", "sh", "shell", "zsh", "console") or any(
                        kw in extra_body for kw in ("npm install", "pip install", "mvn ", "gradle ", "pytest")
                    ):
                        _extract_shell_commands(extra_body, commands)
            else:
                # Unfenced section (or unclosed fence): strip trailing `Bash\n<cmds>` and leading language line
                cmd_match = re.search(r"\n(?:Bash|Shell|Terminal)\s*\n(.*)$", chunk, re.IGNORECASE | re.DOTALL)
                if cmd_match:
                    _extract_shell_commands(cmd_match.group(1).strip(), commands)
                    chunk = chunk[:cmd_match.start()].strip()

                chunk = re.sub(r"^`{3,}[^\n]*\n", "", chunk)
                chunk = re.sub(r"\n`{3,}\s*$", "", chunk)
                lines = chunk.splitlines()
                if lines and lines[0].strip().lower() in KNOWN_LANG_HEADERS:
                    chunk = "\n".join(lines[1:]).strip()

                clean_body = (
                    chunk.strip()
                    if fpath.lower().endswith((".txt", ".env", ".example", ".ini", ".cfg", ".conf", ".properties"))
                    else clean_code_preamble(chunk)
                )
                if clean_body:
                    files.append({"path": fpath, "content": clean_body})

        return {
            "explanation": f"Extracted {len(files)} code file(s) and {len(commands)} command(s).",
            "files_to_write": files,
            "commands_to_run": commands,
            "valid": True,
            "validation_notes": "Deterministic extraction successful.",
        }

    # Strategy 2: Fenced code block scan when no `File: <path>` section headers exist
    pos = 0
    file_idx = 0
    for match in FENCE_BLOCK_RE.finditer(text):
        lang = (match.group(2) or "").strip().lower()
        fence_extra = (match.group(3) or "").strip()
        content = match.group(4)

        preceding_chunk = text[pos:match.start()]
        pos = match.end()

        lines = content.splitlines()
        first_line = lines[0].strip() if lines else ""

        # Clean content early to inspect class/package if needed
        clean_content = clean_code_preamble(content)
        if not clean_content:
            continue

        # Determine filename
        filename = None
        # Check fence extra (e.g. ```python # main.py or ```python file:src/app.py or ../../etc/passwd)
        if fence_extra:
            m = re.search(r'(?:#|//|file:)?\s*([a-zA-Z0-9_\-./]+)', fence_extra, re.IGNORECASE)
            if m and m.group(1).strip():
                candidate = m.group(1).strip()
                if candidate not in ["python", "bash", "sh", "javascript", "js", "typescript", "ts", "java"]:
                    filename = normalize_declared_filepath(candidate)

        if not filename:
            filename = extract_filename_from_context(preceding_chunk[-300:], first_line, lang, file_idx, user_prompt)

        is_shell_block = (
            (filename and filename.endswith(".sh"))
            or lang in ["bash", "sh", "shell", "zsh", "console"]
            or (not filename and any(cmd_kw in clean_content for cmd_kw in ["npm install", "pip install"]))
        )

        # Infer default filename if still undetected and not a pure command block
        default_ext = ext_map.get(lang, ".py")
        if not filename and not is_shell_block:
            if default_ext == ".py":
                filename = "main.py" if file_idx == 0 else f"module_{file_idx+1}.py"
            elif default_ext in [".ts", ".tsx"]:
                filename = "src/index.ts" if file_idx == 0 else f"src/module_{file_idx+1}.ts"
            elif default_ext in [".js", ".jsx"]:
                filename = "src/index.js" if file_idx == 0 else f"src/module_{file_idx+1}.js"
            elif default_ext == ".java":
                cm = re.search(r'public\s+(?:class|interface|record|enum)\s+([a-zA-Z0-9_]+)', clean_content)
                if cm:
                    filename = f"{cm.group(1)}.java"
                else:
                    filename = f"Class_{file_idx+1}.java"
            elif default_ext in [".yaml", ".yml"]:
                filename = "application.yaml" if any(k in text.lower() for k in ["spring", "server:"]) else "config.yaml"
            elif default_ext == ".json":
                filename = "package.json" if "dependencies" in clean_content else f"data_{file_idx+1}.json"
            elif default_ext == ".gradle":
                filename = "build.gradle"
            elif default_ext == ".xml":
                filename = "pom.xml" if "modelVersion" in clean_content else f"config_{file_idx+1}.xml"
            elif default_ext == ".html":
                filename = "index.html"
            elif default_ext == ".css":
                filename = "styles.css"
            else:
                filename = f"file_{file_idx+1}{default_ext}"

        if is_shell_block:
            _extract_shell_commands(clean_content, commands)
            if filename and filename != "run.sh" and filename.endswith((".sh", ".bash")):
                files.append({"path": filename, "content": clean_content})
        else:
            files.append({"path": filename, "content": clean_content})
            file_idx += 1

    # Fallback: only if text has real code statements (not conversational prose or system prompts)
    if not files:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        code_lines = [ln for ln in lines if re.match(r'^(?:def\s+|import\s+|from\s+\w+\s+import|class\s+|const\s+|let\s+|var\s+|function\s+|print\()', ln)]
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
Extract and output the COMPLETE, fully implemented source code for '{path}'.
- For Java / Spring: preserve exact package declarations, all imports, Spring annotations (@SpringBootApplication, @RestController, @Service, etc.), classes, methods.
- For TypeScript / JavaScript: preserve all imports, export statements, type/interface declarations, functions, components.
- For Python: preserve all imports, functions, classes, and execution blocks.
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
    If the optional local AI stage is enabled (ZEROGRAVITY_LOCAL_AI=true), code chunks
    are sent through local Ollama for clean synthesis; otherwise they are cleaned
    deterministically. Telemetry is logged to turn_record.
    """
    cleaned_input = clean_web_scraping_artifacts(raw_browser_output)

    # 1. Primary Chunking & Extraction
    extracted = extract_code_blocks(cleaned_input, user_prompt=user_prompt)
    raw_files = extracted.get("files_to_write", [])
    commands = extracted.get("commands_to_run", [])
    explanation = extracted.get("explanation", "Extracted code files.")

    # 2. Chunk-by-Chunk Cleanup (optional Ollama synthesis when LOCAL_AI_ENABLED)
    processed_files = []
    code_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java",
        ".go", ".rs", ".c", ".cpp", ".cs", ".php", ".rb"
    }

    for file_entry in raw_files:
        path = file_entry.get("path", "").strip()
        raw_code = file_entry.get("content", "")

        raw_ext = os.path.splitext(path)[1].lower()
        if LOCAL_AI_ENABLED and raw_ext in code_extensions:
            clean_code = synthesize_chunk_with_ollama(path, raw_code, turn_record=turn_record)
        else:
            clean_code = clean_code_preamble(raw_code)
            if turn_record and hasattr(turn_record, "log_ollama_chunk"):
                turn_record.log_ollama_chunk(path, raw_code, clean_code, status="direct_text")

        # Resolve Java package directory hierarchy if needed (e.g. UserController.java -> src/main/java/com/example/demo/...)
        if path.endswith(".java"):
            path = resolve_java_path(path, clean_code)

        processed_files.append({"path": path, "content": clean_code})

    # 2b. Automatic project subfolder scoping under /workspace/<project-name> when enabled
    ctx = workspace_context or {}
    auto_project_dir = bool(ctx.get("auto_project_dir", False) or ctx.get("project_name"))
    project_name: Optional[str] = None
    if auto_project_dir and processed_files:
        project_name = resolve_project_name(
            cleaned_input,
            processed_files,
            user_prompt=user_prompt,
            explicit_project=ctx.get("project_name"),
        )
        if project_name:
            for file_entry in processed_files:
                norm_p = file_entry["path"].replace("\\", "/").lstrip("/")
                if norm_p.startswith("workspace/"):
                    norm_p = norm_p[len("workspace/"):]
                if not norm_p.startswith(f"{project_name}/"):
                    file_entry["path"] = f"{project_name}/{norm_p}"
                else:
                    file_entry["path"] = norm_p

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
        "project_name": project_name,
        "files_to_write": safe_files if is_valid else [],
        "commands_to_run": commands if cmd_ok else [],
        "valid": is_valid,
        "validation_notes": " | ".join(validation_notes),
    }


def fallback_regex_extraction(text: str) -> Dict[str, Any]:
    """Backwards-compatible wrapper for extract_code_blocks."""
    return extract_code_blocks(text)
