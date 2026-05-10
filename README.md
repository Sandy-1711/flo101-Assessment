# critic-agent
paste some text or code, get an honest evaluation.

---

## what this does

You paste an artifact — an essay, an email, a proposal, a code snippet, whatever — and the system figures out which quality dimensions are worth checking for *that specific thing*, then scores it on each one. It deliberately does not evaluate every rubric every time. A haiku doesn't need "technical accuracy"; a SQL query doesn't need "professional tone".

There are **13 rubrics** in total: Clarity, Structure, Logical Coherence, Evidence, Depth of Analysis, Relevance, Originality, Actionability, Completeness, Conciseness, Technical Accuracy, Professional Tone, and Functional Correctness (for code). For any given artifact, **3 to 6** of these get selected.

Stage 3 (gap analysis — *what's missing* + *the next best improvement step*) is the next thing being built. Right now it's a `null` placeholder in the response.

---

## architecture

Three stages, orchestrated in [backend/pipeline.py](backend/pipeline.py). Each stage is a pure function in [backend/agents.py](backend/agents.py) and is independently callable.

```
                ┌─────────────────────────────────────────────┐
   artifact ──► │  Stage 1: Rubric Selection                  │
                │  (Groq primary, Gemini fallback)            │
                └────────────────┬────────────────────────────┘
                                 │ 3–6 rubric IDs + reasoning
                                 ▼
                ┌─────────────────────────────────────────────┐
   artifact ──► │  Stage 2: Per-Rubric Scoring (parallel)     │
                │  (Gemini-2.5-pro primary, Groq fallback)    │
                └────────────────┬────────────────────────────┘
                                 │ score 0–10 + reasoning, per rubric
                                 ▼
                ┌─────────────────────────────────────────────┐
                │  Stage 3: Gap Analysis  (TODO — null)       │
                │  → missing gaps + next best improvement     │
                └────────────────┬────────────────────────────┘
                                 ▼
                          EvaluationResult
```

### Stage 1 — Rubric Selection
- **Input**: `artifact` (string), full list of 13 rubrics (id + name + description).
- **Does**: one LLM call. Picks 3–6 rubrics that are *actually meaningful* for this artifact.
- **Output**: `RubricSelection { selected_rubric_ids: [str], reasoning: str }`.
- **Provider**: Groq (`llama-3.3-70b-versatile`) primary, Gemini fallback. Cheap and fast — selection is high-volume, low-stakes.
- **Safety net**: if the model returns fewer than `MIN_RUBRICS`, the result is padded with general-purpose fallbacks (`clarity`, `structure`, `relevance`, `depth`, `completeness`).
- **If both providers fail**: raises `ValueError` → API returns 422.

### Stage 2 — Per-Rubric Scoring
- **Input**: `artifact` + the rubrics chosen in Stage 1.
- **Does**: fans out across rubrics in parallel via `asyncio.gather`. For each rubric, runs N scoring calls (default `N_SCORING_RUNS=1`, configurable) and averages.
- **Output, per rubric**: `RubricScoreResult { rubric_id, rubric_name, avg_score, individual_scores, score_variance, reasonings, runs_completed, runs_attempted, error? }`.
- **Provider**: Gemini-2.5-pro primary (better at calibrated reasoning), Groq fallback.
- **Never raises**: per-run failures are skipped silently. If *all* runs for a rubric fail, that rubric returns `avg_score=null` with an `error` field — the rest of the report is still useful.

### Stage 3 — Gap Analysis *(not yet built)*
- **Planned input**: artifact + the Stage 2 scores and reasonings.
- **Planned output**: `gap_analysis { gaps: [...], next_best_step: str, rationale: str }`.
- **Right now**: `gap_analysis: null` in the response.

### Final response shape
```jsonc
{
  "selection": {
    "selected_rubric_ids": ["clarity", "structure", "depth", "evidence"],
    "reasoning": "..."
  },
  "scores": [
    {
      "rubric_id": "clarity",
      "rubric_name": "Clarity & Communication",
      "avg_score": 7.0,
      "individual_scores": [7.0],
      "score_variance": 0.0,
      "reasonings": ["..."],
      "runs_completed": 1,
      "runs_attempted": 1,
      "error": null
    }
    // ...one per selected rubric
  ],
  "gap_analysis": null
}
```

---

## provider routing & failure handling

The provider abstraction lives in [backend/llm.py](backend/llm.py). `LLMRouter` wraps a primary + fallback and switches on:
- rate-limit errors (Groq `RateLimitError`, Gemini 429 via `APIError`)
- timeouts (`APITimeoutError`, `asyncio.TimeoutError`)
- connection errors
- schema validation failures (Pydantic `ValidationError` — i.e. the model returned malformed JSON)

Both stages use the same router class with different primaries: Groq-first for selection, Gemini-first for scoring.

**Three explicit failure cases**, all handled in [backend/main.py](backend/main.py):
1. **Bad input** — empty / under `MIN_WORDS` / over `MAX_CHARS` → 400 with a clear message *before* any API call.
2. **Both providers down or rate-limited** → 503 `all_providers_unavailable`.
3. **Stage 1 selection fails on both providers** → 422 `rubric_selection_failed`.

**Tradeoff worth naming**: more scoring runs → more stable averages, but linearly more API calls. With `N_SCORING_RUNS=1` and up to 6 rubrics, an evaluation is ~7 calls (1 selection + 6 scoring). Bumping runs to 3 makes it ~19 calls and starts to bite Groq's free tier.

---

## setup

Prereqs: Python 3.11+, a [Groq](https://console.groq.com) free-tier key, a [Gemini](https://aistudio.google.com/apikey) free-tier key.

```
1. git clone <this repo> && cd flo101-assessment
2. cp .env.example .env       # then fill in GROQ_API_KEY and GEMINI_API_KEY
3. python -m venv .venv
4. .venv\Scripts\activate     # (Windows)  or  source .venv/bin/activate
5. pip install -r backend/requirements.txt
6. cd backend
7. uvicorn main:app --reload
8. open http://localhost:8000
```



### config (all in `.env`)

| var | default | what it does |
| --- | --- | --- |
| `GROQ_API_KEY` | — | required |
| `GEMINI_API_KEY` | — | required |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | default Groq model |
| `GEMINI_MODEL` | `gemini-2.0-flash-lite` | default Gemini model (used as Stage 1 fallback) |
| `SCORING_GEMINI_MODEL` | `gemini-2.5-pro` | Gemini model used as Stage 2 primary |
| `N_SCORING_RUNS` | `1` | how many times each rubric is scored, then averaged |
| `MIN_RUBRICS` / `MAX_RUBRICS` | `3` / `6` | bounds on Stage 1 output |
| `SELECTION_TEMPERATURE` | `0.4` | Stage 1 temp |
| `SCORING_TEMPERATURE` | `0` | Stage 2 temp (deterministic-ish) |
| `LLM_TIMEOUT_SECONDS` | `30` | per-call timeout |
| `LLM_MAX_TOKENS` | `512` | output cap |
| `MIN_WORDS` / `MAX_CHARS` | `10` / `15000` | input validation bounds |

---

## running the eval

The server has to be running first.

```
cd eval
python eval_script.py --golden golden_set.json --api-url http://localhost:8000
```

5 pre-written artifacts go through the full pipeline. The script checks:
- **Rubric recall** — did the model pick the rubrics we expected? (target ≥ 85%)
- **Exclude violations** — did it pick any rubric that makes no sense for the artifact? (target 0)
- **Score accuracy** — do the scores fall within the expected ranges? (target ≥ 80%)

Exit code 0 = all targets met. Exit 1 = something missed.

5 entries is enough to catch obvious regressions when prompts change — not enough to trust the numbers statistically. Treat it as a sanity check, not a benchmark.

---

## known limitations

- **No caching.** Same text evaluated twice makes the same API calls twice. Fine — the whole point is fresh evaluation.
- **Free-tier rate limits.** Groq caps ~30 req/min. If you hit it, Gemini takes over. If both are down, 503.
- **Scoring is subjective.** The model's sense of "7/10 for evidence" can drift. Run-averaging helps but doesn't fully fix it.
- **Stage 3 is a placeholder.** Gap analysis isn't built yet — it's the next task.

---

## what's next

- **Stage 3**: gap analysis — what's missing, and the single best next improvement step.
- Better prompt calibration (current prompts are v1, not tuned).
- Surface the per-run reasonings in the UI (collapsed by default).
