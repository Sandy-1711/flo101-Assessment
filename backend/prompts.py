RUBRIC_SELECTION_SYSTEM = """You are an expert writing evaluator. Your job is to look at a piece of text and decide which quality dimensions are most worth measuring for that specific text. You return only valid JSON, nothing else. No markdown, no explanation outside the JSON."""

RUBRIC_SELECTION_USER = """Here is a piece of text to evaluate:

---
{artifact}
---

Here are the available evaluation rubrics:

{rubrics_list}

Select between {min_rubrics} and {max_rubrics} rubrics that are MOST relevant and meaningful to evaluate for this specific text. Prioritize rubrics where the text actually gives you something to measure — skip rubrics that are inapplicable or would produce trivially high/low scores for any text of this type.

Return a JSON object in exactly this format:
{{
  "selected_rubric_ids": ["id1", "id2", "id3"],
  "reasoning": "one or two sentences explaining why these rubrics matter for this text"
}}

Only use rubric IDs from the list above. Return between {min_rubrics} and {max_rubrics} IDs."""


SCORING_SYSTEM = """You are a precise writing critic. You evaluate text on a single quality dimension and return only valid JSON. You are calibrated: a score of 5 means genuinely average, not "good enough to avoid trouble". Use the full 0-10 range. No markdown, no explanation outside the JSON."""

SCORING_USER = """Evaluate the following text on this single rubric:

Rubric: {rubric_name}
Description: {rubric_description}

Scoring guide:
{scoring_guide}

Text to evaluate:
---
{artifact}
---

Return a JSON object in exactly this format:
{{
  "score": <number from 0 to 10, decimals allowed>,
  "reasoning": "<2-4 sentences explaining the score, citing specific evidence from the text>"
}}

Be honest and specific. Reference actual phrases or passages when possible. Do not inflate scores."""
