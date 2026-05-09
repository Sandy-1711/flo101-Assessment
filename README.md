# critic-agent
paste some text, get an honest evaluation.

---

## what this does

The idea is simple: you paste a document — an essay, an email, a proposal, whatever — and the system figures out which quality dimensions are worth checking for that specific thing, then scores it on each one. It doesn't try to evaluate every rubric every time because that would be both slow and kind of dumb. A haiku doesn't need to be evaluated on "technical accuracy".

There are 12 rubrics in total: Clarity, Structure, Logical Coherence, Evidence, Depth of Analysis, Relevance, Originality, Actionability, Completeness, Conciseness, Technical Accuracy, and Professional Tone. For any given artifact, 3 to 6 of these get selected. Each one is scored 0–10.

Stage 3 (gap analysis — identifying *what's missing* and suggesting the highest-impact improvement) is planned but not built yet.

---

## current thinking / architecture

**Stage 1 — Rubric Selection**
A fast, small model (`llama-3.1-8b-instant` via Groq) reads the artifact and picks which rubrics are worth measuring for this specific text. Returns 3–6 rubric IDs and a brief reasoning.

**Stage 2 — Scoring**
For each selected rubric, we make a separate LLM call at lower temperature (0.2). We do this 3 times and average the scores. The idea is that a single run at low temp is still not deterministic — three runs + averaging gives a more stable number. Each result also reports `score_variance` so you can see when the model was uncertain.

**Stage 3 — Gap Analysis**
Not built. Placeholder in the response (`gap_analysis: null`). The plan is to ask the model what the artifact is missing given its rubric scores, and surface the single highest-impact improvement suggestion.

**Failure handling:**
- Bad JSON from LLM → strip markdown fences, retry; fall back to Gemini; return null score if all runs fail
- Groq rate limit / timeout → switch to Gemini immediately; return 503 if both are down
- Bad input (empty, too short, too long) → validated before any API call, clear error message

**Explicit tradeoff:** 3 scoring runs × up to 6 rubrics = ~19 API calls per evaluation. On Groq's free tier this takes 10–20 seconds. If you need it faster, open `backend/agents.py` and set `N_SCORING_RUNS = 1`. You lose stability but it's fine for demos.

**APIs used:**
- [Groq](https://console.groq.com) — primary (free tier, fast)
- [Gemini](https://aistudio.google.com/apikey) — fallback (free tier)

---

## setup

```
1. Clone this repo
2. Copy .env.example to .env and fill in your API keys
3. cd backend
4. pip install -r requirements.txt
5. uvicorn main:app --reload
6. Open http://localhost:8000
```

That's it. No build step, no npm, no database.

---

## running the eval

Make sure the server is running first.

```
cd eval
python eval_script.py --golden golden_set.json --api-url http://localhost:8000
```

It runs 5 pre-written artifacts through the full pipeline and checks:
- **Rubric recall** — did the model select the rubrics we expected? (target: ≥ 85%)
- **Exclude violations** — did it pick any rubrics that make no sense for this artifact? (target: 0)
- **Score accuracy** — do the scores fall within our expected ranges? (target: ≥ 80%)

Exit code 0 = all targets met. Exit code 1 = something failed.

Note: the golden set has 5 entries. That's enough to catch obvious regressions when you change prompts — it's not enough to trust the numbers statistically. Treat it as a sanity check.

---

## known limitations

- **No caching.** Same text evaluated twice makes the same API calls twice. Fine for this use case — the whole point is fresh evaluation.
- **Rate limits.** Groq's free tier caps at ~30 requests/minute. If you hit it during the eval, Gemini kicks in. If both are down, you'll get a clear error.
- **Scoring is subjective.** The model's sense of what a "7 out of 10 for evidence" means may drift between evaluations. The 3-run averaging helps, but it's not a calibrated instrument.
- **Stage 3 is a placeholder.** Gap analysis isn't built yet.

---

## what's next

- Stage 3: gap analysis — what's missing, and what's the single best thing to improve
- Better prompt calibration (the current prompts are v1, not tuned)
- Maybe show all 3 reasoning traces in the UI (collapsed by default)
