from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.product.answer_synthesis import AnswerSynthesisConfig, _prompt_for_packet, _validate_answer
from source.kg.product.artifact_consistency import packet_fingerprint
from source.kg.product.claude_tool_policy import resolve_claude_cli_path
from source.kg.product.evidence_packet import EvidencePacketBuilder
from source.kg.product.goldset_judgement import _validate_judgement, load_goldset_scenarios
from source.kg.product.json_result import parse_json_object_result
from source.kg.product.validation import normalize_unique_strings, require_unique_strings
from source.scripts.run_goldset_answers import _load_or_build_packets, _load_packets, _synthesize_answers
from source.scripts.run_goldset_judgement import _load_by_scenario


class GoldsetHarnessValidationTest(unittest.TestCase):
    def test_packets_in_accepts_top_level_list_and_normalizes_id(self) -> None:
        path = _write_json([{"scenario_id": " Q082\n", "evidence_items": [], "retrieval_steps": [], "unknowns": []}])

        packets = _load_packets(("Q082",), str(path))

        self.assertEqual(packets[0]["scenario_id"], "Q082")

    def test_packets_in_without_scenario_filter_loads_all_packets(self) -> None:
        path = _write_json([{"scenario_id": "Q082"}, {"scenario_id": "CUSTOM"}])

        packets = _load_packets(None, str(path))

        self.assertEqual([packet["scenario_id"] for packet in packets], ["Q082", "CUSTOM"])

    def test_packets_in_rejects_duplicate_requested_scenario(self) -> None:
        path = _write_json([{"scenario_id": "Q082"}, {"scenario_id": "Q082"}])

        with self.assertRaisesRegex(ValueError, "duplicates scenario_id"):
            _load_packets(("Q082",), str(path))

    def test_packets_in_rejects_malformed_list_fields(self) -> None:
        path = _write_json([{"scenario_id": "Q082", "evidence_items": "bad"}])

        with self.assertRaisesRegex(ValueError, "evidence_items must be a list"):
            _load_packets(("Q082",), str(path))

    def test_evidence_packet_no_evidence_items_keep_repo_identity_shape(self) -> None:
        packet = EvidencePacketBuilder("Q999", "query", "shape").build(
            [
                {
                    "step": 1,
                    "command": "test",
                    "args": {},
                    "purpose": "exercise no-evidence fact row",
                    "result": {
                        "status": "ok",
                        "links": [
                            {
                                "fact_id": "fact_1",
                                "predicate": "RESOLVES_TO_REPO",
                                "subject": "pkg",
                                "object": "repo",
                                "evidence": [],
                            }
                        ],
                    },
                }
            ]
        )

        item = packet["evidence_items"][0]
        self.assertIn("repo_name", item)
        self.assertIn("repo_identity", item)
        self.assertIsNone(item["repo_name"])
        self.assertIsNone(item["repo_identity"])

    def test_public_answer_harness_refuses_to_build_private_packets(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --packets-in"):
            _load_or_build_packets("unused", ("Q082",), None)

    def test_load_by_scenario_accepts_object_wrapper_and_normalizes_id(self) -> None:
        path = _write_json({"answers": [{"scenario_id": " Q082\n", "answer": "ok"}]})

        answers = _load_by_scenario(str(path), "answers")

        self.assertEqual(answers["Q082"]["scenario_id"], "Q082")

    def test_load_by_scenario_rejects_duplicate_ids(self) -> None:
        path = _write_json([{"scenario_id": "Q082"}, {"scenario_id": " Q082 "}])

        with self.assertRaisesRegex(ValueError, "duplicates scenario_id"):
            _load_by_scenario(str(path), "answers")

    def test_goldset_markdown_rejects_duplicate_ids(self) -> None:
        path = _write_text(
            "| ID | User Query | Expected Answer Shape | Ground Truth Answer |\n"
            "|---|---|---|---|\n"
            "| Q082 | first | shape | truth1 |\n"
            "| Q082 | second | shape | truth2 |\n"
        )

        with self.assertRaisesRegex(ValueError, "duplicate goldset scenario ID"):
            load_goldset_scenarios(str(path), {"Q082"})

    def test_answer_validation_rejects_missing_list_field(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unknowns.*required"):
            _validate_answer(
                {
                    "score": "Pass",
                    "failure_modes": ["none"],
                    "answer": "ok",
                    "score_reason": "ok",
                    "caveats": [],
                }
            )

    def test_answer_validation_rejects_contradictory_none_sentinel(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "cannot combine"):
            _validate_answer(
                {
                    "score": "Pass",
                    "failure_modes": ["none", "bad synthesis"],
                    "answer": "ok",
                    "score_reason": "ok",
                    "caveats": [],
                    "unknowns": [],
                }
            )

    def test_judgement_validation_rejects_non_pass_with_none_sentinel(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "cannot use"):
            _validate_judgement(
                {
                    "evidence_completeness": "partial",
                    "answer_score": "Partial",
                    "failure_owners": ["none"],
                    "summary": "ok",
                    "recommended_next_action": "fix evidence",
                    "ground_truth_coverage": [],
                    "missing_or_weak_evidence": [],
                    "answer_issues": [],
                }
            )

    def test_parse_json_object_result_handles_prefixed_fenced_json(self) -> None:
        parsed = parse_json_object_result('Here is JSON:\n```json\n{"score": "Pass"}\n```', "test")

        self.assertEqual(parsed["score"], "Pass")

    def test_require_unique_strings_rejects_duplicates(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate value"):
            require_unique_strings(("Q082", "Q082"), "--scenario")

    def test_normalize_unique_strings_strips_before_duplicate_check(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate value"):
            normalize_unique_strings((" Q082 ", "Q082"), "--scenario")

    def test_resolve_claude_cli_path_rejects_bad_configured_path(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not executable"):
            resolve_claude_cli_path("/definitely/missing/claude")

    def test_synthesized_answers_include_packet_fingerprint(self) -> None:
        packet = {
            "scenario_id": "Q082",
            "user_query": "Which clients call the API?",
            "expected_answer_shape": "list clients",
            "evidence_items": [{"claim": "client A calls API"}],
            "retrieval_steps": [{"name": "domain references"}],
            "unknowns": [],
        }

        with patch("source.scripts.run_goldset_answers.ClaudeAnswerSynthesizer", _FakeSynthesizer):
            result = asyncio.run(_synthesize_answers("snapshot", [packet], AnswerSynthesisConfig()))

        answer = result["answers"][0]
        self.assertEqual(result["snapshot"], "snapshot")
        self.assertEqual(answer["evidence_item_count"], 1)
        self.assertEqual(answer["retrieval_step_count"], 1)
        self.assertEqual(answer["packet_fingerprint"], packet_fingerprint(packet))

    def test_synthesized_answers_preserve_raw_snapshot_label(self) -> None:
        packet = {"scenario_id": "Q082", "evidence_items": [], "retrieval_steps": [], "unknowns": []}

        with patch("source.scripts.run_goldset_answers.ClaudeAnswerSynthesizer", _FakeSynthesizer):
            result = asyncio.run(_synthesize_answers("~/not-a-path", [packet], AnswerSynthesisConfig()))

        self.assertEqual(result["snapshot"], "~/not-a-path")

    def test_answer_prompt_adds_reconciliation_rules_for_reconciliation_packets(self) -> None:
        packet = {
            "scenario_id": "Q100",
            "user_query": "Which documented endpoints drift?",
            "expected_answer_shape": "Endpoint drift table.",
            "evidence_items": [
                {"claim": "matched endpoint", "reconciliation_group": "matched"},
                {"claim": "fuzzy endpoint", "reconciliation_group": "possible_matches"},
                {"claim": "right-only endpoint", "reconciliation_group": "right_only"},
            ],
            "retrieval_steps": [],
            "unknowns": [],
        }

        prompt = _prompt_for_packet(packet)

        self.assertIn("Contract reconciliation requirements:", prompt)
        self.assertIn("matched=1, possible_matches=1, right_only=1", prompt)
        self.assertIn("matched-but-unexpected repo/service placement", prompt)
        self.assertIn("repo/service placement drift", prompt)
        self.assertIn("If a material reconciliation category is omitted", prompt)

    def test_answer_prompt_omits_reconciliation_rules_for_non_reconciliation_packets(self) -> None:
        packet = {
            "scenario_id": "Q088",
            "user_query": "Which queues connect services?",
            "expected_answer_shape": "Queue lineage.",
            "evidence_items": [{"claim": "service produces queue"}],
            "retrieval_steps": [],
            "unknowns": [],
        }

        prompt = _prompt_for_packet(packet)

        self.assertNotIn("Contract reconciliation requirements:", prompt)
        self.assertNotIn("matched-but-unexpected repo/service placement", prompt)

    def test_answer_prompt_adds_event_lineage_rules_for_event_packets(self) -> None:
        packet = {
            "scenario_id": "Q106",
            "user_query": "Who produces and consumes the queue?",
            "expected_answer_shape": "Producer, consumer, and downstream lineage.",
            "evidence_items": [
                {"claim": "producer sends queue", "fact_type": "PRODUCES_EVENT"},
                {"claim": "consumer receives queue", "fact_type": "CONSUMES_EVENT"},
                {"claim": "config references queue", "fact_type": "REFERENCES_EVENT_CHANNEL"},
            ],
            "retrieval_steps": [],
            "unknowns": [],
        }

        prompt = _prompt_for_packet(packet)

        self.assertIn("Event lineage requirements:", prompt)
        self.assertIn("CONSUMES_EVENT=1, PRODUCES_EVENT=1, REFERENCES_EVENT_CHANNEL=1", prompt)
        self.assertIn("downstream channels produced by those consumers", prompt)
        self.assertIn("If a material event lineage edge is omitted", prompt)

    def test_answer_prompt_omits_event_lineage_rules_for_non_event_packets(self) -> None:
        packet = {
            "scenario_id": "Q100",
            "user_query": "Which endpoints drift?",
            "expected_answer_shape": "Endpoint drift.",
            "evidence_items": [{"claim": "endpoint match", "fact_type": "DOCUMENTS_ENDPOINT"}],
            "retrieval_steps": [],
            "unknowns": [],
        }

        prompt = _prompt_for_packet(packet)

        self.assertNotIn("Event lineage requirements:", prompt)
        self.assertNotIn("downstream channels produced by those consumers", prompt)


def _write_json(value: object) -> Path:
    return _write_text(json.dumps(value))


def _write_text(value: str) -> Path:
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        path = Path(handle.name)
    path.write_text(value, encoding="utf-8")
    return path


class _FakeSynthesizer:
    def __init__(self, _config: AnswerSynthesisConfig) -> None:
        pass

    async def synthesize(self, packet: dict[str, object]) -> dict[str, object]:
        return {
            "scenario_id": packet["scenario_id"],
            "score": "Pass",
            "failure_modes": ["none"],
            "answer": "ok",
            "score_reason": "ok",
            "caveats": [],
            "unknowns": [],
        }


if __name__ == "__main__":
    unittest.main()
