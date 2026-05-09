import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import evaluate_artifact

app = FastAPI(title="Critic Agent")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# Serve frontend static files
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

MIN_WORDS = 30
MAX_CHARS = 15000


class EvaluateRequest(BaseModel):
    artifact: str


@app.get("/")
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.post("/evaluate")
def evaluate(req: EvaluateRequest):
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
        result = evaluate_artifact(text)
        return result
    except ValueError as e:
        # Rubric selection failed even after Gemini fallback
        raise HTTPException(status_code=422, detail={
            "error": "rubric_selection_failed",
            "message": str(e),
        })
    except RuntimeError as e:
        # Missing API keys
        raise HTTPException(status_code=500, detail={
            "error": "configuration_error",
            "message": str(e),
        })
    except Exception as e:
        # Failure Case 2: both providers unavailable
        if "rate" in str(e).lower() or "quota" in str(e).lower() or "unavailable" in str(e).lower():
            raise HTTPException(status_code=503, detail={
                "error": "all_providers_unavailable",
                "message": "Both Groq and Gemini are currently unavailable. Try again in a minute.",
            })
        raise HTTPException(status_code=500, detail={
            "error": "unexpected_error",
            "message": "Something went wrong. Check the server logs.",
        })
