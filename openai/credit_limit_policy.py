import re


import re

import numpy as np
import pandas as pd


def allowed_credit_limit(yearly_income: pd.Series, credit_score: pd.Series) -> pd.Series:
    """Vectorized policy:
        income < 40k                                    -> 5,000
        40k <= income <= 100k                           -> 15,000
        income > 100k and credit_score >= 600           -> 50,000
        income > 100k and credit_score <  600           -> 15,000 (falls back one tier)
    """
    income = pd.to_numeric(yearly_income, errors="coerce")
    score = pd.to_numeric(credit_score, errors="coerce")

    limit = pd.Series(np.nan, index=income.index, dtype="float64")
    limit = limit.mask(income < 40_000, 5_000)
    limit = limit.mask((income >= 40_000) & (income <= 100_000), 15_000)
    limit = limit.mask((income > 100_000) & (score >= 600), 50_000)
    limit = limit.mask((income > 100_000) & (score < 600), 15_000)
    return limit


def _money_to_int(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(r"[\$,]", "", regex=True),
        errors="coerce",
    )


def find_overextended_accounts(users: pd.DataFrame, cards: pd.DataFrame) -> str:
    """Identify accounts whose assigned credit_limit exceeds what the policy allows,
    and return them as `\\boxed{(Customer ID, Current Limit), ...}`.
    """
    u = users[["id", "yearly_income", "credit_score"]].copy()
    u["yearly_income"] = _money_to_int(u["yearly_income"])

    c = cards[["client_id", "credit_limit"]].copy()
    c["credit_limit"] = _money_to_int(c["credit_limit"])

    df = c.merge(u, how="left", left_on="client_id", right_on="id")
    df["allowed"] = allowed_credit_limit(df["yearly_income"], df["credit_score"])

    over = df[df["credit_limit"] > df["allowed"]].sort_values(
        ["client_id", "credit_limit"]
    )
    pairs = ",".join(
        f"({int(cid)}, ${int(lim):,})"
        for cid, lim in zip(over["client_id"], over["credit_limit"])
    )
    return rf"\boxed{{{pairs},}}"


if __name__ == "__main__":
    users = pd.read_csv("data/users_data.csv")
    cards = pd.read_csv("data/cards_data.csv")
    print(find_overextended_accounts(users, cards))
