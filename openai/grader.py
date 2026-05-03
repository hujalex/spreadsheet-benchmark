import json
import re
from collections import Counter

import pandas as pd

# from tinker.credit_limit_policy import grade_overextended_partial
_PAIR_RE = re.compile(r"\(\s*(-?\d+)\s*,\s*\$?\s*([\d,]+)\s*\)")
_BOXED_RE = re.compile(r"\\boxed\{(.*)\}", re.DOTALL)


def merge_cards_transactions(cards: pd.DataFrame, transactions: pd.DataFrame) -> pd.DataFrame:
        return transactions.merge(cards, how='left', left_on='card_id', right_on='id', suffixes = ('_tx', '_card'))

def merge_clients_transactions(clients: pd.DataFrame, transactions: pd.DataFrame) -> pd.DataFrame:
        return transactions.merge(clients, how='left', left_on='client_id', right_on='id', suffixes = ('_tx', '_card'))

def merge_merchants_transactions(merchants: pd.DataFrame, transactions: pd.DataFrame) -> pd.DataFrame:
        return transactions.merge(merchants, how='left', left_on='client_id', right_on='id', suffixes = ('_tx', '_card'))

def get_state_largest_mean_transaction(transactions: pd.DataFrame):
        transactions = transactions.copy()
        transactions['amount'] = transactions['amount'].astype(str).str.replace(r'[^\d.-]', '', regex=True)
        transactions['amount'] = pd.to_numeric(transactions['amount'])
        state_means = transactions.dropna(subset=['merchant_state']).groupby('merchant_state')['amount'].mean().nlargest(1)
        return state_means.index[0], f"{float(state_means.iloc[0]):.2f}"

def _grade(response: str, example: dict, n_tokens: int = 0) -> float:
        if example["task"] == "merge":
            base = grade_merge(response, example["ground_truth"])
        elif example["task"] == "memo":
            base = grade_memo(response, example["ground_truth"])
        else:
            base = grade_overextended_partial(response, example["ground_truth"])
        # Length penalty: apply only when answer is at least partially correct,
        # so wrong-and-short doesn't beat wrong-and-long. λ=0.05 keeps correctness dominant.
        # if base > 0 and n_tokens > 0:
            # return max(0.0, base - 0.05 * (n_tokens / 512))
        return base
    
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

def grade_memo(response: str, expected: dict) -> float:
        boxes = [m.strip() for m in re.findall(r"\\boxed\{([^}]+)\}", response)]
        state_ok = any(b == expected["state"] for b in boxes)
        amount_ok = any(b.replace(",", "").replace("$", "").strip() == expected["average_amount"] for b in boxes)
        return (state_ok + amount_ok) / 2.0
    
def grade_answer(response: str, ground_truth: str) -> float:
        answer = extract_boxed(response)
        if answer is None:
            return 0.0
        answer = answer.replace(",", "").strip()
        ground_truth = ground_truth.replace(",", "").strip()
        return 1.0 if answer == ground_truth else 0.0
    
def extract_boxed(text: str) -> str | None:
        match = re.findall(r"\\boxed\{([^}]+)\}", text)
        if match:
            return match[-1].strip()
        return None

def grade_overextended(response: str, ground_truth: str) -> float:
    """Sort both sides by Customer ID then compare. 1.0 == exact match."""
    pred = sorted(_parse_pairs(response))
    gold = sorted(_parse_pairs(ground_truth))
    return 1.0 if pred == gold else 0.0


def grade_overextended_partial(response: str, ground_truth: str) -> float:
    """Partial-credit policy grade normalized to a maximum score of 1.0.

    Scoring:
    - +1 for each response pair that matches the ground truth.
    - -1 for each response pair not found in the ground truth.
    - +0 for each ground-truth pair not found in the response.

    Duplicate response entries are treated as separate entries, so repeating a
    correct pair more times than it appears in the ground truth is penalized.
    """
    pred = Counter(_parse_pairs(response))
    gold = Counter(_parse_pairs(ground_truth))

    if not gold:
        return 1.0 if not pred else 0.0

    matches = sum((pred & gold).values())
    extraneous = sum((pred - gold).values())
    score = (matches - extraneous) / sum(gold.values())
    return max(0.0, min(1.0, score))

def _parse_pairs(text: str) -> list[tuple[int, int]]:
    """Pull (id, limit) pairs from a `\\boxed{...}` blob (or a raw list).
    Tolerant to `$`, commas, and whitespace.
    """
    if text is None:
        return []
    m = _BOXED_RE.search(text)
    body = m.group(1) if m else text
    return [
        (int(cid), int(lim.replace(",", "")))
        for cid, lim in _PAIR_RE.findall(body)
    ]
