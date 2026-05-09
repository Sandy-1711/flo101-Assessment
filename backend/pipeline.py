"""
Evaluation pipeline orchestration.

This is the single place where the flow is defined:
    Stage 1: select rubrics
    Stage 2: score each selected rubric (parallel across rubrics)
    Stage 3: gap analysis (TODO)

To change the order, add a stage, or swap an agent — edit `evaluate_artifact`.
"""

import asyncio

from agents import score_rubric, select_rubrics
from llm import get_llm_router
from schemas import EvaluationResult, load_rubrics


async def evaluate_artifact(artifact: str) -> EvaluationResult:
    llm = get_llm_router()
    rubrics = load_rubrics()
    rubric_map = {r.id: r for r in rubrics}

    # Stage 1
    selection = await select_rubrics(artifact, rubrics, llm)

    # Stage 2 — fan out across rubrics, sequential within each rubric
    selected_rubrics = [
        rubric_map[rid] for rid in selection.selected_rubric_ids if rid in rubric_map
    ]
    score_results = await asyncio.gather(
        *(score_rubric(artifact, r, llm) for r in selected_rubrics)
    )

    # Stage 3 — gap analysis (placeholder for the next iteration)
    gap_analysis = None

    return EvaluationResult(
        selection=selection,
        scores=list(score_results),
        gap_analysis=gap_analysis,
    )
