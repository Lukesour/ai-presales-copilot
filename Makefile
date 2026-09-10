PYTHON ?= python3
PYTHONPATH := src

.PHONY: test lint demo eval agent-eval security-check dataset-check build-finetune-dataset finetune-token-audit finetune-dry-run finetune-eval benchmark-llama summarize-benchmarks dify-check schema-export ingest self-qa lock-check compose-config

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check src scripts tests demo/gradio_app.py

lock-check:
	$(PYTHON) -m uv lock --check

schema-export:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/export_schemas.py

ingest:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/ingest_sources.py

self-qa:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/build_self_qa.py --input data/finetuning/train.jsonl

compose-config:
	docker compose -f deploy/compose.agent.yaml config

demo:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_demo.py --case-id case-001

eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_eval.py --output data/results/offline-evaluation.json

agent-eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_agent_eval.py --output data/results/agent-evaluation.json

security-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_security_checks.py --output data/results/security-evaluation.json

dataset-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_finetune_dataset.py

build-finetune-dataset:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/build_finetune_dataset.py

finetune-token-audit:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/audit_finetune_tokens.py --max-length 5120 --strict

finetune-dry-run:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/train_qlora.py --dry-run

finetune-eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/evaluate_finetuned_model.py

benchmark-llama:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/benchmark_llama.py --output data/results/llama-benchmark.json

summarize-benchmarks:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/summarize_benchmarks.py data/results/q4-metal-c1.json data/results/q8-metal-c1.json --output data/results/q4-q8-summary.json

dify-check:
	./scripts/check_dify.sh
