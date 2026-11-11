import os
import re
import logging
from typing import Dict, Any, Optional, List
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from browser_extractor import extract_and_validate_code, sanitize_project_name, LOCAL_AI_ENABLED
from mcp_workspace import write_to_file, run_command, clean_workspace, get_workspace_root
from history_manager import create_turn_record, update_history_index

logger = logging.getLogger("quota_router")
logging.basicConfig(level=logging.INFO)

ZEROGRAVITY_BROWSER_URL = os.environ.get("ZEROGRAVITY_BROWSER_URL", "http://gemini-bridge:5000")
ZEROGRAVITY_EXECUTION_MODE = os.environ.get("ZEROGRAVITY_EXECUTION_MODE", "direct") # 'direct' or 'agy'
ZEROGRAVITY_CLEAN_ON_NEW_CHAT = os.environ.get("ZEROGRAVITY_CLEAN_ON_NEW_CHAT", "false").lower() == "true"
# Seconds the bridge may wait for Gemini to finish; the router waits longer to cover queueing (bridge serializes prompts)
GEMINI_RESPONSE_TIMEOUT = int(os.environ.get("GEMINI_RESPONSE_TIMEOUT", "240"))
BRIDGE_HTTP_TIMEOUT = float(os.environ.get("BRIDGE_HTTP_TIMEOUT", str(GEMINI_RESPONSE_TIMEOUT * 2 + 60)))

# Tracks the most recently active project folder across multi-turn requests
_LAST_ACTIVE_PROJECT: Optional[str] = None

app = FastAPI(title="ZeroGravity Router API")


def needs_auto_project_dir() -> bool:
    """
    Returns True when WORKSPACE_PATH is the root 'workspace' directory (not already
    scoped to 'workspace/{project-name}'), so each new conversation gets its own
    project folder under /workspace/<project-name>.
    """
    explicit_env = os.environ.get("ZEROGRAVITY_AUTO_PROJECT_DIR")
    if explicit_env is not None and explicit_env.strip() != "":
        return explicit_env.strip().lower() in ("1", "true", "yes", "on")

    host_ws = os.environ.get("HOST_WORKSPACE_PATH", "").strip()
    if host_ws:
        norm = host_ws.replace("\\", "/").rstrip("/")
        basename = norm.split("/")[-1].lower() if norm else ""
        return basename == "workspace"

    ws_root = os.environ.get("WORKSPACE_ROOT", "/workspace").replace("\\", "/").rstrip("/")
    return ws_root == "/workspace"


class GenerationRequest(BaseModel):
    prompt: str
    model: Optional[str] = "zerogravity"
    execution_mode: Optional[str] = None  # overrides env if provided ('direct' or 'agy')
    workspace_context: Optional[Dict[str, Any]] = None
    new_chat: Optional[bool] = False


class GenerationResponse(BaseModel):
    status: str
    explanation: str
    execution_mode: str
    project_name: Optional[str] = None
    files_written: List[Dict[str, Any]] = []
    commands_executed: List[Dict[str, Any]] = []
    raw_browser_output: Optional[str] = None
    validation_notes: Optional[str] = None


def is_zerogravity_request(prompt: str, model: Optional[str] = None) -> bool:
    """Checks if the request is targeting ZeroGravity via persona trigger or model name."""
    if model and model.lower() in ["zerogravity", "0g"]:
        return True
    triggers = ["@0g", "@zerogravity", "zerogravity"]
    prompt_lower = prompt.lower()
    return any(trig in prompt_lower for trig in triggers)


async def execute_direct_patch(extracted_data: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Mode A: Apply extracted patches directly via MCP workspace tools."""
    files_written = []
    commands_executed = []

    for file_entry in extracted_data.get("files_to_write", []):
        path = file_entry.get("path")
        content = file_entry.get("content")
        if path and content is not None:
            res = write_to_file(path, content)
            files_written.append(res)

    cmd_root = get_workspace_root()
    project_name = extracted_data.get("project_name")
    if project_name:
        cmd_root = os.path.join(cmd_root, project_name)

    for cmd in extracted_data.get("commands_to_run", []):
        norm_cmd = cmd.strip()
        if project_name:
            # Commands already execute inside /workspace/<project_name>; skip redundant `cd <project_name>`
            # and strip `<project_name>/` prefixes from paths like `mkdir -p <project_name>/src`
            if re.match(rf"^cd\s+['\"]?(?:\./|/workspace/)?{re.escape(project_name)}/?['\"]?\s*$", norm_cmd):
                continue
            norm_cmd = re.sub(
                rf"(?<=\s)(?:\./|/workspace/)?{re.escape(project_name)}/",
                "",
                norm_cmd,
            )
            if re.match(rf"^mkdir\s+(?:-p\s+)?['\"]?(?:\./|/workspace/)?{re.escape(project_name)}/?['\"]?\s*$", norm_cmd):
                continue
        res = run_command(norm_cmd, workspace_root=cmd_root)
        commands_executed.append(res)

    return files_written, commands_executed


async def execute_agy_ingestion(extracted_data: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Mode B: Feed extracted patches into agy --mode accept-edits."""
    explanation = extracted_data.get("explanation", "")
    files = extracted_data.get("files_to_write", [])
    commands = extracted_data.get("commands_to_run", [])

    # First write files to workspace
    files_written, _ = await execute_direct_patch({"files_to_write": files, "commands_to_run": []})

    # Execute agy --mode accept-edits with instructions
    agy_cmd = f"agy --mode accept-edits --message {repr(explanation)}"
    res = run_command(agy_cmd)
    commands_executed = [res]

    # Run remaining commands if agy succeeded
    for cmd in commands:
        cmd_res = run_command(cmd)
        commands_executed.append(cmd_res)

    return files_written, commands_executed


@app.get("/healthz")
async def healthz():
    # Check connection to browser bridge
    browser_healthy = False
    browser_signed_in = None
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{ZEROGRAVITY_BROWSER_URL.rstrip('/')}/healthz", timeout=5.0)
            if res.status_code == 200:
                browser_healthy = True
                browser_signed_in = res.json().get("signed_in")
    except Exception:
        pass

    return {
        "status": "ok",
        "browser_bridge_url": ZEROGRAVITY_BROWSER_URL,
        "browser_bridge_connected": browser_healthy,
        "browser_signed_in": browser_signed_in,
        "auto_project_dir": needs_auto_project_dir(),
        "default_execution_mode": ZEROGRAVITY_EXECUTION_MODE,
        "local_ai_enabled": LOCAL_AI_ENABLED,
    }


@app.post("/generate", response_model=GenerationResponse)
@app.post("/route", response_model=GenerationResponse)
async def route_generation(req: GenerationRequest):
    global _LAST_ACTIVE_PROJECT
    if not req.prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    exec_mode = req.execution_mode or ZEROGRAVITY_EXECUTION_MODE
    ws_ctx = dict(req.workspace_context or {})
    auto_proj = bool(ws_ctx.get("auto_project_dir", needs_auto_project_dir()) or ws_ctx.get("project_name"))
    if auto_proj:
        ws_ctx["auto_project_dir"] = True
        if not req.new_chat and not ws_ctx.get("project_name") and _LAST_ACTIVE_PROJECT:
            ws_ctx["project_name"] = _LAST_ACTIVE_PROJECT

    # Step 1: Forward prompt to Headless Gemini Browser Bridge with Lead Architect conditioning
    consumer_desc = (
        "an automated local AI executor (Ollama / Qwen-Coder)"
        if LOCAL_AI_ENABLED
        else "an automated parser that writes each code block directly to disk"
    )
    if auto_proj:
        if ws_ctx.get("project_name"):
            project_instruction = (
                f'0. Active project folder inside workspace: "Project: {ws_ctx["project_name"]}". '
                'Declare "Project: ' + ws_ctx["project_name"] + '" on the first line and keep all "File: <path>" headers relative to this project root.\n'
            )
        else:
            project_instruction = (
                '0. Because WORKSPACE_PATH is not scoped to a project subfolder, you MUST choose a concise kebab-case project folder name '
                'and declare it on the very first line of your response in the exact format: "Project: <project-name>" '
                '(e.g. "Project: ts-priority-queue" or "Project: task-manager-api"). Keep all "File: <path>" headers relative to that project root.\n'
            )
    else:
        project_instruction = ""

    formatted_prompt = f"""System: You are the Lead Systems Architect in an autonomous code generation pipeline.
Your output, specifications, and code snippets are directly consumed and executed chunk-by-chunk by {consumer_desc}.
Therefore, format your instructions and code blocks clearly for the automated executor:
{project_instruction}1. For every file, clearly declare the relative path on the line immediately preceding the code block (e.g. "File: pom.xml" or "File: src/main/java/com/example/demo/UserController.java" or "File: package.json" or "File: src/index.ts").
2. Adhere to standard project directory conventions:
   - Java / Spring Boot: pom.xml or build.gradle, src/main/java/<package_path>/<ClassName>.java, src/main/resources/application.yaml, src/test/java/<package_path>/<TestClass>.java
   - TypeScript / JavaScript: package.json, tsconfig.json, src/...
   - Python: requirements.txt, src/...
3. Provide complete, fully implemented, production-ready code without ellipsis or placeholders.
4. Place any required shell commands inside separate ```bash ... ``` blocks (commands run directly inside the project root directory, so do not `mkdir <project-name>` or `cd <project-name>`).

User Request: {req.prompt}"""

    try:
        bridge_url = f"{ZEROGRAVITY_BROWSER_URL.rstrip('/')}/generate"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                bridge_url,
                json={"prompt": formatted_prompt, "new_chat": req.new_chat, "timeout": GEMINI_RESPONSE_TIMEOUT},
                timeout=BRIDGE_HTTP_TIMEOUT
            )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Browser bridge error: {resp.text}",
            )

        bridge_data = resp.json()
        raw_output = bridge_data.get("raw_output", "")

    except httpx.TimeoutException as e:
        logger.error(f"Browser bridge did not answer within {BRIDGE_HTTP_TIMEOUT}s ({type(e).__name__}).")
        raise HTTPException(
            status_code=504,
            detail=f"Gemini Browser Bridge timed out after {BRIDGE_HTTP_TIMEOUT}s ({type(e).__name__}).",
        ) from e
    except httpx.RequestError as e:
        logger.error(f"Failed to communicate with browser bridge at {ZEROGRAVITY_BROWSER_URL}: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Gemini Browser Bridge unavailable at {ZEROGRAVITY_BROWSER_URL}: {type(e).__name__}: {e}",
        ) from e

    # Step 2: Initialize telemetry turn record in .gemini-history
    turn_record = create_turn_record(req.prompt, raw_output)

    # Step 3: Extract code blocks (optional Ollama synthesis if ZEROGRAVITY_LOCAL_AI=true) & validate
    extracted_data = extract_and_validate_code(
        raw_output,
        workspace_context=ws_ctx,
        user_prompt=req.prompt,
        turn_record=turn_record,
    )
    resolved_project = extracted_data.get("project_name")
    if resolved_project:
        _LAST_ACTIVE_PROJECT = resolved_project
    logger.info(f"Raw output len: {len(raw_output)}. Project: {resolved_project}. Extracted files count: {len(extracted_data.get('files_to_write', []))}")

    if not extracted_data.get("valid", False):
        turn_record.finalize([], [])
        update_history_index(turn_record)
        return GenerationResponse(
            status="validation_failed",
            explanation=extracted_data.get("explanation", "Validation failed."),
            execution_mode=exec_mode,
            project_name=resolved_project,
            raw_browser_output=raw_output,
            validation_notes=extracted_data.get("validation_notes"),
        )

    # Step 4: Clean previous project files only when ZEROGRAVITY_CLEAN_ON_NEW_CHAT=true and not using per-project subfolders
    if req.new_chat and ZEROGRAVITY_CLEAN_ON_NEW_CHAT and not auto_proj and extracted_data.get("files_to_write"):
        clean_workspace()

    # Step 5: Execute changes based on selected strategy
    if exec_mode.lower() == "agy":
        files_written, commands_executed = await execute_agy_ingestion(extracted_data)
    else:
        files_written, commands_executed = await execute_direct_patch(extracted_data)

    # Finalize turn record and update telemetry index
    turn_record.finalize(files_written, [c.get("command", "") for c in commands_executed if isinstance(c, dict)])
    update_history_index(turn_record)

    return GenerationResponse(
        status="success",
        explanation=extracted_data.get("explanation", "Generation and execution completed."),
        execution_mode=exec_mode,
        project_name=resolved_project,
        files_written=files_written,
        commands_executed=commands_executed,
        raw_browser_output=raw_output,
        validation_notes=extracted_data.get("validation_notes"),
    )


# OpenAI Compatible endpoints for Open WebUI integration
@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "zerogravity",
                "object": "model",
                "created": 1700000000,
                "owned_by": "0g",
            },
            {
                "id": "0g",
                "object": "model",
                "created": 1700000000,
                "owned_by": "0g",
            }
        ]
    }


def is_openwebui_internal_task(prompt: str) -> bool:
    """Checks if the request is an OpenWebUI background meta-task (tags, titles, followups)."""
    markers = [
        "### Task:",
        "Suggest 3-5 relevant follow-up",
        "Generate 1-3 broad tags",
        "Generate a concise, 3-5 word title",
        '"follow_ups":',
        '"tags":',
        '"title":',
    ]
    return any(marker in prompt for marker in markers)


def extract_project_from_history(assistant_msgs: List[Dict[str, Any]]) -> Optional[str]:
    """Extracts the active project subfolder from previous assistant replies in the same conversation."""
    for msg in reversed(assistant_msgs):
        text = msg.get("content", "") or ""
        m_folder = re.search(r"ZeroGravity Project Folder:\*\*\s*`/workspace/([a-zA-Z0-9._\-]+)`", text)
        if m_folder:
            slug = sanitize_project_name(m_folder.group(1))
            if slug:
                return slug
        m_file = re.search(r"- `/workspace/([a-zA-Z0-9._\-]+)/", text)
        if m_file:
            slug = sanitize_project_name(m_file.group(1))
            if slug:
                return slug
    return None


@app.post("/v1/chat/completions")
async def chat_completions(payload: Dict[str, Any]):
    messages = payload.get("messages", [])
    model = payload.get("model", "zerogravity")

    # Extract last user message
    user_prompt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_prompt = msg.get("content", "")
            break

    if not user_prompt:
        raise HTTPException(status_code=400, detail="No user message provided.")

    # Intercept OpenWebUI background meta-tasks (tags, titles, follow-up suggestions)
    if is_openwebui_internal_task(user_prompt):
        if "title" in user_prompt.lower():
            content = '{"title": "ZeroGravity Code Generation"}'
        elif "tag" in user_prompt.lower():
            content = '{"tags": ["ZeroGravity", "Python", "Code"]}'
        elif "follow_up" in user_prompt.lower():
            content = '{"follow_ups": ["Run main.py", "Add unit tests", "Explain the algorithm"]}'
        else:
            content = '{}'

        return {
            "id": "chatcmpl-internal-task",
            "object": "chat.completion",
            "created": 1700000000,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop"
                }
            ]
        }

    # 1-to-1 sync: If there are no previous assistant replies, treat as a fresh chat
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    is_new_chat = len(assistant_msgs) == 0

    ws_ctx: Dict[str, Any] = {}
    if not is_new_chat:
        hist_proj = extract_project_from_history(assistant_msgs)
        if hist_proj:
            ws_ctx["project_name"] = hist_proj

    gen_req = GenerationRequest(
        prompt=user_prompt,
        model=model,
        new_chat=is_new_chat,
        workspace_context=ws_ctx if ws_ctx else None,
    )
    res = await route_generation(gen_req)

    reply_content = res.raw_browser_output or res.explanation
    if res.files_written:
        written_files = [f.get("path") for f in res.files_written if f.get("status") == "success"]
        if written_files:
            project_line = (
                f"📂 **ZeroGravity Project Folder:** `/workspace/{res.project_name}`\n"
                if res.project_name
                else ""
            )
            reply_content += (
                "\n\n---\n"
                + project_line
                + "📁 **ZeroGravity Workspace Files Created:**\n"
                + "\n".join([f"- `{p}`" for p in written_files])
            )
    elif res.status == "validation_failed":
        reply_content += f"\n\n---\n⚠️ **ZeroGravity Validation Warning**: {res.validation_notes}"


    return {
        "id": "chatcmpl-zerogravity-01",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": reply_content,
                },
                "finish_reason": "stop"
            }
        ]
    }



if __name__ == "__main__":
    import uvicorn
    # Container service: must listen on all interfaces
    uvicorn.run(app, host="0.0.0.0", port=8000)  # nosec B104
