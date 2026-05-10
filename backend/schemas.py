"""Pydantic models for all LLM structured I/O, plus rubric loader."""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class Rubric(BaseModel):
    id: str
    name: str
    description: str
    scoring_guide: dict[str, str]
    applicable_to: list[str]


class RubricSelection(BaseModel):
    """Stage 1 output — which rubrics to evaluate this artifact on."""
    selected_rubric_ids: list[str]
    reasoning: str


class RubricScoreResponse(BaseModel):
    """Single LLM scoring response (one run)."""
    score: float = Field(ge=0, le=10)
    reasoning: str


class RubricScoreResult(BaseModel):
    """Stage 2 output — aggregated result for one rubric across N runs."""
    rubric_id: str
    rubric_name: str
    avg_score: float | None
    individual_scores: list[float]
    score_variance: float | None
    reasonings: list[str]
    runs_completed: int
    runs_attempted: int
    error: str | None = None


class GapItem(BaseModel):
    rubric_id: str
    gap_description: str


class GapAnalysisResponse(BaseModel):
    """Stage 3 output — what's missing, plus the single next best improvement."""
    gaps: list[GapItem]
    next_best_step: str
    rationale: str


class EvaluationResult(BaseModel):
    """Final response payload returned to the client."""
    selection: RubricSelection
    scores: list[RubricScoreResult]
    gap_analysis: GapAnalysisResponse | None = None


@lru_cache
def load_rubrics() -> list[Rubric]:
    """Load rubrics.json once and cache."""
    path = Path(__file__).parent / "rubrics.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [Rubric.model_validate(r) for r in data["rubrics"]]
