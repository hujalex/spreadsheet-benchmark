# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A benchmark harness for evaluating LLM agents on three spreadsheet-style tasks against the IBM TabFinDataset (cards / users / transactions):

1. **merge** — left-join a transaction row against the cards table; output a single JSON object.
2. **policy** — apply a tiered credit-limit policy and emit `\boxed{(customer_id, limit), ...}` for over-extended accounts.
3. **memo** — find the merchant state with the largest mean transaction amount; emit two `\boxed{...}` values inside a short memo.

The full task spec lives in `submission/spec.md`; methodology notes in `submission/methodology.md`.

## Architecture

Two parallel training/evaluation backends share one prompt + grader implementation:

- `tinker/` — RL training via the Tinker SDK on a Qwen3 base model with LoRA (rank 32) + Adam + `importance_sampling` loss. The training loop in `tinker/main.py` builds a 3-way mixed batch, samples `group_size` responses per example, computes per-group advantages (`reward − group_mean`), drops degenerate groups (all-zero advantages), and packs `tinker.Datum`s for `forward_backward` + `optim_step`.
- `openai/` — mirrors the same loop using OpenAI Reinforcement Fine-Tuning (RFT). Three modes: `sample` (local sample + grade only — no gradients), `build-jsonl` (write the RFT training file), `rft` (build + submit job). The RFT job uses an inline Python grader (`RFT_PYTHON_GRADER_SOURCE` in `openai/rft.py`) that re-implements the tinker grader logic standalone, since the hosted sandbox can't import this repo. Split across:
  - `openai/main.py` — CLI entry; sets up Phoenix tracing and dispatches on `--mode`.
  - `openai/config.py` — env-derived constants (`MODEL_NAME`, `METRICS_DIR`, Phoenix settings, `MAX_TOKENS`).
  - `openai/tracing.py` — Phoenix/OpenInference setup and `set_span_kind` helper.
  - `openai/batch.py` — module-level CSV loads and per-task example builders + `build_batch(step, per_task)`. Prompt strings here must mirror `tinker/batch.py` exactly.
  - `openai/sampling.py` — `sample_example_async` + `train` loop (the `--mode sample` path).
  - `openai/rft.py` — `RFT_PYTHON_GRADER_SOURCE`, `build_rft_jsonl`, `submit_rft_job`.
  - `openai/metrics.py` — per-step CSV/PNG writers, `annotate_failure`, and `write_failures_markdown` (writes to `metrics_openai/`).
  - The `openai/` directory is intentionally **not** a Python package (no `__init__.py`) to avoid shadowing the `openai` SDK; modules import each other by bare name (e.g. `from batch import build_batch`), which works because Python prepends the script's directory to `sys.path`.

**Shared core lives in `tinker/`** and is imported by both backends:
- `tinker/batch.py` — `build_batch()` and per-task example builders. The exact prompt strings here are load-bearing: any drift between tinker and openai prompts breaks parity. Memo and policy examples are sampled with `random.Random(step)` so step N is reproducible across runs/backends.
- `tinker/grader.py` — `_grade()` dispatches on `example["task"]`. `grade_merge` has a tiered fallback (clean JSON → JSON-in-prose at half credit). `grade_memo` averages two boxed-value checks. Policy grading delegates to `credit_limit_policy.grade_overextended_partial` (per-pair +1 / -1 / +0, normalized to [0, 1]).
- `tinker/credit_limit_policy.py` — vectorized policy logic (`allowed_credit_limit`) and ground-truth generation. Note the policy has a fallback tier: income > 100k AND credit_score < 600 falls back to $15k, not $50k.
- `tinker/tracing.py` — Phoenix/OpenInference tracing setup. Both backends emit `AGENT → CHAIN(step) → CHAIN(example) → LLM(sample) + EVALUATOR(grade)` span hierarchies.
- `tinker/failures.py`, `tinker/metrics.py` — write per-step CSVs, the `training_metrics.png` chart, and a markdown failure rubric to `tinker/metrics/`.

There is also `tinker/main_gemini.py`, an older single-file Gemini variant (uses `google-genai`, no policy-gradient updates — eval only).

## Data and working directory

CSVs live in `tinker/data/` but are loaded with relative paths like `data/cards_data.csv` (see `tinker/batch.py:19` and `openai/batch.py:8`). **You must `cd tinker/` before running either backend**, or `data/` won't resolve.

## Common commands

Activate the venv first (`source venv/bin/activate`). There is no `requirements.txt`/`pyproject.toml` checked in; the venv has the deps already installed.

```bash
# Tinker RL training (writes metrics to tinker/metrics/, traces to Phoenix)
cd tinker && python main.py

# OpenAI: local sample+grade loop only (no fine-tune)
cd tinker && python ../openai/main.py --mode sample --n-steps 10 --batch-size 15 --group-size 8

# OpenAI: build RFT training JSONL
cd tinker && python ../openai/main.py --mode build-jsonl --n-steps 10 --batch-size 15

# OpenAI: build JSONL + submit hosted RFT job
cd tinker && python ../openai/main.py --mode rft

# Gemini eval-only loop
cd tinker && python main_gemini.py
```

Required env vars (loaded via `python-dotenv` from `tinker/.env`):
- `TINKER_API_KEY` — tinker backend
- `OPENAI_API_KEY`, optional `OPENAI_RFT_MODEL` (default `o4-mini-2025-04-16`) — openai backend
- `GEMINI_API_KEY` or `GOOGLE_API_KEY` — gemini backend
- `PHOENIX_COLLECTOR_ENDPOINT` (default `http://localhost:6006/v1/traces`), `PHOENIX_API_KEY`, `PHOENIX_LAUNCH_APP=0` to skip auto-launching the local Phoenix UI.

There are no tests or linters configured.

## Conventions to preserve

- **Prompt parity**: keep the prompt strings identical between `tinker/batch.py` and `openai/batch.py` — they're the contract that lets both backends be compared on the same task.
- **Grader parity**: when changing grading logic in `tinker/grader.py` or `tinker/credit_limit_policy.py`, also update the inline `RFT_PYTHON_GRADER_SOURCE` string in `openai/rft.py` (it runs in an isolated sandbox and can't import).
- **Batch composition**: batches are split evenly across the 3 tasks (`per_task = batch_size // 3`); `batch_size` should stay divisible by 3.
- **Reproducibility**: example builders seed `random.Random(step)` per step. Don't switch to the global `random` module.
