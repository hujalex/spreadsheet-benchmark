import asyncio
import json

from opentelemetry import trace
from openinference.semconv.trace import OpenInferenceSpanKindValues

import grader

from config import MAX_TOKENS
from batch import build_batch
from metrics import annotate_failure, write_failures_markdown, write_metrics
from tracing import set_span_kind

tracer = trace.get_tracer(__name__)


async def sample_example_async(async_client, model_name: str, ex: dict, *,
                               group_size: int, step: int, example_index: int):
    with tracer.start_as_current_span("openai.sample") as span:
        set_span_kind(span, OpenInferenceSpanKindValues.LLM)
        span.set_attribute("llm.provider", "openai")
        span.set_attribute("llm.model_name", model_name)
        span.set_attribute("step", step)
        span.set_attribute("example_index", example_index)
        span.set_attribute("task", ex["task"])
        span.set_attribute("input.value", ex["question"])
        span.set_attribute("llm.invocation_parameters", json.dumps({
            "max_output_tokens": MAX_TOKENS,
            "n": group_size,
        }))

        async def _one():
            resp = await async_client.responses.create(
                model=model_name,
                input=ex["question"],
                max_output_tokens=MAX_TOKENS,
            )
            text = resp.output_text or ""
            if ex.get("prefill") and not text.lstrip().startswith(ex["prefill"]):
                text = ex["prefill"] + text
            return text

        contents = await asyncio.gather(*[_one() for _ in range(group_size)])
        for i, c in enumerate(contents):
            span.set_attribute(f"output.{i}.value", c)
        return contents


async def train(async_client, model_name: str, *,
                n_steps: int = 10, batch_size: int = 15, group_size: int = 8):
    metrics_history: list[dict] = []
    instance_metrics: list[dict] = []
    failures: list[dict] = []
    per_task = batch_size // 3

    for step in range(n_steps):
        with tracer.start_as_current_span(f"step_{step}") as step_span:
            set_span_kind(step_span, OpenInferenceSpanKindValues.CHAIN)
            step_span.set_attribute("step", step)
            step_span.set_attribute("batch_size", batch_size)
            step_span.set_attribute("group_size", group_size)

            examples = build_batch(step, per_task)
            sampled = await asyncio.gather(*[
                sample_example_async(async_client, model_name, ex,
                                     group_size=group_size, step=step, example_index=i)
                for i, ex in enumerate(examples)
            ])

            rewards: list[float] = []
            rewards_by_task = {"merge": [], "policy": [], "memo": []}
            n_degenerate = 0

            for i, (ex, contents) in enumerate(zip(examples, sampled)):
                with tracer.start_as_current_span("example") as span:
                    set_span_kind(span, OpenInferenceSpanKindValues.CHAIN)
                    span.set_attribute("step", step)
                    span.set_attribute("example_index", i)
                    span.set_attribute("task", ex["task"])
                    span.set_attribute("input.value", ex["question"])

                    rewards_group = []
                    for sample_idx, content in enumerate(contents):
                        with tracer.start_as_current_span("grade_response") as gs:
                            set_span_kind(gs, OpenInferenceSpanKindValues.EVALUATOR)
                            gs.set_attribute("task", ex["task"])
                            gs.set_attribute("input.value", content)
                            reward = grader._grade(content, ex)
                            gs.set_attribute("reward", reward)
                            gs.set_attribute("output.value", str(reward))
                        rewards_group.append(reward)
                        if reward < 1.0:
                            failures.append({
                                "step": step, "example_index": i, "sample_index": sample_idx,
                                "task": ex["task"], "reward": reward, "response": content,
                                "ground_truth": ex["ground_truth"],
                                "annotation": annotate_failure(ex, content),
                            })

                    mean_reward = sum(rewards_group) / len(rewards_group)
                    advantages = [r - mean_reward for r in rewards_group]
                    rewards.append(mean_reward)
                    rewards_by_task[ex["task"]].append(mean_reward)
                    is_degenerate = all(a == 0.0 for a in advantages)
                    n_failures = sum(1 for r in rewards_group if r == 0.0)
                    instance_metrics.append({
                        "step": step, "example_index": i, "task": ex["task"],
                        "group_size": len(rewards_group), "failures": n_failures,
                        "mean_reward": mean_reward, "degenerate": is_degenerate,
                    })
                    for j, (c, r) in enumerate(zip(contents, rewards_group)):
                        span.set_attribute(f"output.{j}.value", c)
                        span.set_attribute(f"output.{j}.reward", r)
                    span.set_attribute("reward.mean", mean_reward)
                    span.set_attribute("reward.values", rewards_group)
                    span.set_attribute("degenerate", is_degenerate)
                    if is_degenerate:
                        n_degenerate += 1

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
        metrics_history.append({
            "step": step, "reward": mean_reward, "merge": merge_mean,
            "policy": policy_mean, "memo": memo_mean, "frac_degenerate": frac_degenerate,
        })
        print(
            f"Step {step:2d} | reward: {mean_reward:.3f} "
            f"(merge {merge_mean:.3f}, policy {policy_mean:.3f}, memo {memo_mean:.3f}) | "
            f"degenerate: {frac_degenerate:.0%}"
        )

    write_metrics(metrics_history, instance_metrics)
    write_failures_markdown(failures)
