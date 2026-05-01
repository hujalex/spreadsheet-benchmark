import os
import re
import json
import random
import warnings
import asyncio
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datasets import load_dataset
from google import genai
from google.genai import types
from dotenv import load_dotenv
import phoenix as px
from phoenix.otel import register
from opentelemetry import trace
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

from credit_limit_policy import find_overextended_accounts, grade_overextended, _parse_pairs
from grader import Grader

METRICS_DIR = "metrics"

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
MODEL_NAME = "gemini-2.5-flash"
PHOENIX_PROJECT_NAME = os.getenv("PHOENIX_PROJECT_NAME", "spreadsheet-agent-benchmark-gemini")
PHOENIX_ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")


def _normalize_phoenix_endpoint(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/v1/traces"):
        return endpoint
    return f"{endpoint}/v1/traces"


def setup_phoenix_tracing():
    endpoint = _normalize_phoenix_endpoint(PHOENIX_ENDPOINT)
    session = None
    launch_requested = os.getenv("PHOENIX_LAUNCH_APP", "1") != "0"
    local_endpoint = "localhost" in endpoint or "127.0.0.1" in endpoint
    if launch_requested and local_endpoint:
        session = px.launch_app()
        print(f"Phoenix UI: {session.url}")

    register(
        project_name=PHOENIX_PROJECT_NAME,
        endpoint=endpoint,
        protocol="http/protobuf",
        auto_instrument=False,
        batch=True,
        api_key=os.getenv("PHOENIX_API_KEY") or os.getenv("ARIZE_PHOENIX_API_KEY"),
    )
    print(f"Phoenix tracing: project={PHOENIX_PROJECT_NAME}, endpoint={endpoint}")
    return session

class Model:
    # ds = load_dataset("xw27/scibench")
    fin_tr_cards = pd.read_csv("data/cards_data.csv")
    fin_tr_transactions = pd.read_csv("data/transactions_data.csv")
    fin_tr_users = pd.read_csv("data/users_data.csv")
    
    def __init__(self, model, log_dir: str = "logs/gemini_run"):
        self.base_model = model
        if not GEMINI_API_KEY:
            raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY before running main_gemini.py")
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.generation_config = types.GenerateContentConfig(
            max_output_tokens=8192,
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        self.training_data = Model.fin_tr_transactions
        self.tracer = trace.get_tracer(__name__)
        # Model.merge_cards_transactions(Model.fin_tr_cards, Model.fin_tr_transactions)

    @staticmethod
    def merge_cards_transactions(cards: pd.DataFrame, transactions: pd.DataFrame) -> pd.DataFrame:
        return transactions.merge(cards, how='left', left_on='card_id', right_on='id', suffixes = ('_tx', '_card'))

    @staticmethod
    def merge_clients_transactions(clients: pd.DataFrame, transactions: pd.DataFrame) -> pd.DataFrame:
        return transactions.merge(clients, how='left', left_on='client_id', right_on='id', suffixes = ('_tx', '_card'))

    @staticmethod
    def merge_merchants_transactions(merchants: pd.DataFrame, transactions: pd.DataFrame) -> pd.DataFrame:
        return transactions.merge(merchants, how='left', left_on='client_id', right_on='id', suffixes = ('_tx', '_card'))

    @staticmethod
    def get_state_largest_mean_transaction(transactions: pd.DataFrame):
        transactions = transactions.copy()
        transactions['amount'] = transactions['amount'].astype(str).str.replace(r'[^\d.-]', '', regex=True)
        transactions['amount'] = pd.to_numeric(transactions['amount'])
        state_means = transactions.dropna(subset=['merchant_state']).groupby('merchant_state')['amount'].mean().nlargest(1)
        return state_means.index[0], f"{float(state_means.iloc[0]):.2f}"

    @staticmethod
    def _set_span_kind(span, kind: OpenInferenceSpanKindValues) -> None:
        span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, kind.value)

    async def train(self, n_steps=1, batch_size=3, group_size=1):
        metrics_history = []
        instance_metrics: list[dict] = []
        failures: list[dict] = []
        per_task = batch_size // 3
        for step in range(n_steps):
            with self.tracer.start_as_current_span(f"step_{step}") as step_span:
                self._set_span_kind(step_span, OpenInferenceSpanKindValues.CHAIN)
                step_span.set_attribute("step", step)
                step_span.set_attribute("batch_size", batch_size)
                step_span.set_attribute("group_size", group_size)
                self.save_state()

                with self.tracer.start_as_current_span("build_batch") as batch_span:
                    self._set_span_kind(batch_span, OpenInferenceSpanKindValues.TOOL)
                    batch_span.set_attribute("step", step)
                    batch_span.set_attribute("per_task", per_task)
                    examples = self._build_batch(step, per_task)
                    batch_span.set_attribute("output.value", json.dumps({
                        "n_examples": len(examples),
                        "tasks": [ex["task"] for ex in examples],
                    }))

                rewards: list[float] = []
                rewards_by_task: dict[str, list[float]] = {"merge": [], "policy": [], "memo": []}
                n_degenerate = 0

                for i, ex in enumerate(examples):
                    with self.tracer.start_as_current_span("example") as span:
                        self._set_span_kind(span, OpenInferenceSpanKindValues.CHAIN)
                        span.set_attribute("step", step)
                        span.set_attribute("example_index", i)
                        span.set_attribute("task", ex["task"])
                        span.set_attribute("input.value", ex["question"])

                        sample_result = await self.sample_async(
                            ex["prompt"],
                            group_size,
                            step=step,
                            example_index=i,
                            task=ex["task"],
                        )

                        contents_group, rewards_group = [], []
                        for sample_idx, sample in enumerate(sample_result):
                            content = sample["text"]
                            if ex.get("prefill"):
                                content = self._apply_prefill(content, ex["prefill"])
                            contents_group.append(content)
                            if ex['task'] == 'policy':
                                print(content)
                            with self.tracer.start_as_current_span("grade_response") as grade_span:
                                self._set_span_kind(grade_span, OpenInferenceSpanKindValues.EVALUATOR)
                                grade_span.set_attribute("step", step)
                                grade_span.set_attribute("example_index", i)
                                grade_span.set_attribute("sample_index", sample_idx)
                                grade_span.set_attribute("task", ex["task"])
                                grade_span.set_attribute("input.value", content)
                                reward = Grader._grade(
                                    content,
                                    ex,
                                    n_tokens=self._estimate_token_count(content),
                                )
                                grade_span.set_attribute("reward", reward)
                                grade_span.set_attribute("output.value", str(reward))
                            rewards_group.append(reward)
                            if reward < 1.0:
                                annotation = self._annotate_failure(ex, content)
                                failures.append({
                                    "step": step,
                                    "example_index": i,
                                    "sample_index": sample_idx,
                                    "task": ex["task"],
                                    "reward": reward,
                                    "response": content,
                                    "ground_truth": ex["ground_truth"],
                                    "annotation": annotation,
                                    "finish_reason": sample["finish_reason"],
                                    "finish_message": sample["finish_message"],
                                    "output_tokens": sample["output_tokens"],
                                })

                        mean_reward = sum(rewards_group) / len(rewards_group)
                        advantages_group = [r - mean_reward for r in rewards_group]
                        rewards.append(mean_reward)
                        rewards_by_task[ex["task"]].append(mean_reward)
                        is_degenerate = all(a == 0.0 for a in advantages_group)
                        n_failures = sum(1 for r in rewards_group if r == 0.0)
                        instance_metrics.append({
                            "step": step,
                            "example_index": i,
                            "task": ex["task"],
                            "group_size": len(rewards_group),
                            "failures": n_failures,
                            "mean_reward": mean_reward,
                            "degenerate": is_degenerate,
                        })

                        for j, (content, r) in enumerate(zip(contents_group, rewards_group)):

                            span.set_attribute(f"output.{j}.value", content)
                            span.set_attribute(f"output.{j}.reward", r)
                        span.set_attribute("reward.mean", mean_reward)
                        span.set_attribute("reward.values", rewards_group)
                        span.set_attribute("degenerate", is_degenerate)

                        if is_degenerate:
                            n_degenerate += 1
                            continue

                merge_mean = sum(rewards_by_task["merge"]) / max(len(rewards_by_task["merge"]), 1)
                policy_mean = sum(rewards_by_task["policy"]) / max(len(rewards_by_task["policy"]), 1)
                memo_mean = sum(rewards_by_task["memo"]) / max(len(rewards_by_task["memo"]), 1)
                step_span.set_attribute("reward.mean", sum(rewards) / len(rewards))
                step_span.set_attribute("reward.merge_mean", merge_mean)
                step_span.set_attribute("reward.policy_mean", policy_mean)
                step_span.set_attribute("reward.memo_mean", memo_mean)
                step_span.set_attribute("frac_degenerate", n_degenerate / len(rewards))

            mean_reward = sum(rewards) / len(rewards)
            frac_degenerate = n_degenerate / len(rewards)
            metrics_history.append(
                {"step": step, "reward": mean_reward, "merge": merge_mean,
                 "policy": policy_mean, "memo": memo_mean,
                 "frac_degenerate": frac_degenerate}
            )
            print(
                f"Step {step:2d} | reward: {mean_reward:.3f} "
                f"(merge {merge_mean:.3f}, policy {policy_mean:.3f}, memo {memo_mean:.3f}) | "
                f"degenerate: {frac_degenerate:.0%}"
            )

        self._write_metrics(metrics_history, instance_metrics)
        self._write_failures_markdown(failures)

    def _write_metrics(self, metrics_history: list[dict], instance_metrics: list[dict]) -> None:
        """Persist per-step and per-instance metrics as CSVs plus a PNG figure."""
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
        ax_inst.set_ylabel(f"failures per instance (out of group_size)")
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

    def _annotate_failure(self, ex: dict, response: str) -> str:
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

    def _write_failures_markdown(self, failures: list[dict]) -> None:
        os.makedirs(METRICS_DIR, exist_ok=True)
        md_path = os.path.join(METRICS_DIR, "rubric_gemini.md")
        by_task: dict[str, list[dict]] = {}
        for f in failures:
            by_task.setdefault(f["task"], []).append(f)

        lines: list[str] = ["# Training Failures", ""]
        lines.append(f"Recorded **{len(failures)}** sample(s) with reward < 1.0.")
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
                if f.get("finish_reason") or f.get("output_tokens") is not None:
                    lines.append("")
                    lines.append(
                        f"**Generation:** finish_reason={f.get('finish_reason')}, "
                        f"output_tokens={f.get('output_tokens')}"
                    )
                    if f.get("finish_message"):
                        lines.append(f"finish_message={f['finish_message']}")
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

        with open(md_path, "w") as fp:
            fp.write("\n".join(lines))
        print(f"Wrote {md_path}")

    def save_state(self):
        pass

    async def sample_async(
        self,
        prompt: str,
        num_samples: int,
        *,
        step: int | None = None,
        example_index: int | None = None,
        task: str | None = None,
    ) -> list[dict]:
        return await asyncio.gather(
            *[
                asyncio.to_thread(
                    self._generate_with_metadata,
                    prompt,
                    sample_index=sample_index,
                    step=step,
                    example_index=example_index,
                    task=task,
                )
                for sample_index in range(num_samples)
            ]
        )

    def _generate_content(self, prompt: str) -> str:
        return self._generate_with_metadata(prompt)["text"]

    def _generate_with_metadata(
        self,
        prompt: str,
        *,
        sample_index: int | None = None,
        step: int | None = None,
        example_index: int | None = None,
        task: str | None = None,
    ) -> dict:
        with self.tracer.start_as_current_span("gemini.generate_content") as span:
            self._set_span_kind(span, OpenInferenceSpanKindValues.LLM)
            span.set_attribute("llm.provider", "google")
            span.set_attribute("llm.model_name", self.base_model)
            span.set_attribute("input.value", prompt)
            if step is not None:
                span.set_attribute("step", step)
            if example_index is not None:
                span.set_attribute("example_index", example_index)
            if sample_index is not None:
                span.set_attribute("sample_index", sample_index)
            if task:
                span.set_attribute("task", task)
            span.set_attribute(
                "llm.invocation_parameters",
                json.dumps({
                    "max_output_tokens": 8192,
                    "temperature": 0.2,
                    "thinking_budget": 0,
                }),
            )
            try:
                response = self.client.models.generate_content(
                    model=self.base_model,
                    contents=prompt,
                    config=self.generation_config,
                )
            except Exception as exc:
                span.record_exception(exc)
                span.set_attribute("error", True)
                raise

            candidate = response.candidates[0] if response.candidates else None
            usage = response.usage_metadata
            text = response.text or ""
            finish_reason = str(candidate.finish_reason) if candidate and candidate.finish_reason else None
            output_tokens = usage.candidates_token_count if usage else None

            span.set_attribute("output.value", text)
            if finish_reason:
                span.set_attribute("llm.finish_reason", finish_reason)
            if candidate and candidate.finish_message:
                span.set_attribute("llm.finish_message", candidate.finish_message)
            if usage:
                if usage.prompt_token_count is not None:
                    span.set_attribute("llm.token_count.prompt", usage.prompt_token_count)
                if usage.candidates_token_count is not None:
                    span.set_attribute("llm.token_count.completion", usage.candidates_token_count)
                if usage.total_token_count is not None:
                    span.set_attribute("llm.token_count.total", usage.total_token_count)

            return {
                "text": text,
                "finish_reason": finish_reason,
                "finish_message": candidate.finish_message if candidate else None,
                "output_tokens": output_tokens,
            }

    @staticmethod
    def _apply_prefill(content: str, prefill: str) -> str:
        content = content.lstrip()
        return content if content.startswith(prefill) else prefill + content

    @staticmethod
    def _estimate_token_count(content: str) -> int:
        return max(1, len(content.split()))

    def _build_batch(self, step: int, per_task: int) -> list[dict]:
        """Build a 3-way mixed batch: `per_task` merge + `per_task` policy + `per_task` memo."""
        examples: list[dict] = []

        merge_rows = self.training_data.iloc[step * per_task : (step + 1) * per_task]
        for _, transaction in merge_rows.iterrows():
            examples.append(self._build_merge_example(transaction))

        # * policy task randomly sampled input
        rng = random.Random(step)
        user_ids = list(Model.fin_tr_users["id"])
        chunk_size = 10
        for _ in range(per_task):
            sampled_ids = rng.sample(user_ids, k=chunk_size)
            examples.append(self._build_policy_example(sampled_ids))

        # * memo task randomly sampled input
        memo_chunk_size = 25
        n_tx = len(self.training_data)
        for _ in range(per_task):
            idxs = rng.sample(range(n_tx), k=memo_chunk_size)
            tx_chunk = self.training_data.iloc[idxs]
            examples.append(self._build_memo_example(tx_chunk))

        return examples

    def _build_merge_example(self, transaction: pd.Series) -> dict:
        cards = Model.fin_tr_cards
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
        prompt = question

        gt_row = Model.merge_cards_transactions(
            cards, pd.DataFrame([transaction])
        ).iloc[0].to_dict()
        ground_truth = {k: (None if pd.isna(v) else v) for k, v in gt_row.items()}

        return {"task": "merge", "prompt": prompt, "question": question,
                "ground_truth": ground_truth, "prefill": "{"}

    def _build_policy_example(self, user_ids: list[int]) -> dict:
        users_chunk = Model.fin_tr_users[Model.fin_tr_users["id"].isin(user_ids)].reset_index(drop=True)
        cards_chunk = Model.fin_tr_cards[Model.fin_tr_cards["client_id"].isin(user_ids)].reset_index(drop=True)
        
        credit_limit_by_tiers = '''
        Assign $5,000 limit for yearly_income under $40,000;
        $15,000 limit between $40,000-$100,000; $50,000 limit above $100,000 unless
        credit_score is below 600.
        '''

        question = ( "### TASK: IDENTIFY OVER-EXTENDED ACCOUNTS\n"
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
        prompt = question
        
        # * ground truth
        ground_truth = find_overextended_accounts(users_chunk, cards_chunk)

        return {"task": "policy", "prompt": prompt, "question": question,
                "ground_truth": ground_truth}
        
    def _build_memo_example(self, transactions: pd.DataFrame) -> dict:
        transactions = transactions.reset_index(drop=True)

        question = (
            "Below is a batch of transactions. Write a short memo (<20 words) identifying the "
            "merchant_state with the largest average transaction amount. Include "
            "the identified state inside one \\boxed{...} and that state's average "
            "transaction amount (rounded to two decimal places) inside another "
            "\\boxed{...}. The two boxes may appear anywhere in the memo.\n\n"
            f"Transactions: {transactions.to_json(orient='records')}"
        )
        prompt = question

        # * ground truth
        state, avg_amount = Model.get_state_largest_mean_transaction(transactions)
        ground_truth = {"state": state, "average_amount": avg_amount}

        return {"task": "memo", "prompt": prompt, "question": question,
                "ground_truth": ground_truth}

    def prompt(self, question):
        print(self._generate_content(question))


if __name__ == "__main__":
    session = setup_phoenix_tracing()
    model = Model(MODEL_NAME)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("gemini_agent_run") as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.AGENT.value,
        )
        span.set_attribute("agent.name", "spreadsheet-agent-benchmark-gemini")
        span.set_attribute("llm.model_name", MODEL_NAME)
        asyncio.run(model.train())
    # model.prompt("A 10 kg body moving at sticks to a 15 kg body at rest. What is the final velocity?")
    input("Training complete. Press Enter to shut down Phoenix and exit...")
    
