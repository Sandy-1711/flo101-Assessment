# AI usage disclosure

Honest version of what I used AI for and what I drove myself.

---

## the headline number

Roughly **70–80% of what's in the repo started as AI generation**, but heavily steered. I don't accept generations blind — I'm fairly opinionated about code quality and AI-generated code tends to drift toward verbose, over-defensive, or generically structured output if you let it. So while a lot of the lines were typed by an assistant, the shape, structure, and architectural decisions were mine, and I refined every generation rather than accepting the first pass.

I fed the assistant my own past code as style examples, told it which patterns I wanted (Pydantic-everywhere, async-everywhere, env-driven config, provider abstraction), and pushed back when the output didn't match.

---

## what I drove personally (the architecture-shaping decisions)

These weren't AI-generated — they were decisions I made and then asked the assistant to implement:

- **Three-stage split** (selection → scoring → gap analysis). The reasoning for splitting Stage 3 from Stage 2 — that LLMs are bad at "find what's missing" cold but decent at it once they have scores in front of them — is mine.
- **Provider abstraction layer** (`llm.py`'s `LLMProvider` Protocol + `LLMRouter`). I wanted swappable providers from day 1 because I knew rate limits would force me to switch — which they did, multiple times. Designed the interface, then asked AI to fill in the Groq + Gemini implementations.
- **Pydantic-everywhere policy.** Every LLM I/O is a typed model. AI doesn't push for this on its own — it'll happily return raw dicts. I added the validation pass and pushed every schema through it.
- **Stage routing decisions.** Which model goes where, which is primary, which is fallback. I tried Gemini-2.5-pro first, watched it rate-limit, switched to Gemini-flash, watched *that* rate-limit on parallel scoring bursts, switched primary to Groq's `gpt-oss-120b`. Each switch was driven by an observation I made on the logs.
- **Anti-hallucination guard in Stage 3.** Dropping gap entries whose `rubric_id` isn't in the actual Stage 2 results — I added this after seeing the model invent a `clarity` gap on a run where clarity wasn't scored.
- **Eval golden set design.** The five-entry structure with `must_include`, `must_exclude`, and `expected_scores` per entry — I designed this. The actual entry text was Claude-generated to my spec.
- **Rate-limit diagnosis.** When eval started failing with `RateLimitError`, the realization that Groq's 8k TPM was the real ceiling (not RPM) and the fix (bump inter-entry delay to 60s) was mine.

---

## what AI generated heavily

- **Boilerplate scaffolding.** FastAPI app skeleton, Pydantic model definitions, async wrappers around the SDKs. AI is good at this, I'd be wasting time hand-rolling it.
- **Prompt drafting (first pass only).** I'd describe what I wanted the prompt to do, AI would write a first version, then I'd revise based on actual model output. The current `RUBRIC_SELECTION_USER` prompt for example was rewritten three or four times after watching the selector regress to safe rubrics.
- **Frontend (index.html + app.js + style.css).** Plain HTML/JS/CSS, no framework. I told it what I wanted to see (cards, score badges, gap-analysis section, error states) and reviewed the output. Frontend is not where I want to spend hours of a 6–8 hour timebox.
- **Rubrics + golden-set entry text.** The 13 rubric definitions in `rubrics.json` and the artifact text in `golden_set.json` are AI-generated to my instructions. This is the part I'd want to refine most with more time — they're load-bearing for evaluation quality and a first pass is a first pass.
- **Documentation prose.** The README, this note, the architecture note, the evaluation note — I drafted bullet points or sketched the structure, AI wrote the prose, I rewrote the bits that didn't sound like me. The voice across the notes is deliberately mine; the typing-effort wasn't.

---

## what I'd flag as risk

- **Rubric and golden-set quality.** Because they're AI-generated, they may have biases I haven't audited. If the assistant's idea of a "shallow listicle" is consistently shallower than what real learners submit, my eval numbers are calibrated to a synthetic distribution, not a real one. Worth refining against actual learner data before trusting the eval as a benchmark.
- **Prompt iteration is uneven.** Stage 1 has been rewritten the most because the eval surfaced clear failures. Stage 2 and Stage 3 prompts are first or second drafts — they'd probably benefit from the same loop, but I didn't have the eval coverage to drive it (Stage 3 isn't even asserted in the eval yet).

---

## tools used

- Claude Code (Sonnet, occasionally Opus on harder bits) — the bulk of the assistant work, with my own prompts steering it.
- Gemini and Groq are the *runtime* LLMs the system itself calls — they aren't part of the build process.

No code was committed without me reading it. There's no "vibe-coded" section of this repo where I don't know what the code does.
