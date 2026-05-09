from __future__ import annotations

import argparse
import json
from pathlib import Path

from source.kg.product import EvidencePacketBuilder, SCENARIO_PLANS
from source.kg.queries import KgSnapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a product-validation scenario plan against a KG snapshot.")
    parser.add_argument("--snapshot", required=True, help="Directory containing JSONL KG files")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIO_PLANS),
        help="Scenario ID to run; repeatable. Defaults to all implemented scenarios.",
    )
    parser.add_argument("--out", help="Optional JSON output path")
    args = parser.parse_args()

    kg = KgSnapshot(args.snapshot)
    scenario_ids = args.scenario or sorted(SCENARIO_PLANS)
    packets = [_run_scenario(kg, scenario_id) for scenario_id in scenario_ids]
    result = {"snapshot": str(Path(args.snapshot).expanduser()), "scenario_count": len(packets), "packets": packets}

    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        output_path = Path(args.out).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


def _run_scenario(kg: KgSnapshot, scenario_id: str) -> dict:
    plan = SCENARIO_PLANS[scenario_id]
    step_results = plan.run(kg)
    return EvidencePacketBuilder(
        scenario_id=plan.scenario_id,
        user_query=plan.user_query,
        expected_answer_shape=plan.expected_answer_shape,
    ).build(step_results)


if __name__ == "__main__":
    main()
