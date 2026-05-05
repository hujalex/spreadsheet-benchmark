import os
import json
import asyncio
import tinker
import torch
from tinker import TensorData
import grader
from tinker_cookbook.renderers import get_renderer, get_text_content
from tinker_cookbook.utils.ml_log import setup_logging
from dotenv import load_dotenv
from opentelemetry import trace
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

from tracing import setup_phoenix_tracing, set_span_kind, span
from batch import build_batch, load_finance_tables
from failures import FailureRecorder
from metrics import MetricsWriter, METRICS_DIR


load_dotenv()
TINKER_API_KEY = os.getenv("TINKER_API_KEY")
MODEL_NAME = 'Qwen/Qwen3.6-35B-A3B'
RENDERER = 'qwen3_disable_thinking'


class Model:
    def __init__(self, model, renderer, log_dir: str = "logs/run"):
        self.base_model = model
        self.service_client = tinker.ServiceClient()
        self.training_client = self.service_client.create_lora_training_client(
            base_model=model, rank=32
        )
        self.tokenizer = self.training_client.get_tokenizer()
        self.renderer = get_renderer(renderer, self.tokenizer)
        self.sampling_params = tinker.SamplingParams(
            max_tokens=2048,
            stop=self.renderer.get_stop_sequences(),
        )
        self.adam_params = tinker.AdamParams(learning_rate=4e-5, beta1=0.9, beta2=0.95)
        self.tables = load_finance_tables()
        self.tracer = trace.get_tracer(__name__)
        self.ml_logger = setup_logging(log_dir=log_dir)

    async def train(self, n_steps=10, batch_size=15, group_size=8):
        metrics = MetricsWriter()
        failures = FailureRecorder()
        per_task = batch_size // 3

        for step in range(n_steps):
            with span(self.tracer, f"step_{step}", OpenInferenceSpanKindValues.CHAIN,
                      step=step, batch_size=batch_size, group_size=group_size) as step_span:
                self.save_state()

                with span(self.tracer, "build_batch", OpenInferenceSpanKindValues.TOOL,
                          step=step, per_task=per_task) as batch_span:
                    examples = build_batch(step, per_task, tables=self.tables, renderer=self.renderer)
                    batch_span.set_attribute("output.value", json.dumps({
                        "n_examples": len(examples),
                        "tasks": [ex["task"] for ex in examples],
                    }))

                sample_results = await asyncio.gather(*[
                    self.sample_example_async(ex, group_size=group_size, step=step, example_index=i)
                    for i, ex in enumerate(examples)
                ])

                datums, rewards, rewards_by_task, n_degenerate, n_skipped_empty = self._grade_and_pack(
                    step, examples, sample_results, failures, metrics,
                )

                self.update(datums)

                merge_mean = _safe_mean(rewards_by_task["merge"])
                policy_mean = _safe_mean(rewards_by_task["policy"])
                memo_mean = _safe_mean(rewards_by_task["memo"])
                step_mean = sum(rewards) / len(rewards)
                frac_degenerate = n_degenerate / len(rewards)

                step_span.set_attribute("reward.mean", step_mean)
                step_span.set_attribute("reward.merge_mean", merge_mean)
                step_span.set_attribute("reward.policy_mean", policy_mean)
                step_span.set_attribute("reward.memo_mean", memo_mean)
                step_span.set_attribute("frac_degenerate", frac_degenerate)
                step_span.set_attribute("n_datums", len(datums))
                step_span.set_attribute("n_skipped_empty", n_skipped_empty)

            metrics.record_step({
                "step": step, "reward": step_mean, "merge": merge_mean,
                "policy": policy_mean, "memo": memo_mean,
                "frac_degenerate": frac_degenerate,
            })
            print(
                f"Step {step:2d} | reward: {step_mean:.3f} "
                f"(merge {merge_mean:.3f}, policy {policy_mean:.3f}, memo {memo_mean:.3f}) | "
                f"degenerate: {frac_degenerate:.0%} | datums: {len(datums)} | "
                f"skipped empty: {n_skipped_empty}"
            )

        metrics.write(METRICS_DIR)
        failures.write_markdown(os.path.join(METRICS_DIR, "training_failures_latest.md"))

    def _grade_and_pack(self, step, examples, sample_results, failures, metrics):
        datums: list[tinker.Datum] = []
        rewards: list[float] = []
        rewards_by_task: dict[str, list[float]] = {"merge": [], "policy": [], "memo": []}
        n_degenerate = 0
        n_skipped_empty = 0

        for i, (ex, sample_result) in enumerate(zip(examples, sample_results)):
            with span(self.tracer, "example", OpenInferenceSpanKindValues.CHAIN,
                      step=step, example_index=i, task=ex["task"]) as ex_span:
                ex_span.set_attribute("input.value", ex["question"])

                contents_group, rewards_group = [], []
                tokens_group, logprobs_group = [], []

                for sample_idx, sequence in enumerate(sample_result.sequences):
                    tokens_group.append(sequence.tokens)
                    logprobs_group.append(sequence.logprobs)
                    parsed_message, _ = self.renderer.parse_response(sequence.tokens)
                    content = get_text_content(parsed_message)
                    if ex.get("prefill"):
                        content = ex["prefill"] + content
                    contents_group.append(content)
                    if ex["task"] == "policy":
                        print(content)

                    with span(self.tracer, "grade_response", OpenInferenceSpanKindValues.EVALUATOR,
                              step=step, example_index=i, sample_index=sample_idx,
                              task=ex["task"]) as grade_span:
                        grade_span.set_attribute("input.value", content)
                        reward = grader._grade(content, ex, n_tokens=len(sequence.tokens))
                        grade_span.set_attribute("reward", reward)
                        grade_span.set_attribute("output.value", str(reward))

                    rewards_group.append(reward)
                    if reward < 1.0:
                        failures.record(step=step, example_index=i, sample_index=sample_idx,
                                        ex=ex, reward=reward, response=content)

                mean_reward = sum(rewards_group) / len(rewards_group)
                advantages_group = [r - mean_reward for r in rewards_group]
                rewards.append(mean_reward)
                rewards_by_task[ex["task"]].append(mean_reward)
                is_degenerate = all(a == 0.0 for a in advantages_group)
                n_failures = sum(1 for r in rewards_group if r == 0.0)

                metrics.record_instance({
                    "step": step,
                    "example_index": i,
                    "task": ex["task"],
                    "group_size": len(rewards_group),
                    "failures": n_failures,
                    "mean_reward": mean_reward,
                    "degenerate": is_degenerate,
                })

                for j, (content, r) in enumerate(zip(contents_group, rewards_group)):
                    ex_span.set_attribute(f"output.{j}.value", content)
                    ex_span.set_attribute(f"output.{j}.reward", r)
                ex_span.set_attribute("reward.mean", mean_reward)
                ex_span.set_attribute("reward.values", rewards_group)
                ex_span.set_attribute("degenerate", is_degenerate)

                if is_degenerate:
                    n_degenerate += 1
                    continue

                ob_len = ex["prompt"].length - 1
                for tokens, logprobs, advantage in zip(tokens_group, logprobs_group, advantages_group):
                    if len(tokens) <= 1:
                        n_skipped_empty += 1
                        continue
                    model_input = ex["prompt"].append(tinker.EncodedTextChunk(tokens=tokens[:-1]))
                    datums.append(self.build_datum(model_input, tokens, logprobs, advantage, ob_len))

        return datums, rewards, rewards_by_task, n_degenerate, n_skipped_empty

    def save_state(self):
        with span(self.tracer, "save_weights", OpenInferenceSpanKindValues.TOOL) as s:
            s.set_attribute("llm.model_name", self.base_model)
            self.sampling_client = self.training_client.save_weights_and_get_sampling_client()

    async def sample_example_async(self, ex: dict, *, group_size: int, step: int, example_index: int):
        with span(self.tracer, "tinker.sample", OpenInferenceSpanKindValues.LLM,
                  step=step, example_index=example_index, task=ex["task"]) as s:
            s.set_attribute("llm.provider", "tinker")
            s.set_attribute("llm.model_name", self.base_model)
            s.set_attribute("input.value", ex["question"])
            s.set_attribute(
                "llm.invocation_parameters",
                json.dumps({
                    "max_tokens": self.sampling_params.max_tokens,
                    "num_samples": group_size,
                    "renderer": RENDERER,
                }),
            )
            try:
                result = await self.sampling_client.sample_async(
                    prompt=ex["prompt"],
                    num_samples=group_size,
                    sampling_params=self.sampling_params,
                )
            except Exception as exc:
                s.record_exception(exc)
                s.set_attribute("error", True)
                raise

            s.set_attribute("llm.num_completions", len(result.sequences))
            for sample_idx, sequence in enumerate(result.sequences):
                parsed_message, _ = self.renderer.parse_response(sequence.tokens)
                content = get_text_content(parsed_message)
                if ex.get("prefill"):
                    content = ex["prefill"] + content
                s.set_attribute(f"output.{sample_idx}.value", content)
                s.set_attribute(f"output.{sample_idx}.token_count", len(sequence.tokens))
            return result

    def build_datum(self, model_input, tokens, logprobs, advantage, ob_len):
        target_tokens = [0] * ob_len + list(tokens)
        padded_logprobs = [0.0] * ob_len + list(logprobs)
        padded_advantages = [0.0] * ob_len + [advantage] * (model_input.length - ob_len)
        return tinker.Datum(
            model_input=model_input,
            loss_fn_inputs={
                "target_tokens": TensorData.from_torch(torch.tensor(target_tokens)),
                "logprobs": TensorData.from_torch(torch.tensor(padded_logprobs)),
                "advantages": TensorData.from_torch(torch.tensor(padded_advantages)),
            },
        )

    def update(self, datums):
        if not datums:
            return
        with span(self.tracer, "tinker.update", OpenInferenceSpanKindValues.TOOL,
                  n_datums=len(datums)) as s:
            s.set_attribute("loss_fn", "importance_sampling")
            s.set_attribute("optimizer", "adam")
            s.set_attribute("learning_rate", self.adam_params.learning_rate)
            try:
                fwd_bwd_future = self.training_client.forward_backward(datums, loss_fn="importance_sampling")
                optim_future = self.training_client.optim_step(self.adam_params)
                fwd_bwd_future.result()
                optim_future.result()
            except Exception as exc:
                s.record_exception(exc)
                s.set_attribute("error", True)
                raise

    def prompt(self, question):
        result = self.sampling_client.sample(
            prompt=question, num_samples=1, sampling_params=self.sampling_params
        ).result()
        print(self.tokenizer.decode(result.sequences[0].tokens))


def _safe_mean(xs: list[float]) -> float:
    return sum(xs) / max(len(xs), 1)


if __name__ == "__main__":
    session = setup_phoenix_tracing()
    model = Model(MODEL_NAME, RENDERER)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("tinker_agent_run") as agent_span:
        agent_span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.AGENT.value,
        )
        agent_span.set_attribute("agent.name", "spreadsheet-agent-benchmark-tinker")
        agent_span.set_attribute("llm.model_name", MODEL_NAME)
        agent_span.set_attribute("renderer", RENDERER)
        asyncio.run(model.train())
    input("Training complete. Press Enter to shut down Phoenix and exit...")
