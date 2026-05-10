# product note

Short version of why this build matters for flo101 specifically, and the one metric I'd track if this shipped.

---

## why a critic agent fits flo101

flo101's pitch is *guided execution + verifiable proof-of-work* — learners do real work and get real feedback, instead of watching videos and hoping it sticks. That positioning has a load-bearing assumption: the feedback has to actually be good. If the feedback layer is generic ("nice essay, consider adding more detail"), the proof-of-work value evaporates and you're left with a slightly-better Coursera.

A critic agent is exactly the piece that makes the proof-of-work real:

- **Rubric-based scoring** turns a vague "is this good?" into something the learner can argue with, point at, and improve against. Numbers per dimension are debate-able in a way prose feedback isn't.
- **Selecting which rubrics apply** to *this artifact* (instead of forcing the same rubric set on every input) is the difference between a tool that respects the work and a tool that scores everything on a corporate-essay scale. A code submission shouldn't be scored on `professional_tone`. A creative pitch shouldn't be scored on `logical_coherence`. Stage 1 in this build does that filtering — it's not just a cost optimization, it's a quality decision.
- **One next-best step** (not five suggestions) matches how learners actually improve. A learner staring at six bullet points doesn't know which one to start with. The whole value of a critic is the prioritization. Stage 3 forces a single recommendation.

The piece I deliberately *didn't* build is the roleplay module. The brief said skip it, but it's worth naming: a critic that gives a score is useful; a critic that has a back-and-forth conversation about the score is more useful. The current architecture doesn't preclude that — Stage 3's output is the natural seed for a follow-up turn.

---

## the one metric I'd track in production

**Score-to-revision lift** — for each artifact submission, did the next revision the learner submitted move the per-rubric scores in the direction the gap analysis pointed at?

Concretely: if Stage 3 says "the gap is `evidence`, here's the next best step", then on the next submission of that artifact, did `evidence` go up? If yes, the critic is doing its job. If `evidence` stays flat or other rubrics regress, either the recommendation was wrong, the recommendation was unclear, or the learner didn't act on it — and you can split those three by looking at whether the learner edited at all.

I'd track this because it's the only metric that actually measures the product's *thesis*. You can dashboard a hundred other things — call latency, average score, rubric coverage, user satisfaction — but lift-on-revision is the one that says "the feedback caused better work to happen". That's the proof-of-work loop closing.

A few honorable mentions that didn't make the cut as the *one* metric:

- **Rubric-selection precision/recall** (what the eval harness in this build measures). Useful for development, but a leading indicator — picking the right rubrics doesn't mean the learner improved.
- **Time-to-revision.** If learners submit, get feedback, and never come back, the critic isn't sticky. Worth watching, but it's an engagement metric, not a quality one.
- **Score variance across N runs** (already exposed in the API). A reliability check on the model itself, not on the product.

If lift-on-revision is moving in the right direction and stays there, the critic is working. If it isn't, nothing else matters.
