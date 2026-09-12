import json
from pathlib import Path

import pytest

from ai_presales_copilot.finetuning import dataset_stats, load_conversations, validate_conversation

ROOT = Path(__file__).resolve().parents[1]


def test_generated_finetuning_splits_are_valid() -> None:
    base = ROOT / "data/finetuning"
    train = load_conversations(base / "train.jsonl")
    dev = load_conversations(base / "dev.jsonl")
    test = load_conversations(base / "test.jsonl")
    assert len(train) > len(dev) > 0
    assert len(test) > 0
    assert len({item["id"] for item in train + dev + test}) == len(train + dev + test)
    assert dataset_stats(train)["ids_unique"] is True

    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["generator"] == "scripts/build_finetune_dataset.py"
    assert manifest["metadata"]["system_prompt_version"] == "v2-requirements-first-compact-rag-context"
    assert manifest["metadata"]["target_format"] == "compact_json"
    assert manifest["metadata"]["split_policy"].startswith("deterministic scenario-level")
    assert all(not Path(item["path"]).is_absolute() for item in manifest["files"].values())

    sample = train[0]
    assert '"retrieved_evidence"' in sample["messages"][-2]["content"]
    target = json.loads(sample["messages"][-1]["content"])
    assert "run_id" not in target
    assert "trace_id" not in target
    assert target["case_id"] == sample["metadata"]["case_id"]


def test_invalid_finetuning_conversation_is_rejected() -> None:
    with pytest.raises(ValueError, match="assistant"):
        validate_conversation(
            {
                "id": "bad",
                "messages":[
                    {"role": "user", "content": "hello"},
                    {"role": "user", "content": "still not an answer"},
                ],
            }
        )

    with pytest.raises(ValueError, match="role"):
        validate_conversation(
            {
                "id": "bad-role",
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "tool", "content": "not allowed"},
                ],
            }
        )
