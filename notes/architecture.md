# architecture note

This is the longer-form companion to the README. The README covers *how to run it*; this covers *what I actually built and why I built it that way*.

---

## the tech


- **Backend**: FastAPI (Python 3.11+), fully async.
- **LLM providers**: two free-tier APIs.
  - **Gemini** is the primary across all three stages — `gemini-2.5-flash-lite` for Stage 1 (selection), `gemini-2.5-flash` for Stage 2 and Stage 3 (scoring + gap analysis). Native `response_schema` support means I don't have to parse-and-pray.
  - **Groq** (`llama-3.3-70b-versatile`) is the fallback for every stage — fast, generous free tier, JSON mode for structured output. If Gemini rate-limits or times out, the router transparently switches to Groq.
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

**Why two providers with fallback?** Free-tier rate limits. If Gemini throttles, the system needs to keep working. The router in `llm.py` switches on rate-limit / timeout / connection / schema-validation errors. Every stage uses Gemini as primary and Groq as fallback — Stage 1 with `gemini-2.5-flash-lite` (15 RPM free tier, plenty for a single selection call per evaluation), Stage 2 and 3 with `gemini-2.5-flash` (10 RPM, decent reasoning).

**Why Gemini-flash for scoring, not Gemini-pro?** I started with `gemini-2.5-pro` because reasoning quality matters more for scoring than for selection. But the free-tier rate limit on 2.5-pro is tight enough that almost every scoring call was hitting `ClientError` and falling back to Groq — which defeated the point of having pro as primary. `gemini-2.5-flash` is a small quality drop but a much higher rate limit, so the primary actually gets to do its job.

**Why fan-out scoring in parallel but keep N runs sequential?** `asyncio.gather` across rubrics is free latency reduction — they're independent. Within a single rubric, I keep the N runs sequential to make rate-limiting more predictable. Default is `N_SCORING_RUNS=1` because at temperature 0 the variance is small and I'd rather spend the call budget on more rubrics than on re-scoring the same one.

**Why a separate "next best step" instead of just a list of suggestions?** The brief asks for "the next best improvement step" (singular). And from a product standpoint, a learner staring at six suggestions doesn't know which one to start with — the whole value-add is the prioritization. Stage 3 forces the model to pick one.

---

## what each stage does

### Stage 1 — Rubric Selection

**Input**: the artifact (string), and the full list of 13 rubrics with their IDs, names, and descriptions.

**What it does**: one call to Gemini (`gemini-2.5-flash-lite`) with `response_schema` on. The model sees every rubric and picks 3–6 that are *meaningful for this specific artifact*. The prompt explicitly tells it to skip rubrics that would be inapplicable or trivially high/low — that's how a haiku avoids being scored on technical accuracy. Flash-lite is cheap, fast, and has 15 RPM free-tier headroom; Groq is the fallback if Gemini throttles.

**Output**: `RubricSelection { selected_rubric_ids: [str], reasoning: str }`. The reasoning is shown in the UI underneath the score grid so the user can see *why* these dimensions were chosen.

**Safety net**: if the model returns fewer than `MIN_RUBRICS=3` valid IDs (rare, but happens when it hallucinates an ID that isn't in the list), I pad up using a hardcoded list of general-purpose fallbacks (`clarity`, `structure`, `relevance`, `depth`, `completeness`). The list is also capped at `MAX_RUBRICS=6` so the model can't blow up the API budget by selecting all 13.

**Failure**: if Gemini fails *and* Groq fallback fails, this is the one place that raises. The API surfaces it as a 422 `rubric_selection_failed`. Without selected rubrics there's nothing for the rest of the pipeline to do.

### Stage 2 — Per-Rubric Scoring

**Input**: the artifact + the rubrics chosen in Stage 1.

**What it does**: for each selected rubric, `asyncio.gather` fans out a scoring call. The primary is `gemini-2.5-flash` with `response_schema` (typed JSON output, no parsing required). Each call gets the artifact, the rubric description, and the rubric's specific 0–10 scoring guide. Inside each rubric, I run N calls (default 1, configurable to 3 if you want score-stability) and average them — `score_variance` is reported so you can see when the model was uncertain.

**Output, per rubric**: `RubricScoreResult { rubric_id, rubric_name, avg_score, individual_scores, score_variance, reasonings, runs_completed, runs_attempted, error? }`.

**Never raises**: this was important. If one rubric's call fails, the rest of the report is still useful — losing "professional tone" doesn't invalidate "evidence". A failed rubric returns `avg_score: null` with an `error` field, and the frontend renders that card with a "?" badge instead of a number.

### Stage 3 — Gap Analysis

**Input**: the artifact + the score+reasoning of every rubric that successfully scored in Stage 2.

**What it does**: one LLM call (same router as Stage 2 — Gemini-flash primary, Groq fallback). The prompt feeds the model a compact `id | name | score | reasoning` block for each rubric and asks for two things: 1–4 *concrete gaps* (each tied to a rubric ID — the model has to ground the gap to something it actually scored), and one *next best improvement step* with a short rationale. Temperature is 0.3 — slightly above zero so the phrasing isn't robotic, but not enough for the model to wander off-topic.

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
