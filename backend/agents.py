"""
Agent functions — pure stages of the evaluation pipeline.

Each function takes an `LLMRouter` and is independently usable. The pipeline
orchestrator (pipeline.py) decides how they compose.
"""

import os

from schemas import (
    GapAnalysisResponse,
    Rubric,
    RubricScoreResponse,
    RubricScoreResult,
    RubricSelection,
)
from llm import LLMRouter
from prompts import (
    GAP_ANALYSIS_SYSTEM,
    GAP_ANALYSIS_USER,
    RUBRIC_SELECTION_SYSTEM,
    RUBRIC_SELECTION_USER,
    SCORING_SYSTEM,
    SCORING_USER,
)

# --- Config (override via .env) ---
N_SCORING_RUNS = int(os.getenv("N_SCORING_RUNS", "1"))
MIN_RUBRICS = int(os.getenv("MIN_RUBRICS", "3"))
MAX_RUBRICS = int(os.getenv("MAX_RUBRICS", "6"))
SELECTION_TEMPERATURE = float(os.getenv("SELECTION_TEMPERATURE", "0.4"))
SCORING_TEMPERATURE = float(os.getenv("SCORING_TEMPERATURE", "0"))
GAP_ANALYSIS_TEMPERATURE = float(os.getenv("GAP_ANALYSIS_TEMPERATURE", "0.3"))

# Used to pad selection up to MIN_RUBRICS if model returns too few
_FALLBACK_RUBRIC_IDS = ("clarity", "structure", "relevance", "depth", "completeness")


async def select_rubrics(
    artifact: str,
    rubrics: list[Rubric],
    llm: LLMRouter,
) -> RubricSelection:
    """
    Stage 1 — pick which rubrics are worth measuring for this artifact.
    Returns a RubricSelection with between MIN_RUBRICS and MAX_RUBRICS valid IDs.
    Raises ValueError if both providers fail.
    """
    rubrics_list = "\n".join(
        f"- id: {r.id} | applicable_to: {r.applicable_to} | name: {r.name} — {r.description}"
        for r in rubrics
    )
    user_msg = RUBRIC_SELECTION_USER.format(
        artifact=artifact,
        rubrics_list=rubrics_list,
        min_rubrics=MIN_RUBRICS,
        max_rubrics=MAX_RUBRICS,
    )

    try:
        result = await llm.generate_structured(
            system=RUBRIC_SELECTION_SYSTEM,
            user=user_msg,
            response_model=RubricSelection,
            temperature=SELECTION_TEMPERATURE,
            label="select_rubrics",
        )
    except Exception as e:
        raise ValueError(f"Rubric selection failed: {e}") from e

    valid_ids = {r.id for r in rubrics}
    selected = [rid for rid in result.selected_rubric_ids if rid in valid_ids]

    # Pad up to MIN_RUBRICS using general-purpose fallbacks
    if len(selected) < MIN_RUBRICS:
        for fb in _FALLBACK_RUBRIC_IDS:
            if fb in valid_ids and fb not in selected:
                selected.append(fb)
            if len(selected) >= MIN_RUBRICS:
                break

    selected = selected[:MAX_RUBRICS]
    return RubricSelection(
        selected_rubric_ids=selected,
        reasoning=result.reasoning,
    )


async def score_rubric(
    artifact: str,
    rubric: Rubric,
    llm: LLMRouter,
    n_runs: int = N_SCORING_RUNS,
) -> RubricScoreResult:
    """
    Stage 2 — run N scoring calls for this rubric and average the scores.
    Never raises. Per-run failures are skipped. If all runs fail, returns a
    result with avg_score=None and an error string.
    """
    scoring_guide = "\n".join(
        f"  {range_}: {desc}" for range_, desc in rubric.scoring_guide.items()
    )
    user_msg = SCORING_USER.format(
        rubric_name=rubric.name,
        rubric_description=rubric.description,
        scoring_guide=scoring_guide,
        artifact=artifact,
    )

    scores: list[float] = []
    reasonings: list[str] = []

    for run_idx in range(n_runs):
        try:
            run = await llm.generate_structured(
                system=SCORING_SYSTEM,
                user=user_msg,
                response_model=RubricScoreResponse,
                temperature=SCORING_TEMPERATURE,
                label=f"score:{rubric.id}#{run_idx + 1}",
            )
            # Schema enforces 0-10 already, but clamp defensively
            score = max(0.0, min(10.0, float(run.score)))
            scores.append(score)
            reasonings.append(run.reasoning)
        except Exception:
            continue

    if not scores:
        return RubricScoreResult(
            rubric_id=rubric.id,
            rubric_name=rubric.name,
            avg_score=None,
            individual_scores=[],
            score_variance=None,
            reasonings=[],
            runs_completed=0,
            runs_attempted=n_runs,
            error="all_scoring_runs_failed",
        )

    avg = round(sum(scores) / len(scores), 2)
    variance = round(max(scores) - min(scores), 2) if len(scores) > 1 else 0.0

    return RubricScoreResult(
        rubric_id=rubric.id,
        rubric_name=rubric.name,
        avg_score=avg,
        individual_scores=scores,
        score_variance=variance,
        reasonings=reasonings,
        runs_completed=len(scores),
        runs_attempted=n_runs,
    )


async def analyze_gaps(
    artifact: str,
    score_results: list[RubricScoreResult],
    llm: LLMRouter,
) -> GapAnalysisResponse | None:
    """
    Stage 3 — given the per-rubric scores from Stage 2, identify gaps and the
    single next best improvement step.

    Never raises. Returns None if both providers fail or no rubric was scored,
    so the rest of the report still ships to the client.
    """
    valid_ids = {r.rubric_id for r in score_results if r.avg_score is not None}
    if not valid_ids:
        return None

    scores_block = "\n".join(
        f"- id: {r.rubric_id} | name: {r.rubric_name} | score: {r.avg_score}/10\n"
        f"  reasoning: {r.reasonings[0] if r.reasonings else '(no reasoning)'}"
        for r in score_results
        if r.avg_score is not None
    )
    user_msg = GAP_ANALYSIS_USER.format(artifact=artifact, scores_block=scores_block)

    try:
        result = await llm.generate_structured(
            system=GAP_ANALYSIS_SYSTEM,
            user=user_msg,
            response_model=GapAnalysisResponse,
            temperature=GAP_ANALYSIS_TEMPERATURE,
            label="analyze_gaps",
        )
    except Exception:
        return None

    # Drop gap entries that reference rubric IDs the model didn't actually score
    result.gaps = [g for g in result.gaps if g.rubric_id in valid_ids]
    return result
