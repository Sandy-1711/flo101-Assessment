import json
import os
import re
import time
from pathlib import Path

import groq as groq_sdk
import google.generativeai as genai
from dotenv import load_dotenv

from prompts import (
    RUBRIC_SELECTION_SYSTEM,
    RUBRIC_SELECTION_USER,
    SCORING_SYSTEM,
    SCORING_USER,
)

load_dotenv()

# --- Config ---
N_SCORING_RUNS = 3          # set to 1 for faster demos
MIN_RUBRICS = 3
MAX_RUBRICS = 6
SELECTION_MODEL = "llama-3.1-8b-instant"
SCORING_MODEL = "llama-3.1-8b-instant"
GEMINI_MODEL = "gemini-2.0-flash-lite"
SELECTION_TEMPERATURE = 0.4
SCORING_TEMPERATURE = 0.2
TIMEOUT_SECONDS = 30

# --- Client init ---
_groq_client = None
_gemini_model = None


def _get_groq():
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set")
        _groq_client = groq_sdk.Groq(api_key=api_key)
    return _groq_client


def _get_gemini():
    global _gemini_model
    if _gemini_model is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)
        _gemini_model = genai.GenerativeModel(GEMINI_MODEL)
    return _gemini_model


def _strip_fences(text: str) -> str:
    """Strip markdown code fences that models sometimes wrap around JSON."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _call_groq(system: str, user: str, temperature: float) -> str:
    client = _get_groq()
    resp = client.chat.completions.create(
        model=SCORING_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=512,
        timeout=TIMEOUT_SECONDS,
    )
    return resp.choices[0].message.content


def _call_gemini(system: str, user: str) -> str:
    model = _get_gemini()
    prompt = f"{system}\n\n{user}"
    resp = model.generate_content(prompt)
    return resp.text


def _llm_call(system: str, user: str, temperature: float, use_gemini: bool = False) -> str:
    """Call Groq by default, fall back to Gemini on rate limit or timeout."""
    if use_gemini:
        return _call_gemini(system, user)

    try:
        return _call_groq(system, user, temperature)
    except groq_sdk.RateLimitError:
        return _call_gemini(system, user)
    except groq_sdk.APITimeoutError:
        time.sleep(2)
        try:
            return _call_groq(system, user, temperature)
        except Exception:
            return _call_gemini(system, user)


def _load_rubrics() -> list[dict]:
    path = Path(__file__).parent / "rubrics.json"
    with open(path) as f:
        return json.load(f)["rubrics"]


def select_rubrics(artifact: str) -> dict:
    """
    Stage 1: Ask a small model which rubrics are relevant for this artifact.
    Returns {"selected_rubric_ids": [...], "reasoning": "..."}
    Raises ValueError if rubric selection fails after Gemini fallback.
    """
    rubrics = _load_rubrics()
    rubrics_list = "\n".join(
        f"- id: {r['id']} | name: {r['name']} | description: {r['description']}"
        for r in rubrics
    )
    user_msg = RUBRIC_SELECTION_USER.format(
        artifact=artifact,
        rubrics_list=rubrics_list,
        min_rubrics=MIN_RUBRICS,
        max_rubrics=MAX_RUBRICS,
    )

    valid_ids = {r["id"] for r in rubrics}

    for use_gemini in (False, True):
        try:
            raw = _llm_call(RUBRIC_SELECTION_SYSTEM, user_msg, SELECTION_TEMPERATURE, use_gemini)
            parsed = json.loads(_strip_fences(raw))
            selected = parsed["selected_rubric_ids"]

            # Filter to only valid IDs
            selected = [rid for rid in selected if rid in valid_ids]

            # Enforce min/max
            if len(selected) < MIN_RUBRICS:
                # Pad with most general rubrics
                fallbacks = ["clarity", "structure", "relevance", "depth", "completeness"]
                for fb in fallbacks:
                    if fb not in selected:
                        selected.append(fb)
                    if len(selected) >= MIN_RUBRICS:
                        break
            selected = selected[:MAX_RUBRICS]

            return {
                "selected_rubric_ids": selected,
                "reasoning": parsed.get("reasoning", ""),
            }
        except (json.JSONDecodeError, KeyError, TypeError):
            if use_gemini:
                raise ValueError("Rubric selection failed — could not parse response from either model")

    # unreachable but satisfies linter
    raise ValueError("Rubric selection failed")


def score_rubric(artifact: str, rubric: dict) -> dict:
    """
    Stage 2: Score a single rubric, running N_SCORING_RUNS times and averaging.
    Never raises — returns error info in the dict if all runs fail.
    """
    scoring_guide = "\n".join(
        f"  {range_}: {desc}" for range_, desc in rubric["scoring_guide"].items()
    )
    user_msg = SCORING_USER.format(
        rubric_name=rubric["name"],
        rubric_description=rubric["description"],
        scoring_guide=scoring_guide,
        artifact=artifact,
    )

    scores = []
    reasonings = []

    for _ in range(N_SCORING_RUNS):
        try:
            raw = _llm_call(SCORING_SYSTEM, user_msg, SCORING_TEMPERATURE)
            parsed = json.loads(_strip_fences(raw))
            score = float(parsed["score"])
            score = max(0.0, min(10.0, score))
            scores.append(score)
            reasonings.append(parsed.get("reasoning", ""))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue

    if not scores:
        return {
            "rubric_id": rubric["id"],
            "rubric_name": rubric["name"],
            "avg_score": None,
            "individual_scores": [],
            "score_variance": None,
            "reasonings": [],
            "runs_completed": 0,
            "runs_attempted": N_SCORING_RUNS,
            "error": "all_scoring_runs_failed",
        }

    avg = round(sum(scores) / len(scores), 2)
    variance = round(max(scores) - min(scores), 2) if len(scores) > 1 else 0.0

    return {
        "rubric_id": rubric["id"],
        "rubric_name": rubric["name"],
        "avg_score": avg,
        "individual_scores": scores,
        "score_variance": variance,
        "reasonings": reasonings,
        "runs_completed": len(scores),
        "runs_attempted": N_SCORING_RUNS,
        "error": None,
    }


def evaluate_artifact(artifact: str) -> dict:
    """
    Full evaluation pipeline: Stage 1 (select rubrics) + Stage 2 (score each).
    Returns the complete result payload.
    """
    rubrics = _load_rubrics()
    rubric_map = {r["id"]: r for r in rubrics}

    # Stage 1
    selection = select_rubrics(artifact)
    selected_ids = selection["selected_rubric_ids"]

    # Stage 2
    scores = []
    for rid in selected_ids:
        rubric = rubric_map.get(rid)
        if rubric is None:
            continue
        result = score_rubric(artifact, rubric)
        scores.append(result)

    return {
        "selection": selection,
        "scores": scores,
        "gap_analysis": None,  # Stage 3 — not built yet
    }
