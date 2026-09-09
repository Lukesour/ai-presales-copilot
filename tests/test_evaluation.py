import json
from pathlib import Path

from ai_presales_copilot.evaluation import evaluate_cases, load_cases
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.offline_engine import OfflineSolutionEngine

ROOT = Path(__file__).resolve().parents[1]


def test_evaluation_corpus_has_24_cases() -> None:
    cases = load_cases(ROOT / "data/evaluation/cases.jsonl")
    assert len(cases) == 24
    assert len({case.case_id for case in cases}) == 24


def test_offline_evaluation_produces_schema_safe_report() -> None:
    cases = load_cases(ROOT / "data/evaluation/cases.jsonl")
    engine = OfflineSolutionEngine(KnowledgeBase(ROOT / "data/knowledge"))
    summary, outputs = evaluate_cases(cases, engine.analyze)
    assert summary.total == 24
    assert summary.schema_pass == 24
    assert len(outputs) == 24
    json.dumps(summary.to_dict(), ensure_ascii=False)
