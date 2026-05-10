# architecture note

This is the longer-form companion to the README. The README covers *how to run it*; this covers *what I actually built and why I built it that way*.

---

## the tech


- **Backend**: FastAPI (Python 3.11+), fully async.
- **LLM providers**: two free-tier APIs.
  - **Groq** (`openai/gpt-oss-120b`) is the primary across all three stages — fast, generous free-tier RPM, capable enough to handle both selection and scoring + synthesis. JSON mode for structured output.
  - **Gemini** is the fallback per stage — `gemini-2.5-flash-lite` for Stage 1, `gemini-2.5-flash` for Stage 2 and 3. Native `response_schema` support means the fallback path is also typed-JSON-clean.
- **Validation**: Pydantic v2 everywhere — every LLM call returns a typed model.
- **Frontend**: plain HTML + vanilla JS + a single CSS file. 
- **Eval harness**: a standalone Python script + a 5-entry golden set in JSON. Runs against the live server, exits 0/1.
- **Config**: every tunable lives in `.env` — models, temperatures, retry counts, validation thresholds.

---

## the approach

The brief asks for four things from a single artifact: rubric-based evaluation, dimension-specific feedback, missing gaps, and the next best improvement step. I split that into **three stages**, in this order, because each one needs the previous one's output:

1. **Stage 1 — Rubric Selection**: which dimensions are even worth measuring for *this* artifact?
2. **Stage 2 — Per-Rubric Scoring**: for each selected rubric, how does it score, and why?
3. **Stage 3 — Gap Analysis**: given those scores, what's actually missing, and what's the one thing the author should fix first?

A few decisions worth naming explicitly:

**Why select rubrics instead of scoring all 13?** Two reasons. Cost — I'd be making 13 scoring calls per evaluation instead of 3–6, and the free tier doesn't love that. But the bigger reason is *quality*: forcing the model to score "technical accuracy" on an essay is not worth it. The scores stop meaning anything if every rubric gets used on every artifact. The selection step is a filter that keeps the output trustworthy.

**Why two providers with fallback?** Free-tier rate limits. The router in `llm.py` switches on rate-limit / timeout / connection / schema-validation errors. Every stage uses Groq (`openai/gpt-oss-120b`) as primary and Gemini as fallback. I went back and forth on the primary — see below.

**Why Groq as primary, not Gemini?** Tried it both ways. Started with Groq, switched to Gemini-2.5-flash because I thought reasoning quality mattered more for scoring than for selection. But Gemini's free-tier 10 RPM ceiling kept tripping during Stage 2 — the parallel burst of 5 scoring calls plus a gap-analysis call per evaluation was too much for that quota. Groq's free-tier RPM is more forgiving and `gpt-oss-120b`'s reasoning is strong enough that the quality penalty (vs. Gemini-flash) is small. Gemini stays as fallback so a single Groq throttle doesn't take the whole pipeline down.

**Why not Gemini-2.5-pro on the fallback path?** I tried `gemini-2.5-pro` early on because reasoning quality matters more for scoring than for selection. But the free-tier rate limit on 2.5-pro is tight (5 RPM) and almost every scoring call was hitting `ClientError`. `gemini-2.5-flash` has a much higher rate limit and is good enough as a fallback when Groq throttles.

**Why fan-out scoring in parallel but keep N runs sequential?** `asyncio.gather` across rubrics is free latency reduction — they're independent. Within a single rubric, I keep the N runs sequential to make rate-limiting more predictable. Default is `N_SCORING_RUNS=1` because at temperature 0 the variance is small and I'd rather spend the call budget on more rubrics than on re-scoring the same one.

**Why a separate "next best step" instead of just a list of suggestions?** The brief asks for "the next best improvement step" (singular). And from a product standpoint, a learner staring at six suggestions doesn't know which one to start with — the whole value-add is the prioritization. Stage 3 forces the model to pick one.

---

## what each stage does

### Stage 1 — Rubric Selection

**Input**: the artifact (string), and the full list of 13 rubrics with their IDs, names, and descriptions.

**What it does**: one call to Groq (`openai/gpt-oss-120b`) with JSON mode on. The model sees every rubric and picks 3–6 that are *meaningful for this specific artifact*. The prompt explicitly tells it to skip rubrics that would be inapplicable or trivially high/low — that's how a haiku avoids being scored on technical accuracy. Gemini-flash-lite is the fallback if Groq throttles or returns malformed JSON.

**Output**: `RubricSelection { selected_rubric_ids: [str], reasoning: str }`. The reasoning is shown in the UI underneath the score grid so the user can see *why* these dimensions were chosen.

**Safety net**: if the model returns fewer than `MIN_RUBRICS=3` valid IDs (rare, but happens when it hallucinates an ID that isn't in the list), I pad up using a hardcoded list of general-purpose fallbacks (`clarity`, `structure`, `relevance`, `depth`, `completeness`). The list is also capped at `MAX_RUBRICS=6` so the model can't blow up the API budget by selecting all 13.

**Failure**: if Groq fails *and* the Gemini fallback also fails, this is the one place that raises. The API surfaces it as a 422 `rubric_selection_failed`. Without selected rubrics there's nothing for the rest of the pipeline to do.

### Stage 2 — Per-Rubric Scoring

**Input**: the artifact + the rubrics chosen in Stage 1.

**What it does**: for each selected rubric, `asyncio.gather` fans out a scoring call. The primary is Groq (`openai/gpt-oss-120b`) with JSON mode. Each call gets the artifact, the rubric description, and the rubric's specific 0–10 scoring guide. Inside each rubric, I run N calls (default 1, configurable to 3 if you want score-stability) and average them — `score_variance` is reported so you can see when the model was uncertain. If Groq throttles mid-run, the call falls over to `gemini-2.5-flash` per-rubric — failures on one rubric never affect the others.

**Output, per rubric**: `RubricScoreResult { rubric_id, rubric_name, avg_score, individual_scores, score_variance, reasonings, runs_completed, runs_attempted, error? }`.

**Never raises**: this was important. If one rubric's call fails, the rest of the report is still useful — losing "professional tone" doesn't invalidate "evidence". A failed rubric returns `avg_score: null` with an `error` field, and the frontend renders that card with a "?" badge instead of a number.

### Stage 3 — Gap Analysis

**Input**: the artifact + the score+reasoning of every rubric that successfully scored in Stage 2.

**What it does**: one LLM call (same router as Stage 2 — Groq primary, Gemini-flash fallback). The prompt feeds the model a compact `id | name | score | reasoning` block for each rubric and asks for two things: 1–4 *concrete gaps* (each tied to a rubric ID — the model has to ground the gap to something it actually scored), and one *next best improvement step* with a short rationale. Temperature is 0.3 — slightly above zero so the phrasing isn't robotic, but not enough for the model to wander off-topic.

**Output**: `GapAnalysisResponse { gaps: [{rubric_id, gap_description}], next_best_step: str, rationale: str }`.

**Anti-hallucination guard**: after the model returns, I drop any gap entry whose `rubric_id` wasn't actually in the Stage 2 results. If the model invented `clarity` when only `evidence` and `depth` were scored, that gap gets thrown out before the response leaves the server.

**Never raises**: same philosophy as Stage 2. If both providers fail on the gap call, `gap_analysis` comes back `null` and the UI shows a small amber "gap analysis was unavailable" notice. The score grid above it is still valid.

---

## file layout

```
backend/
  main.py        — FastAPI app, input validation, error mapping
  pipeline.py    — the only place where the three stages are composed
  agents.py      — pure stage functions: select_rubrics, score_rubric, analyze_gaps
  llm.py         — provider abstraction + LLMRouter (primary/fallback switching)
  schemas.py     — every Pydantic model + the rubric loader
  prompts.py     — every system + user prompt, in one place
  rubrics.json   — the 13 rubrics with their scoring guides
  requirements.txt
frontend/
  index.html, app.js, style.css
eval/
  eval_script.py, golden_set.json
notes/
  architecture.md   — this file
.env, .env.example  — every tunable
README.md
```

The stage / agent / pipeline / prompts split is deliberate. Adding a Stage 4 would mean: write its prompt in `prompts.py`, write its function in `agents.py`, add a line to `pipeline.py`. The provider layer and the schema layer wouldn't need to change.
