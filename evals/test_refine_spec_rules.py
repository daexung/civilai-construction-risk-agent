"""refine_spec_rules의 로컬 파일·인용 검사를 네트워크 없이 확인한다.

실행: .venv/Scripts/python.exe -m unittest evals.test_refine_spec_rules -v
"""
from __future__ import annotations

import copy
from argparse import Namespace
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import refine_spec_rules as rs  # noqa: E402


class RefineSpecRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.base = Path(self.temp.name)
        self.original = self.base / "original-draft.json"
        self.original.write_text('{"unchanged":true}', encoding="utf-8")
        text = "작업 | 단위 | 수량 9%"
        self.bundle = {
            "manifest": {"division": "테스트", "section_no": "1-1-1", "draft": str(self.original),
                         "draft_sha256": hashlib.sha256(self.original.read_bytes()).hexdigest(), "warnings": []},
            "source_ids": {"t-1": {"kind": "table", "text": text},
                           "x-1": {"kind": "text", "text": "원문 인용 문장"}},
            "parsed_chunks": [{"chunk_id": "t-1", "kind": "table", "text": text},
                              {"chunk_id": "x-1", "kind": "text", "text": "원문 인용 문장"}],
            "draft_record": {"draft": {}},
        }
        self.bundle_path = self.base / "bundle.json"
        self.bundle_path.write_text(json.dumps(self.bundle), encoding="utf-8")
        self.candidate = self.good_candidate()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def good_candidate(division: str = "테스트", section: str = "1-1-1") -> dict:
        draft = {key: None for key in rs.REQUIRED}
        draft.update({"id": f"2026-정오표1차/{division}/{section}/sample", "edition": "2026-정오표1차",
                      "division": division, "section_no": section, "title": "예시", "work": "예시 작업",
                      "review": "AI 초안 · 검토 전", "source_pages": [], "inputs": [], "tables": [],
                      "quantity_model": {"name": "rate", "params": {}, "steps": []}})
        return {"draft": draft, "calc_type": "rate", "citations": [
            {"table_id": "t-1", "row": "작업", "column": "수량", "value": "9%"}], "open_questions": []}

    def validate(self, candidate: dict | list) -> tuple[dict, int]:
        path = self.base / "candidate.json"
        path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
        return rs.validate(self.bundle_path, path)

    def test_valid_candidate_passes_offline_checks(self) -> None:
        report, code = self.validate(self.candidate)
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "machine_checks_passed_review_still_required")
        self.assertTrue(report["original_draft_unchanged"])

    def test_unknown_source_id_fails(self) -> None:
        candidate = copy.deepcopy(self.candidate)
        candidate["citations"][0]["table_id"] = "missing-table"
        report, code = self.validate(candidate)
        self.assertEqual(code, 1)
        self.assertTrue(any("근거 없는 table_id" in e for e in report["errors"]))

    def test_invalid_quote_fails(self) -> None:
        candidate = copy.deepcopy(self.candidate)
        candidate["citations"] = [{"chunk_id": "x-1", "quote": "invented"}]
        report, code = self.validate(candidate)
        self.assertEqual(code, 1)
        self.assertTrue(report["errors"])

    def test_malformed_candidate_types_return_report_instead_of_crashing(self) -> None:
        for malformed in ([1, 2], {**self.candidate, "citations": "bad"},
                          {**self.candidate, "open_questions": None},
                          {**self.candidate, "citations": [{"chunk_id": [], "quote": "bad"}]}):
            with self.subTest(malformed=malformed):
                report, code = self.validate(malformed)
                self.assertEqual(code, 1)
                self.assertTrue(report["errors"])

    def test_unresolved_3m_rule_is_reported(self) -> None:
        candidate = copy.deepcopy(self.candidate)
        self.bundle["manifest"].update({"division": "공통", "section_no": "6-3-1"})
        self.bundle_path.write_text(json.dumps(self.bundle), encoding="utf-8")
        candidate["draft"].update({"division": "공통", "section_no": "6-3-1", "work": "9%까지 시공량 감산"})
        candidate["open_questions"] = ["높이가 10m인 경우 어떻게 합니까?"]
        report, code = self.validate(candidate)
        self.assertEqual(code, 1)
        self.assertTrue(any("미확정 질문" in e for e in report["errors"]))

    def test_other_trade_nine_percent_is_not_subject_to_formwork_guardrail(self) -> None:
        candidate = copy.deepcopy(self.candidate)
        candidate["draft"]["work"] = "조건이 맞으면 9%를 반드시 감산해야 한다. 물량감산"
        report, code = self.validate(candidate)
        self.assertEqual(code, 0, report)
        self.assertFalse(any("9% 감산" in e or "물리 물량" in e for e in report["errors"]))

    def test_max_word_elsewhere_does_not_hide_unsafe_9_percent_rule(self) -> None:
        candidate = copy.deepcopy(self.candidate)
        self.bundle["manifest"].update({"division": "공통", "section_no": "6-3-1"})
        self.bundle_path.write_text(json.dumps(self.bundle), encoding="utf-8")
        candidate["draft"].update({"division": "공통", "section_no": "6-3-1",
                                   "work": "최대 9%까지 조정한다. 조건이 넘으면 9%를 반드시 감산해야 한다."})
        candidate["open_questions"] = ["매 3m 구간별 누적 적용 방식은 미확정입니다."]
        report, code = self.validate(candidate)
        self.assertEqual(code, 1)
        self.assertTrue(any("고정·의무 규칙" in e for e in report["errors"]))

    def test_protected_and_existing_output_paths_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            rs.assert_new_output(self.base / "source-file.json", protected_files=[self.base / "source-file.json"])
        with self.assertRaises(ValueError):
            rs.assert_new_output(self.bundle_path, protected_files=[self.bundle_path])
        with self.assertRaises(ValueError):
            rs.assert_new_output(ROOT / "data/drafts/overwrite.json")
        with self.assertRaises(FileExistsError):
            rs.assert_new_output(self.bundle_path)

    def test_validate_report_cannot_overwrite_bundle(self) -> None:
        before = self.bundle_path.read_bytes()
        args = Namespace(bundle=str(self.bundle_path), candidate=str(self.base / "candidate.json"),
                         report=str(self.bundle_path))
        args.candidate = Path(args.candidate)
        args.candidate.write_text(json.dumps(self.candidate), encoding="utf-8")
        self.assertEqual(rs.validate_cmd(args), 1)
        self.assertEqual(self.bundle_path.read_bytes(), before)
        args.report = str(self.original)
        before = self.original.read_bytes()
        self.assertEqual(rs.validate_cmd(args), 1)
        self.assertEqual(self.original.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
