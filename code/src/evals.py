import json
from math import exp
from pathlib import Path
from typing import Literal
from unicodedata import category
from pydantic import BaseModel
from review_pr import review_diff_with_context

class ExpectedFinding(BaseModel):
    category: Literal['security', 'performance', 'logic', 'style']
    min_severity: Literal['low', 'medium', 'high', 'critical']
    topic: str
    description: str

class EvalCase(BaseModel):
    pr_id: str
    source: str
    difficulty: Literal['easy', 'medium', 'hard']
    description: str
    diff_path: str
    expected_findings: list[ExpectedFinding]
    forbidden_findings: list[str] = []
    notes: str = ""

class EvalResult(BaseModel):
    pr_id: str
    true_positives: int
    false_negatives: int
    false_positives: int
    other_findings: int
    precision: float
    recall: float
    f1: float
    agent_findings_raw: list[dict]

def load_eval_dataset(path: Path) -> list[EvalCase]:
    """Load all eval cases from a JSON file."""
    data = json.loads(path.read_text())
    return [EvalCase(**case) for case in data]

def match_finding(agent_finding:dict, expected: ExpectedFinding) -> bool:
    """Does this agent\'s finding matches with expected findings?
    
    Semantic matching: Same category, severity >= min_severity + topic keywords present in agent's message or rationale. 
    """
    SEVERITY_ORDER = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}

    if agent_finding['category'] != expected.category:
        return False
    if SEVERITY_ORDER[agent_finding['severity']] < SEVERITY_ORDER[expected.min_severity]:
        return False
    
    # Topic keyword match
    agent_text = (agent_finding['message'] + " " + agent_finding['rationale']).lower()
    topic_keywords = [kw.strip() for kw in expected.topic.lower().split()]
    # Atleast half the keywords should appear
    matches = sum(1 for kw in topic_keywords if kw in agent_text)
    return matches >= len(topic_keywords)/2

def is_forbidden(agent_finding:dict, forbidden: list[str]) -> bool:
    """Is this agent finding a known false poistive topic?"""
    agent_text = (agent_finding['message'] + " " + agent_finding['rationale']).lower()
    return any(topic.lower() in agent_text for topic in forbidden)

def evaluate_case(case: EvalCase, agent_findings: list[dict]) -> EvalResult:
    """Score agent findings against expected + forbidden lists."""
    expected = case.expected_findings

    # Mark expected findings as caught or missed
    caught = set()
    for i, exp in enumerate(expected):
        for af in agent_findings:
            if match_finding(af, exp):
                caught.add(i)
                break
        
    tp = len(caught)
    fn = len(expected) - tp

    #Mark agent findings as true positives, false positives, or other
    fp = 0
    other = 0
    for af in agent_findings:
        matched_expected = any(match_finding(af, exp) for exp in expected)
        if matched_expected:
            continue
        if is_forbidden(af, case.forbidden_findings):
            fp += 1
        else:
            other += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0  else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

    return EvalResult(
        pr_id=case.pr_id,
        true_positives=tp,
        false_negatives=fn,
        false_positives=fp,
        other_findings=other,
        precision=precision,
        recall=recall,
        f1=f1,
        agent_findings_raw=agent_findings
    )

def run_full_eval(dataset_path: Path, codebase_path: Path, results_path: Path):
    """Run every eval case, save results"""
    cases = load_eval_dataset(dataset_path)
    results = []

    for i, case in enumerate(cases):
        print(f'[{i+1}/{len(cases)}] {case.pr_id} ({case.difficulty})...')

        diff_text = Path(case.diff_path).read_text()
        review = review_diff_with_context(diff_text, codebase_path)

        #Convert findings into dict for scoring
        agent_findings = [f.model_dump() for f in review.findings]
        result = evaluate_case(case, agent_findings)
        results.append(result)

        print(f'precision={result.precision:.2f} recall={result.recall:.2f} f1={result.f1:.2f}')

    # Aggregate
    total_precision = sum(r.precision for r in results) / len(results)
    total_recall = sum(r.recall for r in results) / len(results)
    total_f1 = sum(r.f1 for r in results) / len(results)

    print(f"\n=== Overall ===")
    print(f"Avg precision: {total_precision:.3f}")
    print(f"Avg recall:    {total_recall:.3f}")
    print(f"Avg F1:        {total_f1:.3f}")

    # By difficulty
    for diff_level in ["easy", "medium", "hard"]:
        subset = [r for r, c in zip(results, cases) if c.difficulty == diff_level]
        if subset:
            avg_f1 = sum(r.f1 for r in subset) / len(subset)
            print(f"{diff_level:8s}: F1={avg_f1:.3f}  (n={len(subset)})")
    
    # Save
    results_path.write_text(json.dumps([r.model_dump() for r in results], indent=2))
    print(f"\nResults saved to {results_path}")

if __name__ == "__main__":
    run_full_eval(
        Path("code/tests/eval_dataset.json"),
        Path("/Users/jay/applied-ai-journey"),
        Path("code/tests/eval_results.json"),
    )