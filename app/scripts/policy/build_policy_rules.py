from __future__ import annotations

import os

from app.core.imitation_dataset import load_step_rows
from app.core.policy_learner import learn_policy_rules
from app.core.policy_learner import save_policy_rules


def main() -> None:
    dataset_name = os.getenv("IMITATION_SOURCE_DATASET", "imitation_steps_merged_213617_220455")
    min_support = int(os.getenv("POLICY_RULE_MIN_SUPPORT", "2"))
    min_dominance = float(os.getenv("POLICY_RULE_MIN_DOMINANCE", "0.75"))

    rows = load_step_rows(dataset_name)
    if not rows:
        print("[ERROR] No imitation rows found.")
        return

    policy = learn_policy_rules(rows, min_support=min_support, min_dominance=min_dominance)
    path = save_policy_rules(policy)
    print(f"[DONE] rules={policy.get('rule_count', 0)}")
    print(f"[DONE] path={path}")


if __name__ == "__main__":
    main()
