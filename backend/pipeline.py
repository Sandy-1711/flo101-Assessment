"""
Evaluation pipeline orchestration.

This is the single place where the flow is defined:
    Stage 1: select rubrics
    Stage 2: score each selected rubric (parallel across rubrics)
    Stage 3: gap analysis — what's missing + the next best improvement step

To change the order, add a stage, or swap an agent — edit `evaluate_artifact`.
"""

import asyncio
import os

from agents import analyze_gaps, score_rubric, select_rubrics
from llm import get_llm_router
from schemas import EvaluationResult, load_rubrics

# All stages: Gemini primary — flash for selection (light routing), pro for scoring + gap analysis (heavy reasoning).
# Groq (`openai/gpt-oss-120b`) stays as fallback per stage — generous free-tier RPM keeps the pipeline alive on rate limits.
SELECTION_GEMINI_MODEL = os.getenv("SELECTION_GEMINI_MODEL", "gemini-2.5-flash")
SCORING_GEMINI_MODEL = os.getenv("SCORING_GEMINI_MODEL", "gemini-2.5-pro")


async def evaluate_artifact(artifact: str) -> EvaluationResult:
    selection_llm = get_llm_router(primary="gemini", gemini_model=SELECTION_GEMINI_MODEL)
    scoring_llm = get_llm_router(primary="gemini", gemini_model=SCORING_GEMINI_MODEL)
    rubrics = load_rubrics()
    rubric_map = {r.id: r for r in rubrics}

    # Stage 1
    selection = await select_rubrics(artifact, rubrics, selection_llm)

    # Stage 2 — fan out across rubrics, sequential within each rubric
    selected_rubrics = [
        rubric_map[rid] for rid in selection.selected_rubric_ids if rid in rubric_map
    ]
    score_results = list(await asyncio.gather(
        *(score_rubric(artifact, r, scoring_llm) for r in selected_rubrics)
    ))

    # Stage 3 — gap analysis (reuses the scoring router; never raises)
    gap_analysis = await analyze_gaps(artifact, score_results, scoring_llm)

    return EvaluationResult(
        selection=selection,
        scores=score_results,
        gap_analysis=gap_analysis,
    )
