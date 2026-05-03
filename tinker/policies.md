Transaction Approval by Amount
"Auto-approve transactions under $500; flag for review between $500–$5,000; auto-decline above $5,000 unless use_chip = 'Chip Transaction'."

Credit Limit Tiers by Income
"Assign $5,000 limit for yearly_income under $40,000; $15,000 limit between $40,000–$100,000; $50,000 limit above $100,000 unless credit_score is below 600."

Card Reissue Triggers
"No reissue if card_on_dark_web = No; mandatory reissue if card_on_dark_web = Yes; expedited reissue if card_on_dark_web = Yes AND year_pin_last_changed is more than 5 years ago."

Fraud Risk Scoring
"Low risk if errors is null AND amount under $200; medium risk if errors is null AND amount between $200–$2,000; high risk if errors is not null OR amount exceeds $2,000."

Account Standing by Debt-to-Income
"Good standing if total_debt is under 30% of yearly_income; watch status between 30–60%; restricted status above 60% unless credit_score is above 750."

Merchant Category Restrictions
"Allow all transactions for mcc in retail/grocery codes; require chip verification for mcc in travel/entertainment codes; block entirely for mcc in high-risk codes unless use_chip = 'Chip Transaction'."

Customer Segmentation
"Standard tier if credit_score under 670; Preferred tier between 670–740; Premium tier above 740 unless num_credit_cards is greater than 5."

Transaction Velocity Limits
"Allow unlimited transactions under $50; cap at 10 per day between $50–$500; cap at 3 per day above $500 unless prior transaction same day had errors = null."

Retirement Readiness Flag
"Mark 'On Track' if current_age is more than 10 years from retirement_age; mark 'Review Needed' between 5–10 years; mark 'Urgent Planning' if within 5 years AND total_debt exceeds yearly_income."

PIN Change Enforcement
"No action if year_pin_last_changed is within 2 years; send reminder between 2–5 years; force change after 5 years unless has_chip = True AND card_on_dark_web = No."

Here are the revised prompts for each category, updated to request list formats instead of tables and incorporating your specific formatting requirements where applicable.

---
### Transaction Approval
Prompt: "I have attached a transaction log and our Transaction Approval Policy. Please identify every transaction that was 'Approved' but actually should have been 'Declined' according to the rule: 'Auto-decline above $5,000 unless use_chip = Chip Transaction.' Provide a list of these 'False Approvals' including the Transaction ID and the actual dollar amount we over-authorized in this format \boxed{(transaction ID, dollar amount),}"

### Credit Limit Tiers by Income
**Prompt:** "I have provided a dataset of customer income profiles. Please identify any accounts where the assigned credit limit exceeds the allowed threshold based on the rule: **'Assign $5,000 limit for yearly_income under $40,000; $15,000 limit between $40,000–$100,000; $50,000 limit above $100,000 unless credit_score is below 600.'** Provide a list of these over-extended accounts including the Customer ID and the current limit in the following format: $\boxed{(Customer ID, Current Limit),}$"

### Card Reissue Triggers
**Prompt:** "Analyze the attached security audit and identify all customers who require a 'Mandatory' or 'Expedited' reissue based on these triggers: **'No reissue if card_on_dark_web = No; mandatory reissue if card_on_dark_web = Yes; expedited reissue if card_on_dark_web = Yes AND year_pin_last_changed is more than 5 years ago.'** Generate a list of these customers, clearly marking which are 'Expedited.' Use the format: $\boxed{(Customer ID, Reissue Type),}$"

### Fraud Risk Scoring
**Prompt:** "Review the recent transaction batch and categorize each entry based on the rule: **'Low risk if errors is null AND amount under $200; medium risk if errors is null AND amount between $200–$2,000; high risk if errors is not null OR amount exceeds $2,000.'** Provide a list of all 'High Risk' transactions that require manual investigator sign-off in this format: $\boxed{(Transaction ID, Risk Level),}$"

### Account Standing by Debt-to-Income
**Prompt:** "Examine the attached portfolio and flag any accounts that should be moved to 'Restricted' status based on the rule: **'Good standing if total_debt is under 30% of yearly_income; watch status between 30–60%; restricted status above 60% unless credit_score is above 750.'** Provide a list of accounts that are currently marked 'Good' but should be 'Restricted' or 'Watch' in the format: $\boxed{(Customer ID, Suggested Status),}$"

### Merchant Category Restrictions
**Prompt:** "I have attached a list of today's blocked and allowed transactions. Please identify any 'Blocked' transactions that should have been allowed under this exception: **'Block entirely for mcc in high-risk codes unless use_chip = Chip Transaction.'** Provide a list of these incorrect blocks including the Merchant Category Code (MCC) and Transaction ID in this format: $\boxed{(Transaction ID, MCC),}$"

### Customer Segmentation
**Prompt:** "Using the provided CRM data, audit our 'Premium' tier members against this standard: **'Premium tier above 740 unless num_credit_cards is greater than 5.'** Provide a list of users currently in the Premium tier who should be downgraded to 'Preferred' or 'Standard' in the format: $\boxed{(User ID, New Suggested Tier),}$"

### Transaction Velocity Limits
**Prompt:** "Review the daily activity logs and flag any users who exceeded their velocity caps according to the logic: **'Allow unlimited transactions under $50; cap at 10 per day between $50–$500; cap at 3 per day above $500 unless prior transaction same day had errors = null.'** Provide a list of User IDs that bypassed these caps and the count of excess transactions in this format: $\boxed{(User ID, Excess Count),}$"

### Retirement Readiness Flag
**Prompt:** "Analyze the attached employee financial profiles and identify those requiring 'Urgent Planning' based on the rule: **'Mark On Track if current_age is more than 10 years from retirement_age; mark Review Needed between 5–10 years; mark Urgent Planning if within 5 years AND total_debt exceeds yearly_income.'** Provide a list of employees in the 'Urgent' category for HR outreach in the format: $\boxed{(Employee ID, Current Age),}$"

### PIN Change Enforcement
**Prompt:** "Audit our security compliance logs to find users who must be 'Force Changed' based on this policy: **'Send reminder between 2–5 years; force change after 5 years unless has_chip = True AND card_on_dark_web = No.'** Provide a list of all accounts that require a forced change in the format: $\boxed{(Account ID, Year PIN Last Changed),}$"