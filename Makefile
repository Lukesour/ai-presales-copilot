PYTHON ?= python3
PYTHONPATH := src
SECURITY_OUTPUT ?= data/results/security-evaluation.json
EVAL_OUTPUT ?= data/results/offline-evaluation.json

.PHONY: governance openapi-build openapi-check file-length test lint demo demo-live eval security-check dataset-check build-finetune-dataset finetune-token-audit finetune-dry-run finetune-eval benchmark-llama summarize-benchmarks dify-check schema-export schema-check ingest self-qa lock-check compose-config demo-replay-check replay-manifest-check demo-capture

governance:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_governance.py

openapi-build:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/build_openapi.py

openapi-check:
	PYTHONPATH=$(PYTHONPATH) uv run --locked --extra runtime --extra dev python scripts/check_openapi.py

file-length:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_file_length.py

test:
	PYTHONPATH=src:. uv run --locked --extra runtime --extra dev pytest -q

lint:
	PYTHONPATH=src:. uv run --locked --extra runtime --extra dev ruff check src scripts tests migrations demo/gradio_app.py

lock-check:
	$(PYTHON) -m uv lock --check

schema-export:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/export_schemas.py

schema-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/export_schemas.py --check

ingest:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/ingest_sources.py

self-qa:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/build_self_qa.py --input data/finetuning/train.jsonl

compose-config:
	docker compose -f deploy/compose.agent.yaml config

demo-replay-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_demo_replays.py
	$(MAKE) replay-manifest-check

replay-manifest-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/check_replay_manifest.py

demo-capture:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/capture_demo_replays.py

demo:
	$(MAKE) demo-live

demo-live:
	PYTHONPATH=src:. uv run --locked --extra runtime --extra demo python scripts/start_local_demo.py

eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_eval.py --output $(EVAL_OUTPUT)

security-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_security_checks.py --output $(SECURITY_OUTPUT)

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
