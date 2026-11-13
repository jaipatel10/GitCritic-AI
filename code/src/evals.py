import json
from math import exp
from pathlib import Path
from typing import Literal
from unicodedata import category
from pydantic import BaseModel

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
    agent_text = (agent_finding['messsage'] + " " + agent_finding['rationale']).lower()
    return any(topic.lower() in agent_text for topic in forbidden)

