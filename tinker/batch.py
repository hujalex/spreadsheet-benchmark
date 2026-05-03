import random
from dataclasses import dataclass

import pandas as pd

from credit_limit_policy import find_overextended_accounts
from grader import merge_cards_transactions, get_state_largest_mean_transaction


@dataclass
class FinanceTables:
    cards: pd.DataFrame
    transactions: pd.DataFrame
    users: pd.DataFrame


def load_finance_tables() -> FinanceTables:
    return FinanceTables(
        cards=pd.read_csv("data/cards_data.csv"),
        transactions=pd.read_csv("data/transactions_data.csv"),
        users=pd.read_csv("data/users_data.csv"),
    )


def build_batch(step: int, per_task: int, *, tables: FinanceTables, renderer) -> list[dict]:
    """Build a 3-way mixed batch: `per_task` merge + `per_task` policy + `per_task` memo."""
    examples: list[dict] = []

    merge_rows = tables.transactions.iloc[step * per_task : (step + 1) * per_task]
    for _, transaction in merge_rows.iterrows():
        examples.append(_build_merge_example(transaction, tables, renderer))

    rng = random.Random(step)
    user_ids = list(tables.users["id"])
    chunk_size = 10
    for _ in range(per_task):
        sampled_ids = rng.sample(user_ids, k=chunk_size)
        examples.append(_build_policy_example(sampled_ids, tables, renderer))

    memo_chunk_size = 25
    n_tx = len(tables.transactions)
    for _ in range(per_task):
        idxs = rng.sample(range(n_tx), k=memo_chunk_size)
        tx_chunk = tables.transactions.iloc[idxs]
        examples.append(_build_memo_example(tx_chunk, renderer))

    return examples


def _build_merge_example(transaction: pd.Series, tables: FinanceTables, renderer) -> dict:
    cards = tables.cards
    card_id = transaction["card_id"]
    matching = cards[cards["id"] == card_id]
    distractors = cards[cards["id"] != card_id].head(4)
    cards_slice = pd.concat([matching, distractors]).reset_index(drop=True)

    question = (
        "Output exactly one JSON object — no other text. "
        "Left-join the transaction below with its matching card row "
        "(transaction.card_id == cards.id). "
        "Overlapping columns get suffix '_tx' (from transaction) or '_card' (from card): "
        "use id_tx, id_card, client_id_tx, client_id_card. "
        "Use null for missing values.\n\n"
        f"Transaction: {transaction.to_json()}\n\n"
        f"Cards: {cards_slice.to_json(orient='records')}"
    )
    convo = [{"role": "user", "content": question}]
    prompt = renderer.build_generation_prompt(convo, prefill="{")

    gt_row = merge_cards_transactions(cards, pd.DataFrame([transaction])).iloc[0].to_dict()
    ground_truth = {k: (None if pd.isna(v) else v) for k, v in gt_row.items()}

    return {"task": "merge", "prompt": prompt, "question": question,
            "ground_truth": ground_truth, "prefill": "{"}


def _build_policy_example(user_ids: list[int], tables: FinanceTables, renderer) -> dict:
    users_chunk = tables.users[tables.users["id"].isin(user_ids)].reset_index(drop=True)
    cards_chunk = tables.cards[tables.cards["client_id"].isin(user_ids)].reset_index(drop=True)

    credit_limit_by_tiers = '''
    Assign $5,000 limit for yearly_income under $40,000;
    $15,000 limit between $40,000-$100,000; $50,000 limit above $100,000 unless
    credit_score is below 600.
    '''

    question = ("### TASK: IDENTIFY OVER-EXTENDED ACCOUNTS\n"
        f"RULE: {credit_limit_by_tiers}\n\n"
        "### CRITICAL CONSTRAINTS:\n"
        "1. OUTPUT ONLY the list of accounts.\n"
        "2. DO NOT include any introductory text, explanations, or concluding remarks.\n"
        "3. FORMAT: Only output a sequence of boxed tuples like this: \\boxed{(Customer ID, Limit),}\n\n"
        f"### DATA:\n"
        f"Users: {users_chunk.to_json(orient='records')}\n"
        f"Cards: {cards_chunk.to_json(orient='records')}\n\n"
        "### OUTPUT:"
    )
    convo = [{"role": "user", "content": question}]
    prompt = renderer.build_generation_prompt(convo)

    ground_truth = find_overextended_accounts(users_chunk, cards_chunk)

    return {"task": "policy", "prompt": prompt, "question": question,
            "ground_truth": ground_truth}


def _build_memo_example(transactions: pd.DataFrame, renderer) -> dict:
    transactions = transactions.reset_index(drop=True)

    question = (
        "Below is a batch of transactions. Write a short memo (<20 words) identifying the "
        "merchant_state with the largest average transaction amount. Include "
        "the identified state inside one \\boxed{...} and that state's average "
        "transaction amount (rounded to two decimal places) inside another "
        "\\boxed{...}. The two boxes may appear anywhere in the memo.\n\n"
        f"Transactions: {transactions.to_json(orient='records')}"
    )
    convo = [{"role": "user", "content": question}]
    prompt = renderer.build_generation_prompt(convo)

    state, avg_amount = get_state_largest_mean_transaction(transactions)
    ground_truth = {"state": state, "average_amount": avg_amount}

    return {"task": "memo", "prompt": prompt, "question": question,
            "ground_truth": ground_truth}
