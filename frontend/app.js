const textarea = document.getElementById("artifact");
const submitBtn = document.getElementById("submit-btn");
const wordCountEl = document.getElementById("word-count");
const errorBox = document.getElementById("error-box");
const errorMsg = document.getElementById("error-msg");
const loading = document.getElementById("loading");
const loadingMsg = document.getElementById("loading-msg");
const results = document.getElementById("results");
const rubricReasoning = document.getElementById("rubric-reasoning");
const scoresGrid = document.getElementById("scores-grid");
const gapAnalysisEl = document.getElementById("gap-analysis");
const gapListEl = document.getElementById("gap-list");
const nextStepText = document.getElementById("next-step-text");
const nextStepRationale = document.getElementById("next-step-rationale");
const gapUnavailableEl = document.getElementById("gap-unavailable");

// Live word count
textarea.addEventListener("input", () => {
  const words = textarea.value.trim().split(/\s+/).filter(Boolean).length;
  wordCountEl.textContent = `${words} word${words !== 1 ? "s" : ""}`;
});

function showError(msg) {
  errorMsg.textContent = msg;
  errorBox.classList.remove("hidden");
}

function hideAll() {
  errorBox.classList.add("hidden");
  loading.classList.add("hidden");
  results.classList.add("hidden");
}

function scoreBadgeClass(score) {
  if (score === null) return "";
  if (score < 4) return "low";
  if (score < 7) return "mid";
  return "high";
}

function buildScoreCard(item) {
  const card = document.createElement("div");
  card.className = "score-card";

  if (item.error) {
    card.innerHTML = `
      <div class="score-card-header">
        <span class="rubric-name">${item.rubric_name}</span>
        <span class="score-badge mid">?</span>
      </div>
      <p class="score-error">Could not score this rubric (model response failed).</p>
    `;
    return card;
  }

  const badgeClass = scoreBadgeClass(item.avg_score);
  const variance = item.score_variance > 1.5
    ? `<span title="High variance across ${item.runs_completed} runs">±${item.score_variance}</span>`
    : "";
  const reasoning = item.reasonings[0] || "";

  card.innerHTML = `
    <div class="score-card-header">
      <span class="rubric-name">${item.rubric_name}</span>
      <span class="score-badge ${badgeClass}">${item.avg_score}/10</span>
    </div>
    <div class="score-meta">${item.runs_completed} run${item.runs_completed !== 1 ? "s" : ""} averaged ${variance}</div>
    <p class="score-reasoning">${reasoning}</p>
  `;
  return card;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderGapAnalysis(gap, rubricNameById) {
  gapAnalysisEl.classList.add("hidden");
  gapUnavailableEl.classList.add("hidden");

  if (!gap) {
    gapUnavailableEl.classList.remove("hidden");
    return;
  }

  gapListEl.innerHTML = "";
  for (const item of gap.gaps || []) {
    const row = document.createElement("div");
    row.className = "gap-item";
    const name = rubricNameById[item.rubric_id] || item.rubric_id;
    row.innerHTML = `
      <span class="gap-rubric">${escapeHtml(name)}</span>
      <span class="gap-desc">${escapeHtml(item.gap_description)}</span>
    `;
    gapListEl.appendChild(row);
  }

  nextStepText.textContent = gap.next_best_step || "";
  nextStepRationale.textContent = gap.rationale ? `Why: ${gap.rationale}` : "";
  gapAnalysisEl.classList.remove("hidden");
}

async function runEvaluation() {
  const text = textarea.value.trim();

  // Client-side validation (mirrors server-side)
  if (!text) {
    hideAll();
    showError("Please paste some text to evaluate.");
    return;
  }
  const wordCount = text.split(/\s+/).filter(Boolean).length;
  if (wordCount < 10) {
    hideAll();
    showError("The text is too short. Need at least 10 words.");
    return;
  }
  if (text.length > 15000) {
    hideAll();
    showError("Text exceeds 15,000 characters. Please trim it down.");
    return;
  }

  hideAll();
  loading.classList.remove("hidden");
  loadingMsg.textContent = "Selecting rubrics…";
  submitBtn.disabled = true;

  // Update loading message after a moment to indicate scoring has started
  const scoringTimer = setTimeout(() => {
    loadingMsg.textContent = "Scoring each rubric (this takes ~15 seconds)…";
  }, 2500);

  try {
    const resp = await fetch("/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artifact: text }),
    });

    clearTimeout(scoringTimer);

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const detail = err.detail || {};
      if (resp.status === 503) {
        showError("Both AI providers are currently unavailable. Try again in a minute.");
      } else {
        showError(detail.message || `Error ${resp.status}`);
      }
      return;
    }

    const data = await resp.json();

    // Render results
    rubricReasoning.textContent = data.selection?.reasoning || "";
    scoresGrid.innerHTML = "";
    for (const item of data.scores) {
      scoresGrid.appendChild(buildScoreCard(item));
    }

    // Map rubric_id -> rubric_name so gap entries can show a friendly label
    const rubricNameById = {};
    for (const item of data.scores) {
      rubricNameById[item.rubric_id] = item.rubric_name;
    }

    renderGapAnalysis(data.gap_analysis, rubricNameById);

    results.classList.remove("hidden");
  } catch (e) {
    clearTimeout(scoringTimer);
    showError("Network error — is the server running?");
  } finally {
    loading.classList.add("hidden");
    submitBtn.disabled = false;
  }
}
