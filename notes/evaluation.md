# evaluation note

This is the honest version: what I measure, what the numbers actually are right now, what's broken, and what I'd do with more time.

---

## what I measure

A small golden set (`eval/golden_set.json`, 5 entries) covers different artifact types — strong analytical essay, vague corporate email, technical report with deliberate errors, creative product pitch, shallow listicle. Each entry has:

- `must_include` — rubrics the selector *should* pick for this artifact
- `must_exclude` — rubrics the selector should *not* pick (would be inapplicable)
- `expected_scores` — `{rubric_id: {min, max}}` ranges I think a calibrated scorer should produce

The eval script (`eval/eval_script.py`) hits the live `/evaluate` endpoint for each entry and computes three metrics:

| metric | target | what it asks |
| --- | --- | --- |
| **Rubric recall** | ≥ 0.85 | did the selector pick the rubrics that actually mattered for this artifact? |
| **Exclude violations** | = 0 | did it pick rubrics that make no sense for this artifact? |
| **Score accuracy** | ≥ 0.80 | are the per-rubric scores within the range I expected? |

Exit code 0 if all three pass, 1 otherwise. Brief 1-second pause between entries to avoid hammering the free-tier API.

---

## current results

Last run (5 entries, against `gemini-2.5-flash` for scoring):

```
Rubric recall      : 0.70    [target ≥ 0.85]    FAIL
Exclude violations : 0       [target = 0]       PASS
Score accuracy     : 0.69    [target ≥ 0.80]    FAIL
```

**Overall: FAIL.** Two of three metrics are below target. I'm leaving this in the note honestly because the eval doing its job — surfacing real prompt-quality issues — is more useful than a self-graded pass.

---

## failure patterns

Two distinct things are wrong, and they're worth separating.

### 1. Selector regresses to "safe" rubrics

The recall miss isn't random. The selector keeps picking generic, broadly-applicable rubrics (clarity, structure, relevance, conciseness) and skipping the more *interpretive* ones (originality, depth, actionability) — which are exactly the rubrics a critic should be using to call out weak artifacts.

Concrete misses from the last run:
- gs_002 vague corporate email → expected `actionability` (no clear ask in the email), got `professional_tone` instead.
- gs_004 product pitch → expected `originality`, didn't pick it.
- gs_005 shallow listicle → expected `depth`, picked everything *except* depth.

The selector is being too cautious. A weak artifact's most important rubrics are usually the ones it's failing on, but the model is treating "safe and broadly applicable" as "important". This is fixable in the prompt — needs nudging toward "what would an expert critic flag here" rather than "what is universally relevant".

### 2. Scorer regresses to the mean

Scores cluster in the 5–7 range even when the artifact is clearly bad or clearly good.

- gs_003 technical report with deliberate errors → `technical_accuracy: 7.5` (expected ≤ 5.0). The model didn't catch the planted errors.
- gs_005 shallow listicle → `evidence: 5.5` (expected ≤ 3.5). Too generous.
- gs_004 pitch → `actionability: 2.0` (expected ≥ 6.0). Too harsh on a category that's actually a strength.
- gs_001 strong essay → `evidence: 9.0` (expected ≤ 8.5). Slightly over the top end.

This is a calibration problem. The scoring prompt does say "a 5 means genuinely average, not 'good enough to avoid trouble'" but that's clearly not enough — the model still anchors to the middle. Concrete scoring guides per rubric (specifying what 2 looks like, what 8 looks like) would probably help more than prompt-level instructions.

### 3. What the eval doesn't catch yet

- **Stage 3 (gap analysis) isn't asserted at all.** The eval was written when Stage 3 didn't exist. It still passes through the response (the script doesn't error if `gap_analysis` is present or null), but no metric reads it. So the gap-list quality, the "next best step" relevance, and the anti-hallucination guard are all ungated by the eval right now.
- **No latency or cost tracking.** I report neither end-to-end time nor per-call token usage. For a one-page demo this is fine; for production it isn't.
- **5 entries is not enough to trust the numbers statistically.** A single bad selection swings recall by 0.10, a single bad score swings accuracy by 0.20. I treat the eval as a sanity check ("did I just regress something obviously?"), not a benchmark.

---

## known runtime failure modes

These are baked into the design — the eval can't catch them, but they're handled.

- **Both providers down or rate-limited** on a Stage 1 call → API returns 422 `rubric_selection_failed`. The pipeline can't proceed without selected rubrics.
- **Both providers fail on a single Stage 2 rubric** → that rubric returns `avg_score: null` with an `error` field; the rest of the report still renders.
- **Both providers fail on Stage 3** → `gap_analysis: null`; the UI shows a small amber notice. Score grid is unaffected.
- **Bad input** (empty / under `MIN_WORDS` / over `MAX_CHARS`) → 400 with a clear message *before* any LLM call.
- **Schema-validation failure** (model returned malformed JSON) → router treats it as a fallback-eligible error and switches providers.
- **Gemini 2.5-pro rate limit was so tight it was hitting `ClientError` on most scoring calls** → switched the default to 2.5-flash. The `LLMRouter` fallback handled this transparently in the meantime; the system stayed up but everything was running on Groq.

---

## what I'd do with more time

In rough priority order:

1. **Add Stage 3 assertions to the golden set.** Each entry should specify expected gap categories ("a sensible gap-analysis output for this artifact would mention X") and the eval would check the model's gaps overlap with that. Right now Stage 3 quality is entirely visual / vibes-based.
2. **Per-rubric calibration anchors in the scoring prompt.** Right now every rubric uses the same generic scoring guide. A rubric-specific "here's what a 2 looks like, here's what an 8 looks like" anchor would push the model out of the 5–7 cluster.
3. **Selection prompt v2.** Bias the model toward picking the rubrics that *expose weakness* in the artifact rather than the ones that are universally applicable. Possibly two-pass — quick read for "where does this artifact look weakest", then pick rubrics that measure those dimensions.
4. **Bigger golden set + categorize misses.** 20+ entries grouped by artifact type, so I can tell whether failures cluster on essays, code, emails, or creative work.
5. **Latency + token tracking** in the response. Useful for the demo and for reasoning about the cost-stability tradeoff at scale.

If I had to pick one of these, it's #1 — Stage 3 is the most product-differentiated piece of the system and it's currently flying blind.
