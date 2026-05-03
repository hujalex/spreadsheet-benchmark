import json
import re

from grader import _parse_pairs


class FailureRecorder:
    def __init__(self):
        self._failures: list[dict] = []

    def record(self, *, step: int, example_index: int, sample_index: int,
               ex: dict, reward: float, response: str) -> None:
        self._failures.append({
            "step": step,
            "example_index": example_index,
            "sample_index": sample_index,
            "task": ex["task"],
            "reward": reward,
            "response": response,
            "ground_truth": ex["ground_truth"],
            "annotation": _annotate(ex, response),
        })

    def write_markdown(self, path: str) -> None:
        by_task: dict[str, list[dict]] = {}
        for f in self._failures:
            by_task.setdefault(f["task"], []).append(f)

        lines: list[str] = ["# Training Failures", ""]
        lines.append(f"Recorded **{len(self._failures)}** sample(s) with reward < 1.0.")
        for task, items in sorted(by_task.items()):
            lines.append(f"- `{task}`: {len(items)}")
        lines.append("")

        for task, items in sorted(by_task.items()):
            lines.append(f"## {task} ({len(items)})")
            lines.append("")
            for f in items:
                resp = f["response"] or ""
                gt = str(f["ground_truth"])
                lines.append(
                    f"### step {f['step']} · example {f['example_index']} · "
                    f"sample {f['sample_index']} · reward {f['reward']:.2f}"
                )
                lines.append("")
                lines.append(f"**Annotation:** {f['annotation']}")
                lines.append("")
                lines.append("**Ground truth:**")
                lines.append("```")
                lines.append(gt)
                lines.append("```")
                lines.append("**Response:**")
                lines.append("```")
                lines.append(resp)
                lines.append("```")
                lines.append("")

        with open(path, "w") as fp:
            fp.write("\n".join(lines))
        print(f"Wrote {path}")


def _annotate(ex: dict, response: str) -> str:
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
