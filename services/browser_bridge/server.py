import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from gemini_automator import GeminiAutomator

logger = logging.getLogger("browser_bridge_server")
logging.basicConfig(level=logging.INFO)

automator = GeminiAutomator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing GeminiAutomator browser context...")
    try:
        await automator.start()
    except Exception as e:
        logger.error(f"Failed to start GeminiAutomator: {e}")
    yield
    logger.info("Closing GeminiAutomator browser context...")
    await automator.stop()


app = FastAPI(title="ZeroGravity Gemini Web Bridge API", lifespan=lifespan)


class PromptRequest(BaseModel):
    prompt: str
    timeout: int = 120
    new_chat: bool = False


class GenerateResponse(BaseModel):
    raw_output: str
    status: str = "success"


@app.get("/healthz")
async def healthz():
    try:
        auth_status = await automator.is_authenticated()
        return {
            "status": "ok",
            "authenticated": auth_status,
            "browser_active": automator.context is not None,
        }
    except Exception as e:
        return {
            "status": "error",
            "authenticated": False,
            "error": str(e),
        }


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: PromptRequest):
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt must not be empty.")
    try:
        raw_output = await automator.send_prompt(req.prompt, timeout=req.timeout, new_chat=req.new_chat)
        return GenerateResponse(raw_output=raw_output, status="success")
    except RuntimeError as re:
        logger.error(f"Runtime error during prompt generation: {re}")
        raise HTTPException(status_code=401 if "authenticated" in str(re) else 500, detail=str(re))
    except Exception as e:
        logger.error(f"Unexpected error during prompt generation: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
