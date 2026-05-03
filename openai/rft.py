import json
import os

from batch import build_batch


# OpenAI's "python" grader runs this source in a sandbox. It must define
# `grade(sample, item) -> float` returning a reward in [0, 1].
RFT_PYTHON_GRADER_SOURCE = r'''
import json, re
from collections import Counter

_PAIR_RE = re.compile(r"\(\s*(-?\d+)\s*,\s*\$?\s*([\d,]+)\s*\)")
_BOXED_RE = re.compile(r"\\boxed\{(.*)\}", re.DOTALL)

def _parse_pairs(text):
    if not text:
        return []
    m = _BOXED_RE.search(text)
    body = m.group(1) if m else text
    return [(int(c), int(l.replace(",", ""))) for c, l in _PAIR_RE.findall(body)]

def _grade_merge(response, expected):
    try:
        if json.loads(response) == expected:
            return 1.0
    except Exception:
        pass
    for cand in re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response or "", re.DOTALL):
        try:
            if json.loads(cand) == expected:
                return 0.5
        except Exception:
            continue
    return 0.0

def _grade_memo(response, expected):
    boxes = [m.strip() for m in re.findall(r"\\boxed\{([^}]+)\}", response or "")]
    state_ok = any(b == expected["state"] for b in boxes)
    amount_ok = any(b.replace(",", "").replace("$", "").strip() == expected["average_amount"] for b in boxes)
    return (state_ok + amount_ok) / 2.0

def _grade_policy(response, ground_truth):
    pred = Counter(_parse_pairs(response))
    gold = Counter(_parse_pairs(ground_truth))
    if not gold:
        return 1.0 if not pred else 0.0
    matches = sum((pred & gold).values())
    extra = sum((pred - gold).values())
    return max(0.0, min(1.0, (matches - extra) / sum(gold.values())))

def grade(sample, item) -> float:
    response = sample["output_text"]
    task = item["task"]
    gt = item["ground_truth"]
    if task == "merge":
        return _grade_merge(response, gt)
    if task == "memo":
        return _grade_memo(response, gt)
    if task == "policy":
        return _grade_policy(response, gt)
    return 0.0
'''


def build_rft_jsonl(n_steps: int, batch_size: int, out_path: str) -> str:
    """Build the JSONL training file for OpenAI Reinforcement Fine-Tuning.

    Each line is {"messages": [...], "task": ..., "ground_truth": ...} —
    the python grader reads `task` and `ground_truth` from the item.
    """
    per_task = batch_size // 3
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    n = 0
    with open(out_path, "w") as fp:
        for step in range(n_steps):
            for ex in build_batch(step, per_task):
                record = {
                    "messages": [{"role": "user", "content": ex["question"]}],
                    "task": ex["task"],
                    "ground_truth": ex["ground_truth"],
                }
                fp.write(json.dumps(record) + "\n")
                n += 1
    print(f"Wrote {n} RFT examples to {out_path}")
    return out_path


def submit_rft_job(client, training_file_path: str, model_name: str, *, n_epochs: int = 1):
    """Upload training file and create a Reinforcement Fine-Tuning job."""
    upload = client.files.create(file=open(training_file_path, "rb"), purpose="fine-tune")
    print(f"Uploaded training file: {upload.id}")

    job = client.fine_tuning.jobs.create(
        training_file=upload.id,
        model=model_name,
        method={
            "type": "reinforcement",
            "reinforcement": {
                "grader": {
                    "type": "python",
                    "source": RFT_PYTHON_GRADER_SOURCE,
                },
                "hyperparameters": {
                    "n_epochs": n_epochs,
                    # additional knobs (reasoning_effort, eval_samples, etc.)
                    # can be set here; defaults are reasonable for a smoke run.
                },
            },
        },
    )
    print(f"Created RFT job: {job.id} (status={job.status})")
    return job
