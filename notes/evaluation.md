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

Two runs documented here, in order, so the trajectory is visible.

### run 1 — initial state (Groq `openai/gpt-oss-120b` primary, scoring on `gemini-2.5-flash` fallback)

```
Rubric recall      : 0.70    [target ≥ 0.85]    FAIL
Exclude violations : 2       [target = 0]       FAIL
Score accuracy     : 0.79    [target ≥ 0.80]    FAIL
```

All three metrics under target. The selector was both missing the right rubrics *and* picking inapplicable ones; the scorer was clustered around the middle.

### run 2 — after passing `applicable_to` to the selector + critic-framing rewrite (Gemini 2.5-flash selection / 2.5-pro scoring)

```
Rubric recall      : 0.90    [target ≥ 0.85]    PASS
Exclude violations : 4       [target = 0]       FAIL
Score accuracy     : 0.67    [target ≥ 0.80]    FAIL
```

Recall went up sharply (the critic framing nudged the model toward weakness-exposing rubrics), but exclude violations got *worse* and score accuracy slid. The eval doing its job — these regressions would be invisible without it.

**Overall: still FAIL.** I'm leaving this in the note honestly because a self-graded pass would be less useful than knowing exactly what's broken.

---

## failure patterns

Two distinct things are wrong after run 2, and they're worth separating.

### 1. Selector over-picks rather than mis-picks

After the critic-framing rewrite the selector is no longer regressing to safe rubrics — recall is solid. The new failure mode is different: it's filling its rubric budget. With `MIN_RUBRICS=3, MAX_RUBRICS=6`, every entry in run 2 picked 4–5 rubrics, and the *trailing* picks were the violations:

- gs_001 analytical essay → picked `actionability` and `originality` (both flagged as must-exclude — essays don't make recommendations and originality isn't load-bearing for analytical work).
- gs_004 creative pitch → picked `logical_coherence` (pitches aren't formal arguments).
- gs_005 shallow listicle → picked `technical_accuracy` (listicle isn't a technical artifact).

The selection prompt does say "do not pick actionability for an analytical essay" with concrete examples, but the model is reading those as advice and adding the rubric anyway once the obvious picks are exhausted. The fix is structural, not just rhetorical: drop `MAX_RUBRICS` to 4 and reword the `applicable_to` step as a hard disqualifier ("rubrics whose `applicable_to` does not match are *ineligible*") rather than guidance.

### 2. Scorer is close-miss, not clustered-at-mean

This is the inverted version of run 1. Scores are no longer regressing to the middle — they're now mostly within 1 point of the expected band, just outside it.

| entry | rubric | actual | expected | gap |
| --- | --- | --- | --- | --- |
| gs_002 | conciseness | 1.2 | 1.5–5.0 | -0.3 |
| gs_003 | evidence | 1.5 | 2.0–5.5 | -0.5 |
| gs_004 | actionability | 5.0 | 6.0–9.5 | -1.0 |
| gs_005 | evidence | 4.5 | 0.0–3.5 | +1.0 |

Three of four misses are within 0.5 of the band. The drift is mildly harsh on weak artifacts and mildly generous on the listicle's evidence. That's the kind of thing per-rubric calibration anchors fix — concrete "here's what a 2 looks like, here's what an 8 looks like" examples baked into the scoring prompt for the most-checked rubrics. The general "5 means genuinely average" instruction isn't precise enough on its own.

### 3. What the eval doesn't catch yet

- **Stage 3 (gap analysis) isn't asserted at all.** The eval was written when Stage 3 didn't exist. It still passes through the response (the script doesn't error if `gap_analysis` is present or null), but no metric reads it. So the gap-list quality, the "next best step" relevance, and the anti-hallucination guard are all ungated by the eval right now.
- **No latency or cost tracking.** I report neither end-to-end time nor per-call token usage. For a one-page demo this is fine; for production it isn't.
- **5 entries is not enough to trust the numbers statistically.** A single bad selection swings recall by 0.10, a single bad score swings accuracy by 0.20. I treat the eval as a sanity check ("did I just regress something obviously?"), not a benchmark. Run 1 → run 2 going from 2 violations to 4 on essentially the same prompts is a good illustration — that's a single rubric pick per entry, well within the noise floor.

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

1. **Tighten `MAX_RUBRICS` from 6 → 4 and harden the `applicable_to` filter.** Highest leverage on the still-failing exclude metric. Reword the prompt step from "skip rubrics that don't fit" (advice) to "rubrics whose `applicable_to` does not match are ineligible — disqualified before selection" (rule). This is the cheapest fix on the board.
2. **Per-rubric calibration anchors in the scoring prompt.** Every rubric currently uses the same generic 0–10 guide. A rubric-specific "here's what a 2 on `evidence` looks like, here's what an 8 looks like" anchor on the most-checked rubrics (depth, evidence, actionability, conciseness) should tighten the close-miss band.
3. **Add Stage 3 assertions to the golden set.** Each entry should specify expected gap categories and the eval would check the model's gaps overlap with that. Right now Stage 3 quality is entirely visual / vibes-based.
4. **Bigger golden set + categorize misses.** 20+ entries grouped by artifact type, so I can tell whether failures cluster on essays, code, emails, or creative work. Five entries is too noisy to know whether a prompt change actually helped — see the run 1 → run 2 swing on exclude.
5. **Latency + token tracking** in the response. Useful for the demo and for reasoning about the cost-stability tradeoff at scale.

If I had to pick one, it's #1 — exclude is currently the only metric where I know the exact lever to pull, and the lever is small.
