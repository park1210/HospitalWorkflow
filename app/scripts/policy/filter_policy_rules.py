from __future__ import annotations

import os

from app.core.imitation_dataset import load_step_rows
from app.core.policy_learner import filter_policy_rules
from app.core.policy_learner import load_policy_rules
from app.core.policy_learner import save_policy_rules


def main() -> None:
    validation_dataset = os.getenv("POLICY_VALIDATION_DATASET", "trajectory_steps_merged_213617_220455")
    min_validation_support = int(os.getenv("POLICY_VALIDATION_MIN_SUPPORT", "2"))
    min_return_margin = float(os.getenv("POLICY_VALIDATION_MIN_RETURN_MARGIN", "0.0"))

    policy = load_policy_rules()
    if not policy:
        print("[ERROR] No learned policy rules found.")
        return

    validation_rows = load_step_rows(validation_dataset)
    if not validation_rows:
        print("[ERROR] No validation rows found.")
        return

    filtered = filter_policy_rules(
        policy,
        validation_rows,
        min_validation_support=min_validation_support,
        min_return_margin=min_return_margin,
    )
    path = save_policy_rules(filtered)
    print(f"[DONE] kept_rules={filtered.get('rule_count', 0)}")
    print(f"[DONE] dropped_rules={filtered.get('dropped_rule_count', 0)}")
    print(f"[DONE] path={path}")


if __name__ == "__main__":
    main()
