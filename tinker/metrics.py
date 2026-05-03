import os

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


METRICS_DIR = "metrics"


class MetricsWriter:
    def __init__(self):
        self._steps: list[dict] = []
        self._instances: list[dict] = []

    def record_step(self, row: dict) -> None:
        self._steps.append(row)

    def record_instance(self, row: dict) -> None:
        self._instances.append(row)

    def write(self, out_dir: str = METRICS_DIR) -> None:
        os.makedirs(out_dir, exist_ok=True)
        steps_df = pd.DataFrame(self._steps)
        inst_df = pd.DataFrame(self._instances)
        steps_path = os.path.join(out_dir, "training_steps.csv")
        inst_path = os.path.join(out_dir, "training_instances.csv")
        png_path = os.path.join(out_dir, "training_metrics.png")
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
        ax_inst.set_ylabel("failures per instance (out of group_size)")
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
