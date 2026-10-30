"""A priced estimate must retain omitted work while ignoring reference values."""
from __future__ import annotations

import unittest

from backend.agent.tools.calc.price import price_unit, select_rate_version


class PriceCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.rates = select_rate_version("2026-10-01")
        code, rate = next(iter(self.rates["rates"].items()))
        self.spec = {"quantity_model": {"params": {
            "quantity_input": "quantity", "crew": {"rate_codes": {rate["name"]: code}}}},
            "not_calculated": []}
        self.labor = {"kind": "labor", "name": rate["name"], "unit": "인/㎥",
                      "applied": "1", "citations": []}

    def price(self, *extra_lines, **inputs):
        return price_unit(self.spec, [self.labor, *extra_lines], self.rates,
                          {"quantity": "10", **inputs}, "2026-10-01")

    def test_fully_priced_labor_is_complete(self):
        result = self.price()
        self.assertEqual(result["status"], "OK")
        self.assertFalse(result["partial"])
        self.assertGreater(int(result["reference_amounts"]["total"]), 0)

    def test_omitted_work_without_cost_category_is_partial(self):
        complete = self.price()
        self.spec["not_calculated"] = [{"item": "양생", "cite": []}]
        result = self.price()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertTrue(result["partial"])
        self.assertIsNone(result["unpriced"][0]["category"])
        self.assertEqual(result["unpriced"][0]["name"], "양생")
        self.assertEqual(result["reference_amounts"], complete["reference_amounts"])

    def test_inactive_omitted_work_does_not_mark_partial(self):
        self.spec["not_calculated"] = [{"item": "양생", "cite": [],
                                         "when": {"curing_separate": True}}]
        self.assertEqual(self.price(curing_separate=False)["status"], "OK")
        self.assertEqual(self.price(curing_separate=True)["status"], "PARTIAL")

    def test_lookup_and_reference_values_do_not_mark_partial(self):
        expected = self.price()["reference_amounts"]
        for kind in ("lookup", "reference"):
            with self.subTest(kind=kind):
                line = {"kind": kind, "name": "작업량 참고값", "citations": []}
                result = self.price(line)
                self.assertEqual(result["status"], "OK")
                self.assertTrue(result["unpriced"][0]["reference_only"])
                self.assertEqual(result["reference_amounts"], expected)

    def test_reference_does_not_hide_omitted_work(self):
        self.spec["not_calculated"] = [{"item": "양생", "cite": []}]
        result = self.price({"kind": "reference", "name": "참고값", "citations": []})
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(len(result["unpriced"]), 2)

    def test_missing_resource_price_is_partial(self):
        material = {"kind": "material", "name": "미등록 재료", "unit": "kg/㎥",
                    "applied": "1", "citations": []}
        result = self.price(material)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["unpriced"][0]["category"], "재료비")

    def test_excluded_supply_remains_partial(self):
        self.spec["supply_rules"] = [{"input": "supply", "item": "공급 재료", "category": "재료비",
                                       "cite": [], "when": {"관급": {"status": "제외", "reason": "관급"}}}]
        result = self.price(supply="관급")
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(len(result["excluded"]), 1)


if __name__ == "__main__":
    unittest.main()
