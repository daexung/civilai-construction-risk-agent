from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class SourceEvidenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pipeline.calculation_contract import build_source_bundle
        cls.pdf = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
        cls.chunks = ROOT / "data/processed/chunks.all.jsonl"
        cls.page_map = ROOT / "data/processed/page_map.json"
        cls.source_text, cls.bundle = build_source_bundle(
            cls.pdf, cls.chunks, cls.page_map, "공통", "6-3-1")
        cls.policy_id = "formwork-6-3-1-height-started-interval-compound-v1"

    def test_only_explicit_table_note_cells_are_collected(self):
        from pipeline.calculation_contract import _table_note_text
        self.assertIsNone(_table_note_text({"kind": "table", "text": "1. 기준\n항목 | 단위 | 수량 1"}))
        self.assertEqual(_table_note_text({"kind": "table", "text": "3. 설치 및 해체\n비고 | - 명시된 주의사항"}),
                         ("3. 설치 및 해체", "- 명시된 주의사항"))

    def test_actual_height_policy_resolves_to_pdf_table_note_and_prose_survives(self):
        from backend.agent.tools.calc.policies import POLICIES, resolve_policy_source_evidence
        evidence, errors = resolve_policy_source_evidence(self.policy_id, self.bundle)
        self.assertEqual(errors, [])
        self.assertEqual(evidence["evidence_id"], POLICIES[self.policy_id]["source_note_id"])
        self.assertEqual(evidence["location"]["pdf_page"], 193)
        self.assertEqual(evidence["location"]["printed_page"], 137)
        self.assertEqual(evidence["location"]["table_heading"], "3. 설치 및 해체")
        self.assertEqual(evidence["location"]["label"], "비고")
        self.assertTrue(any(item["kind"] == "prose_text" and item["location"]["pdf_page"] == 193
                            for item in self.bundle["calculation_notes"]))
        self.assertIn("referenced_chunks", self.bundle)
        self.assertIn("referenced_evidence", self.bundle)
        self.assertIn("references", self.bundle)

    def test_misrecorded_policy_source_page_or_wording_fails(self):
        from backend.agent.tools.calc.policies import POLICIES, resolve_policy_source_evidence
        policy = POLICIES[self.policy_id]
        bad_page = {**policy, "source_locator": {**policy["source_locator"], "pdf_page": 192}}
        with patch.dict(POLICIES, {self.policy_id: bad_page}):
            evidence, errors = resolve_policy_source_evidence(self.policy_id, self.bundle)
        self.assertIsNone(evidence)
        self.assertTrue(errors)
        bad_pdf = {**policy, "source_locator": {**policy["source_locator"], "pdf_sha256": "0" * 64}}
        with patch.dict(POLICIES, {self.policy_id: bad_pdf}):
            evidence, errors = resolve_policy_source_evidence(self.policy_id, self.bundle)
        self.assertIsNone(evidence)
        self.assertTrue(errors)
        bad_anchor = {**policy, "source_note_id": "공통/6-3-1/chunk-10"}
        with patch.dict(POLICIES, {self.policy_id: bad_anchor}):
            evidence, errors = resolve_policy_source_evidence(self.policy_id, self.bundle)
        self.assertIsNone(evidence)
        self.assertTrue(any("registered evidence ID" in error for error in errors))
        bad_text = {**policy, "source_locator": {**policy["source_locator"], "required_text": "없는 원문 문구"}}
        with patch.dict(POLICIES, {self.policy_id: bad_text}):
            evidence, errors = resolve_policy_source_evidence(self.policy_id, self.bundle)
        self.assertIsNone(evidence)
        self.assertTrue(errors)

    def test_evidence_ids_do_not_depend_on_parser_array_order(self):
        from pipeline.calculation_contract import build_source_bundle
        items = [json.loads(line) for line in self.chunks.read_text(encoding="utf-8").splitlines() if line.strip()]
        selected = [item for item in items if item.get("division") == "공통" and item.get("section_no") == "6-3-1"]
        rest = [item for item in items if not (item.get("division") == "공통" and item.get("section_no") == "6-3-1")]
        random.Random(812).shuffle(selected)
        with tempfile.TemporaryDirectory() as temp:
            shuffled = Path(temp) / "chunks.jsonl"
            shuffled.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in rest + selected),
                                encoding="utf-8")
            _, reordered = build_source_bundle(self.pdf, shuffled, self.page_map, "공통", "6-3-1")
        original_ids = {item["evidence_id"] for item in self.bundle["calculation_notes"]}
        reordered_ids = {item["evidence_id"] for item in reordered["calculation_notes"]}
        self.assertEqual(original_ids, reordered_ids)
        from backend.agent.tools.calc.policies import resolve_policy_source_evidence
        evidence, errors = resolve_policy_source_evidence(self.policy_id, reordered)
        self.assertEqual(errors, [])
        self.assertEqual(evidence["evidence_id"],
                         next(item["evidence_id"] for item in self.bundle["calculation_notes"]
                              if item["kind"] == "table_note"))

    def test_section_prose_and_referenced_section_notes_are_retained(self):
        import fitz
        from pipeline.calculation_contract import build_source_bundle
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = fitz.open()
            for text in ("section one source", "section two referenced note"):
                page = pdf.new_page()
                page.insert_text((50, 50), text)
            pdf_path = root / "source.pdf"
            pdf.save(pdf_path)
            pdf.close()
            chunks = [
                {"kind": "text", "division": "common", "section_no": "1-1", "pages": [1],
                 "source": {"page": 1}, "text": "1-1\n[주] 계산 범위에 적용되는 본문 주석",
                 "references": [{"division": "common", "section_no": "1-2"}]},
                {"kind": "table", "division": "common", "section_no": "1-1", "pages": [1],
                 "source": {"page": 1, "table_id": "p1-t0"}, "text": "1. 기준\n항목 | 단위 | 수량 1"},
                {"kind": "text", "division": "common", "section_no": "1-2", "pages": [2],
                 "source": {"page": 2}, "text": "1-2\n[주] 참조 절의 적용 조건"},
            ]
            chunks_path = root / "chunks.jsonl"
            chunks_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in chunks),
                                   encoding="utf-8")
            page_map_path = root / "pages.json"
            page_map_path.write_text(json.dumps({"pages": {"1": {"printed_page": 1},
                "2": {"printed_page": 2}}}), encoding="utf-8")
            _, bundle = build_source_bundle(pdf_path, chunks_path, page_map_path, "common", "1-1")
        self.assertTrue(any("본문 주석" in item["content"] for item in bundle["calculation_notes"]))
        self.assertTrue(any("참조 절의 적용 조건" in item["content"]
                            for item in bundle["referenced_evidence"]))
        self.assertTrue(any(item.get("section_no") == "1-2" for item in bundle["references"]))
        self.assertFalse(any(item["kind"] == "table_note" for item in bundle["calculation_notes"]))

    def test_policy_preflight_blocks_model_call_on_wrong_page_mapping(self):
        from pipeline.calculation_modules import author_semantic_candidate
        bundle = json.loads(self.source_text)
        page = next(item for item in bundle["full_section_pdf_pages"] if item["pdf_page"] == 193)
        page["printed_page"] = 136
        calls = []
        result = author_semantic_candidate(json.dumps(bundle, ensure_ascii=False),
            [{"id": "probe", "spec": {}, "inputs": {}, "expected": {}}],
            model=lambda prompt: calls.append(prompt) or "{}",
            allowed_system_policies={self.policy_id}, attempt_log=None)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(calls, [])

    def test_runtime_policy_requires_full_registered_pdf_locator(self):
        from backend.agent.tools.calc.policies import POLICIES, policy_applies, resolve_policy_source_evidence
        policy = POLICIES[self.policy_id]
        evidence, errors = resolve_policy_source_evidence(self.policy_id, self.bundle)
        self.assertFalse(errors)
        locator = policy["source_locator"]
        pages = [{"pdf_page": locator["pdf_page"], "printed_page": locator["printed_page"]}]
        citation = {"evidence_id": evidence["evidence_id"], "kind": evidence["kind"],
                    "location": evidence["location"], "content": evidence["content"]}
        note_map = [{"note_id": evidence["evidence_id"], "rule_ids": ["height"]}]
        module = {"sections": [policy["scope"]], "system_policy_ids": [self.policy_id],
            "policy_note_ids": {self.policy_id: evidence["evidence_id"]},
            "policy_evidence_ids": {self.policy_id: evidence["evidence_id"]},
            "policy_versions": {self.policy_id: policy["version"]},
            "policy_sources": {self.policy_id: policy["source"]},
            "rules": [{"id": "height", "system_policy_ref": self.policy_id}],
            "calculation_contract": {"source": {"pages": pages, "citations": [citation],
                "note_rule_map": note_map, "policy_evidence": {self.policy_id: {
                    **locator, "evidence_id": evidence["evidence_id"]}}},
                "application": {"system_policies": [self.policy_id],
                    "policy_versions": {self.policy_id: policy["version"]},
                    "policy_sources": {self.policy_id: policy["source"]}}}}
        spec = {"division": policy["scope"]["division"], "section_no": policy["scope"]["section_no"]}
        self.assertTrue(policy_applies(self.policy_id, module, spec))
        legacy_module = json.loads(json.dumps(module))
        legacy_module["calculation_contract"]["source"].pop("policy_evidence")
        legacy_module.pop("policy_evidence_ids")
        self.assertFalse(policy_applies(self.policy_id, legacy_module, spec))
        module["calculation_contract"]["source"]["policy_evidence"][self.policy_id]["printed_page"] = 136
        self.assertFalse(policy_applies(self.policy_id, module, spec))


if __name__ == "__main__":
    unittest.main()
