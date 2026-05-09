import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent / ".env")

from pipeline import evaluate_artifact  # noqa: E402

app = FastAPI(title="Critic Agent")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

MIN_WORDS = int(os.getenv("MIN_WORDS", "10"))
MAX_CHARS = int(os.getenv("MAX_CHARS", "15000"))


class EvaluateRequest(BaseModel):
    artifact: str


@app.get("/")
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.post("/evaluate")
async def evaluate(req: EvaluateRequest):
    text = req.artifact.strip()

    # Failure Case 3: input validation
    if not text:
        raise HTTPException(status_code=400, detail={
            "error": "empty_artifact",
            "message": "Please paste some text to evaluate.",
        })

    if len(text.split()) < MIN_WORDS:
        raise HTTPException(status_code=400, detail={
            "error": "too_short",
            "message": f"The text is too short to evaluate meaningfully. Need at least {MIN_WORDS} words.",
        })

    if len(text) > MAX_CHARS:
        raise HTTPException(status_code=400, detail={
            "error": "too_long",
            "message": f"Text exceeds the {MAX_CHARS:,} character limit. Please trim it down.",
        })

    try:
        result = await evaluate_artifact(text)
        return result.model_dump()
    except ValueError as e:
        # Stage 1 failed even after fallback to Gemini
        raise HTTPException(status_code=422, detail={
            "error": "rubric_selection_failed",
            "message": str(e),
        })
    except RuntimeError as e:
        # Missing API keys / config errors
        raise HTTPException(status_code=500, detail={
            "error": "configuration_error",
            "message": str(e),
        })
    except Exception as e:
        # Failure Case 2: both providers down (rate limit / quota)
        msg = str(e).lower()
        if "rate" in msg or "quota" in msg or "unavailable" in msg:
            raise HTTPException(status_code=503, detail={
                "error": "all_providers_unavailable",
                "message": "Both Groq and Gemini are currently unavailable. Try again in a minute.",
            })
        raise HTTPException(status_code=500, detail={
            "error": "unexpected_error",
            "message": "Something went wrong. Check the server logs.",
        })
