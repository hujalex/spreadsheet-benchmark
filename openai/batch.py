import random

import pandas as pd

from credit_limit_policy import find_overextended_accounts

# Loaded with cwd = tinker/ (see CLAUDE.md).
fin_tr_cards = pd.read_csv("data/cards_data.csv")
fin_tr_transactions = pd.read_csv("data/transactions_data.csv")
fin_tr_users = pd.read_csv("data/users_data.csv")


def merge_cards_transactions(cards: pd.DataFrame, transactions: pd.DataFrame) -> pd.DataFrame:
    return transactions.merge(cards, how="left", left_on="card_id", right_on="id",
                              suffixes=("_tx", "_card"))


def get_state_largest_mean_transaction(transactions: pd.DataFrame):
    transactions = transactions.copy()
    transactions["amount"] = transactions["amount"].astype(str).str.replace(r"[^\d.-]", "", regex=True)
    transactions["amount"] = pd.to_numeric(transactions["amount"])
    state_means = transactions.dropna(subset=["merchant_state"]).groupby("merchant_state")["amount"].mean().nlargest(1)
    return state_means.index[0], f"{float(state_means.iloc[0]):.2f}"


def build_merge_example(transaction: pd.Series) -> dict:
    cards = fin_tr_cards
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
    gt_row = merge_cards_transactions(cards, pd.DataFrame([transaction])).iloc[0].to_dict()
    ground_truth = {k: (None if pd.isna(v) else v) for k, v in gt_row.items()}
    return {"task": "merge", "question": question, "ground_truth": ground_truth, "prefill": "{"}


def build_policy_example(user_ids: list[int]) -> dict:
    users_chunk = fin_tr_users[fin_tr_users["id"].isin(user_ids)].reset_index(drop=True)
    cards_chunk = fin_tr_cards[fin_tr_cards["client_id"].isin(user_ids)].reset_index(drop=True)
    credit_limit_by_tiers = (
        "Assign $5,000 limit for yearly_income under $40,000; "
        "$15,000 limit between $40,000-$100,000; $50,000 limit above $100,000 unless "
        "credit_score is below 600."
    )
    question = (
        "### TASK: IDENTIFY OVER-EXTENDED ACCOUNTS\n"
        f"RULE: {credit_limit_by_tiers}\n\n"
        "### CRITICAL CONSTRAINTS:\n"
        "1. OUTPUT ONLY the list of accounts.\n"
        "2. DO NOT include any introductory text, explanations, or concluding remarks.\n"
        "3. FORMAT: Only output a sequence of boxed tuples like this: \\boxed{(Customer ID, Limit),}\n\n"
        "### DATA:\n"
        f"Users: {users_chunk.to_json(orient='records')}\n"
        f"Cards: {cards_chunk.to_json(orient='records')}\n\n"
        "### OUTPUT:"
    )
    ground_truth = find_overextended_accounts(users_chunk, cards_chunk)
    return {"task": "policy", "question": question, "ground_truth": ground_truth}


def build_memo_example(transactions: pd.DataFrame) -> dict:
    transactions = transactions.reset_index(drop=True)
    question = (
        "Below is a batch of transactions. Write a short memo (<20 words) identifying the "
        "merchant_state with the largest average transaction amount. Include "
        "the identified state inside one \\boxed{...} and that state's average "
        "transaction amount (rounded to two decimal places) inside another "
        "\\boxed{...}. The two boxes may appear anywhere in the memo.\n\n"
        f"Transactions: {transactions.to_json(orient='records')}"
    )
    state, avg_amount = get_state_largest_mean_transaction(transactions)
    return {"task": "memo", "question": question,
            "ground_truth": {"state": state, "average_amount": avg_amount}}


def build_batch(step: int, per_task: int) -> list[dict]:
    examples: list[dict] = []
    merge_rows = fin_tr_transactions.iloc[step * per_task : (step + 1) * per_task]
    for _, tx in merge_rows.iterrows():
        examples.append(build_merge_example(tx))

    rng = random.Random(step)
    user_ids = list(fin_tr_users["id"])
    for _ in range(per_task):
        examples.append(build_policy_example(rng.sample(user_ids, k=10)))

    n_tx = len(fin_tr_transactions)
    for _ in range(per_task):
        idxs = rng.sample(range(n_tx), k=25)
        examples.append(build_memo_example(fin_tr_transactions.iloc[idxs]))

    return examples
