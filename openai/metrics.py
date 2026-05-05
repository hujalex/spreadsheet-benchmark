import json
import os
import re

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from grader import _parse_pairs

from config import METRICS_DIR


def write_metrics(metrics_history: list[dict], instance_metrics: list[dict]) -> None:
    os.makedirs(METRICS_DIR, exist_ok=True)
    steps_df = pd.DataFrame(metrics_history)
    inst_df = pd.DataFrame(instance_metrics)
    steps_path = os.path.join(METRICS_DIR, "training_steps.csv")
    inst_path = os.path.join(METRICS_DIR, "training_instances.csv")
    png_path = os.path.join(METRICS_DIR, "training_metrics.png")
    steps_df.to_csv(steps_path, index=False)
    inst_df.to_csv(inst_path, index=False)

    fig, (ax_inst, ax_step) = plt.subplots(2, 1, figsize=(10, 7), constrained_layout=True)
    colors = {"merge": "tab:blue", "policy": "tab:orange", "memo": "tab:green"}
    for task, color in colors.items():
        sub = inst_df[inst_df["task"] == task]
        if sub.empty:
            continue
        x = sub["step"] + sub["example_index"] / max(inst_df["example_index"].max() + 1, 1)
        ax_inst.scatter(x, sub["failures"], color=color, label=task, alpha=0.7, s=24)
    ax_inst.set_xlabel("step (fractional offset = example index within step)")
    ax_inst.set_ylabel("failures per instance (out of group_size)")
    ax_inst.set_title("Per-instance failures")
    ax_inst.set_ylim(bottom=-0.5)
    ax_inst.legend(loc="upper right")
    ax_inst.grid(True, alpha=0.3)

    ax_step.plot(steps_df["step"], steps_df["reward"], label="overall", color="black", linewidth=2)
    ax_step.plot(steps_df["step"], steps_df["merge"], label="merge", color=colors["merge"])
    ax_step.plot(steps_df["step"], steps_df["policy"], label="policy", color=colors["policy"])
    ax_step.plot(steps_df["step"], steps_df["memo"], label="memo", color=colors["memo"])
    ax_step.plot(steps_df["step"], steps_df["frac_degenerate"], label="frac degenerate",
                 color="tab:red", linestyle="--")
    ax_step.set_xlabel("step")
    ax_step.set_ylabel("value")
    ax_step.set_title("Per-step mean reward and degenerate fraction")
    ax_step.set_ylim(-0.05, 1.05)
    ax_step.legend(loc="best")
    ax_step.grid(True, alpha=0.3)
    fig.savefig(png_path, dpi=120)
    plt.close(fig)
    print(f"Wrote {steps_path}, {inst_path}, {png_path}")


def annotate_failure(ex: dict, response: str) -> str:
    task = ex["task"]
    gt = ex["ground_truth"]
    if task == "merge":
        try:
            parsed = json.loads(response)
        except (json.JSONDecodeError, TypeError) as e:
            return f"response is not valid JSON ({type(e).__name__}: {e})"
        if not isinstance(parsed, dict):
            return f"response parsed to {type(parsed).__name__}, expected dict"
        missing = sorted(set(gt) - set(parsed))
        extra = sorted(set(parsed) - set(gt))
        mismatched = [k for k in gt if k in parsed and parsed[k] != gt[k]]
        notes = []
        if missing:
            notes.append(f"missing keys: {missing}")
        if extra:
            notes.append(f"unexpected keys: {extra}")
        if mismatched:
            preview = {k: {"expected": gt[k], "got": parsed[k]} for k in mismatched[:5]}
            notes.append(f"value mismatches ({len(mismatched)}): {preview}")
        return "; ".join(notes) or "dicts differ but no specific diff found"
    if task == "memo":
        boxes = [m.strip() for m in re.findall(r"\\boxed\{([^}]+)\}", response)]
        if not boxes:
            return r"no \boxed{} found in response"
        state_ok = any(b == gt["state"] for b in boxes)
        amount_ok = any(b.replace(",", "").replace("$", "").strip() == gt["average_amount"] for b in boxes)
        notes = []
        if not state_ok:
            notes.append(f"state box not matched (expected '{gt['state']}', got boxes={boxes})")
        if not amount_ok:
            notes.append(f"amount box not matched (expected '{gt['average_amount']}', got boxes={boxes})")
        return "; ".join(notes) or "all required boxes matched"
    if task == "policy":
        if "\\boxed" not in response:
            return r"no \boxed{} found in response"
        pred = sorted(_parse_pairs(response))
        gold = sorted(_parse_pairs(gt))
        missing = [p for p in gold if p not in pred]
        extra = [p for p in pred if p not in gold]
        notes = []
        if missing:
            notes.append(f"missing pairs ({len(missing)}): {missing[:8]}")
        if extra:
            notes.append(f"extraneous pairs ({len(extra)}): {extra[:8]}")
        return "; ".join(notes) or "pairs match (graded as correct)"
    return f"unknown task: {task}"


def write_failures_markdown(failures: list[dict]) -> None:
    os.makedirs(METRICS_DIR, exist_ok=True)
    md_path = os.path.join(METRICS_DIR, "training_failures_latest.md")
    by_task: dict[str, list[dict]] = {}
    for f in failures:
        by_task.setdefault(f["task"], []).append(f)

    lines = ["# Training Failures", "",
             f"Recorded **{len(failures)}** sample(s) with reward < 1.0."]
    for task, items in sorted(by_task.items()):
        lines.append(f"- `{task}`: {len(items)}")
    lines.append("")

    for task, items in sorted(by_task.items()):
        lines.append(f"## {task} ({len(items)})")
        lines.append("")
        for f in items:
            lines.append(
                f"### step {f['step']} · example {f['example_index']} · "
                f"sample {f['sample_index']} · reward {f['reward']:.2f}"
            )
            lines.append("")
            lines.append(f"**Annotation:** {f['annotation']}")
            lines.append("")
            lines.append("**Ground truth:**")
            lines.append("```")
            lines.append(str(f["ground_truth"]))
            lines.append("```")
            lines.append("**Response:**")
            lines.append("```")
            lines.append(f["response"] or "")
            lines.append("```")
            lines.append("")

    with open(md_path, "w") as fp:
        fp.write("\n".join(lines))
    print(f"Wrote {md_path}")
