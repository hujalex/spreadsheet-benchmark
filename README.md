# Spreadsheet Agent Benchmark

Three evaluation tasks for assessing spreadsheet agent capabilities.

---

## Task 1: Record Reconciliation

**Objective:** Left-join a transaction with its matching card row and return the merged result.

**Description:**
Given a transaction record and a set of card records, perform a left-join matching on `transaction.card_id == cards.id`. Return only the merged row as a single JSON object with no other text.

### Inputs
- Subset of transactions from `transactions_data.csv`
- Complete `cards_data.csv`

### Output Format
- Merged row as a single JSON object

### Grading Criteria
- **Full Credit (+1):** The agent output matches the result of the programmatic operation (Python Pandas left-join)
- **No Credit (+0):** Output does not match or is malformed

---

## Task 2: Computation Under Written Policy

**Objective:** Identify accounts exceeding credit limits under a tiered policy.

**Description:**
Given customer income profiles and assigned credit limits, identify all accounts where the assigned credit limit exceeds the allowed threshold based on the following policy:

```
Credit Limit By Tiers Policy:
- Yearly income < $40,000        → $5,000 limit
- $40,000 ≤ yearly income ≤ $100,000  → $15,000 limit
- Yearly income > $100,000 AND credit_score ≥ 600  → $50,000 limit
- Yearly income > $100,000 AND credit_score < 600  → $15,000 limit (fallback)
```

### Inputs
- Subset of user IDs from `users_data.csv`
- Associated card records from `cards_data.csv`

### Output Format
Format: `\boxed{(Customer ID, Current Limit), ...}`

### Grading Criteria
- **Per Account (+/- points):**
  - Correctly identified account: **+1** point
  - Incorrectly identified account: **-1** point
  - Missed account (not identified): **+0** points
- **Total Score:** Sum of all account-level scores

---

## Task 3: Memo – State Analysis

**Objective:** Analyze transaction data and identify the state with the largest average transaction amount.

**Description:**
For a given batch of transactions, write a memo that:
1. Identifies the merchant state with the largest average transaction amount
2. Includes the state name in a `\boxed{...}` block
3. Includes the state's average transaction amount (rounded to 2 decimal places) in another `\boxed{...}` block

The memo can be written in any style; the grader will extract the boxed values from anywhere in the text.

### Inputs
- Batch of transactions from `transactions_data.csv`

### Output Format
- A prose memo with the state wrapped in `\boxed{STATE}` and the average amount in `\boxed{AMOUNT}`

### Grading Criteria
- **Full Credit (+1.0):** Both the state and average amount are correctly identified and found in `\boxed{}` blocks
- **Partial Credit (+0.5):** Either the state or the average amount is correct (one out of two)
- **No Credit (+0.0):** Neither value is correct, or boxes are missing/malformed

---

## Scoring

Each task is evaluated independently:
- **Task 1:** Binary (0 or 1)
- **Task 2:** Per-account scoring (sum of +1/+0/-1)
- **Task 3:** 0, 0.5, or 1.0

The final benchmark score is the average performance across all three tasks.
