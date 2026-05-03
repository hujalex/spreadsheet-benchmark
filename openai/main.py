"""Replicates the tinker/main.py RL training environment with the OpenAI SDK.

OpenAI doesn't expose policy-gradient updates on hosted models, so this script
uses Reinforcement Fine-Tuning (RFT) — the closest analog. The same three tasks
(merge / policy / memo) are constructed with identical prompts and ground
truths as in tinker/main.py. A JSONL training file is written, custom Python
graders matching tinker's Grader logic are attached, and an RFT job is
submitted.

A local sampling+grading loop using the Responses API also mirrors tinker's
per-step metrics (rewards, degenerate fraction, failure rubric).
"""

import argparse
import asyncio

from openai import OpenAI, AsyncOpenAI
from opentelemetry import trace
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

from config import MODEL_NAME
from rft import build_rft_jsonl, submit_rft_job
from sampling import train
from tracing import setup_phoenix_tracing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["sample", "rft", "build-jsonl"], default="sample",
                        help="sample: local sampling+grading loop; "
                             "build-jsonl: write the RFT training file; "
                             "rft: build the file then submit an RFT job.")
    parser.add_argument("--n-steps", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--group-size", type=int, default=4)
    parser.add_argument("--jsonl", default="metrics_openai/rft_train.jsonl")
    args = parser.parse_args()

    setup_phoenix_tracing()
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("openai_agent_run") as span:
        span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND,
                           OpenInferenceSpanKindValues.AGENT.value)
        span.set_attribute("agent.name", "spreadsheet-agent-benchmark-openai")
        span.set_attribute("llm.model_name", MODEL_NAME)

        if args.mode == "sample":
            async_client = AsyncOpenAI()
            asyncio.run(train(async_client, MODEL_NAME,
                              n_steps=args.n_steps,
                              batch_size=args.batch_size,
                              group_size=args.group_size))
        elif args.mode == "build-jsonl":
            build_rft_jsonl(args.n_steps, args.batch_size, args.jsonl)
        elif args.mode == "rft":
            build_rft_jsonl(args.n_steps, args.batch_size, args.jsonl)
            submit_rft_job(OpenAI(), args.jsonl, MODEL_NAME)

    input("Done. Press Enter to shut down Phoenix and exit...")


if __name__ == "__main__":
    main()
