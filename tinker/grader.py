import json
import re
from tinker.credit_limit_policy import grade_overextended_partial

class Grader:

    @staticmethod
    def _grade(response: str, example: dict, n_tokens: int = 0) -> float:
        if example["task"] == "merge":
            base = Grader.grade_merge(response, example["ground_truth"])
        elif example["task"] == "memo":
            base = Grader.grade_memo(response, example["ground_truth"])
        else:
            base = grade_overextended_partial(response, example["ground_truth"])
        # Length penalty: apply only when answer is at least partially correct,
        # so wrong-and-short doesn't beat wrong-and-long. λ=0.05 keeps correctness dominant.
        # if base > 0 and n_tokens > 0:
            # return max(0.0, base - 0.05 * (n_tokens / 512))
        return base
    
    @staticmethod
    def grade_merge(response: str, expected: dict) -> float:
        # Tier 1: clean output parses as-is
        try:
            if json.loads(response) == expected:
                return 1.0
        except (json.JSONDecodeError, TypeError):
            pass
        # Tier 2: correct JSON buried in surrounding prose
        for candidate in re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL):
            try:
                if json.loads(candidate) == expected:
                    return 0.5
            except (json.JSONDecodeError, TypeError):
                continue
        return 0.0
    
    @staticmethod
    def grade_memo(response: str, expected: dict) -> float:
        boxes = [m.strip() for m in re.findall(r"\\boxed\{([^}]+)\}", response)]
        state_ok = any(b == expected["state"] for b in boxes)
        amount_ok = any(b.replace(",", "").replace("$", "").strip() == expected["average_amount"] for b in boxes)
        return (state_ok + amount_ok) / 2.0
    
    @staticmethod
    def grade_answer(response: str, ground_truth: str) -> float:
        answer = Grader.extract_boxed(response)
        if answer is None:
            return 0.0
        answer = answer.replace(",", "").strip()
        ground_truth = ground_truth.replace(",", "").strip()
        return 1.0 if answer == ground_truth else 0.0
    
    @staticmethod
    def extract_boxed(text: str) -> str | None:
        match = re.findall(r"\\boxed\{([^}]+)\}", text)
        if match:
            return match[-1].strip()
        return None
