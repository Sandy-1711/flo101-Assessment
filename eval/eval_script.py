"""
Critic Agent — evaluation script.

Runs each golden set entry through the live /evaluate endpoint and measures:
  1. Rubric recall   — fraction of must_include rubrics that were selected
  2. Rubric precision — count of must_exclude rubrics that were selected (violations)
  3. Score accuracy  — fraction of avg_scores within expected [min, max] range

Usage:
  python eval_script.py --golden golden_set.json --api-url http://localhost:8000

Exit code 0 if all targets met, 1 otherwise.
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error


RECALL_TARGET = 0.85
SCORE_ACCURACY_TARGET = 0.80
MAX_EXCLUDE_VIOLATIONS = 0


def post_evaluate(api_url: str, artifact: str) -> dict:
    payload = json.dumps({"artifact": artifact}).encode()
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/evaluate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def evaluate_entry(api_url: str, entry: dict) -> dict:
    """Run one golden entry and return structured metrics."""
    label = entry["label"]
    artifact = entry["artifact"]
    expected_rubrics = entry["expected_rubrics"]
    expected_scores = entry.get("expected_scores", {})

    print(f"\n  [{entry['id']}] {label}")
    print("  Calling /evaluate ...", end="", flush=True)

    try:
        result = post_evaluate(api_url, artifact)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f" HTTP {e.code}: {body}")
        return {"id": entry["id"], "label": label, "error": f"HTTP {e.code}"}
    except Exception as e:
        print(f" ERROR: {e}")
        return {"id": entry["id"], "label": label, "error": str(e)}

    print(" done")

    selected_ids = set(result.get("selection", {}).get("selected_rubric_ids", []))
    scores_map = {s["rubric_id"]: s["avg_score"] for s in result.get("scores", []) if s.get("avg_score") is not None}

    # Rubric recall: must_include
    must_include = expected_rubrics.get("must_include", [])
    hits = [rid for rid in must_include if rid in selected_ids]
    recall = len(hits) / len(must_include) if must_include else 1.0

    # Rubric precision: must_exclude
    must_exclude = expected_rubrics.get("must_exclude", [])
    violations = [rid for rid in must_exclude if rid in selected_ids]

    # Score accuracy
    in_range = 0
    checked = 0
    score_details = []
    for rubric_id, bounds in expected_scores.items():
        if rubric_id not in scores_map:
            score_details.append(f"    {rubric_id}: NOT SCORED (not selected or failed)")
            continue
        actual = scores_map[rubric_id]
        lo, hi = bounds["min"], bounds["max"]
        ok = lo <= actual <= hi
        in_range += int(ok)
        checked += 1
        status = "OK" if ok else f"OUT [{lo}-{hi}]"
        score_details.append(f"    {rubric_id}: {actual} {status}")

    score_acc = in_range / checked if checked > 0 else None

    # Print detail
    print(f"  Selected rubrics : {sorted(selected_ids)}")
    print(f"  Must-include     : {must_include}  => recall {recall:.2f}")
    if violations:
        print(f"  Must-exclude VIOLATED: {violations}")
    print(f"  Scores:")
    for line in score_details:
        print(line)
    if score_acc is not None:
        print(f"  Score accuracy   : {in_range}/{checked} = {score_acc:.2f}")

    return {
        "id": entry["id"],
        "label": label,
        "selected_ids": sorted(selected_ids),
        "recall": recall,
        "exclude_violations": violations,
        "score_accuracy": score_acc,
        "in_range": in_range,
        "checked": checked,
        "error": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", default="golden_set.json")
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()

    with open(args.golden) as f:
        golden = json.load(f)

    entries = golden["entries"]
    print(f"\nCritic Agent Eval — {len(entries)} entries against {args.api_url}")
    print("=" * 60)

    results = []
    for i, entry in enumerate(entries):
        if i > 0:
            # Brief pause to avoid hammering the API
            time.sleep(1)
        r = evaluate_entry(args.api_url, entry)
        results.append(r)

    # Aggregate
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    errored = [r for r in results if r.get("error")]
    valid = [r for r in results if not r.get("error")]

    if errored:
        print(f"  Errors: {len(errored)} entries failed ({[r['id'] for r in errored]})")

    if not valid:
        print("  No valid results to aggregate.")
        sys.exit(1)

    # Recall
    recalls = [r["recall"] for r in valid]
    mean_recall = sum(recalls) / len(recalls)

    # Exclude violations
    total_violations = sum(len(r["exclude_violations"]) for r in valid)

    # Score accuracy
    total_in_range = sum(r["in_range"] for r in valid if r["score_accuracy"] is not None)
    total_checked = sum(r["checked"] for r in valid if r["score_accuracy"] is not None)
    mean_score_acc = total_in_range / total_checked if total_checked > 0 else None

    print(f"\n  Rubric recall (must_include)  : {mean_recall:.2f}  [target >= {RECALL_TARGET}]")
    print(f"  Exclude violations           : {total_violations}    [target = {MAX_EXCLUDE_VIOLATIONS}]")
    if mean_score_acc is not None:
        print(f"  Score accuracy (in-range)    : {mean_score_acc:.2f}  [target >= {SCORE_ACCURACY_TARGET}]")
    else:
        print(f"  Score accuracy               : N/A (no rubrics checked)")

    # Pass/fail
    recall_ok = mean_recall >= RECALL_TARGET
    violations_ok = total_violations <= MAX_EXCLUDE_VIOLATIONS
    score_ok = mean_score_acc is None or mean_score_acc >= SCORE_ACCURACY_TARGET

    print("\n  Results:")
    print(f"    Rubric recall   : {'PASS' if recall_ok else 'FAIL'}")
    print(f"    Exclude check   : {'PASS' if violations_ok else 'FAIL'}")
    print(f"    Score accuracy  : {'PASS' if score_ok else 'FAIL'}")

    all_pass = recall_ok and violations_ok and score_ok
    print(f"\n  Overall: {'PASS' if all_pass else 'FAIL'}")
    print()

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
