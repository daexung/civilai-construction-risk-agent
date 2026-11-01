"""Shared runtime contracts: totals/per-unit pricing and scope completeness."""
from __future__ import annotations

import unittest

from backend.agent.estimate.aggregate import _combined_priced
from backend.agent.tools.calc.adapters import _as_totals
from backend.agent.tools.calc.formula import formula_quantity
from backend.agent.tools.calc.price import price_unit, select_rate_version


class ParallelRuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.rates = select_rate_version("2026-10-01")
        code, rate = next(iter(self.rates["rates"].items()))
        self.spec = {"id": "contract", "quantity_model": {"params": {
            "quantity_input": "quantity", "crew": {"rate_codes": {rate["name"]: code}}}},
            "not_calculated": []}
        self.line = {"kind": "labor", "name": rate["name"], "unit": "인/㎥",
                     "applied": "1", "citations": []}

    def test_per_unit_price_is_constant_and_amount_scales_once(self):
        low = price_unit(self.spec, [self.line], self.rates, {"quantity": "100"}, "2026-10-01")
        high = price_unit(self.spec, [self.line], self.rates, {"quantity": "200"}, "2026-10-01")
        self.assertEqual(low["unit_prices"], high["unit_prices"])
        self.assertEqual(int(high["reference_amounts"]["total"]), 2 * int(low["reference_amounts"]["total"]))

    def test_totals_adapter_uses_quantity_one_so_pricing_does_not_multiply_twice(self):
        total_line = {"kind": "labor", "name": self.line["name"], "unit": "인·일",
                      "applied": "100", "exact": "100", "citations": []}
        adapted = _as_totals({"status": "computed", "unit_lines": [total_line],
                              "provenance": {"quantity": "100"}}, reference_only=False)
        self.assertEqual(adapted["provenance"]["quantity"], "1")
        once = price_unit(self.spec, adapted["unit_lines"], self.rates,
                          {"quantity": adapted["provenance"]["quantity"]}, "2026-10-01")
        self.assertEqual(int(once["reference_amounts"]["total"]),
                         int(once["unit_prices"]["노무비"]))

    def test_reference_only_failure_does_not_erase_real_partial_scope(self):
        real = price_unit(self.spec, [self.line, {"kind": "reference", "name": "Q 참고", "citations": []}],
                          self.rates, {"quantity": "10"}, "2026-10-01")
        self.assertEqual(real["status"], "OK")
        self.assertTrue(real["unpriced"][-1]["reference_only"])
        self.spec["not_calculated"] = [{"item": "양생", "cite": []}]
        partial = price_unit(self.spec, [self.line, {"kind": "reference", "name": "Q 참고", "citations": []}],
                             self.rates, {"quantity": "10"}, "2026-10-01")
        self.assertEqual(partial["status"], "PARTIAL")
        combined = _combined_priced([{"item_id": "i1", "request_text": "시험",
                                      "priced_result": partial}], [])
        self.assertTrue(any(x["name"] == "Q 참고" and x["reference_only"] for x in combined["unpriced"]))
        self.assertTrue(any(x["name"] == "양생" and not x.get("reference_only", False)
                            for x in combined["unpriced"]))

    def test_formula_can_represent_weighted_k_p_and_distance_total(self):
        """Small source-table reproduction of observation quantity: rate × T/15 × weighted K × P."""
        inputs = [
            {"name": "total_distance", "type": "positive_rational", "unit": "km", "required": True},
            {"name": "standard_terrain_distance", "type": "positive_rational", "unit": "km", "required": True},
            {"name": "mountain_terrain_distance", "type": "positive_rational", "unit": "km", "required": True},
            {"name": "city_terrain_distance", "type": "positive_rational", "unit": "km", "required": True},
            *[{"name": f"{area}_elevation_diff", "type": "enum", "allowed_values": ["100m 이하"], "required": True}
              for area in ("standard", "mountain", "city")],
            {"name": "tunnel_bridge_ratio_over_70", "type": "boolean", "allowed_values": [True, False], "required": True},
        ]
        spec = {"inputs": inputs, "blocked": [], "tables": [
            {"id": "p479-t0", "unit": "인/15km", "values": {"관측 | 단위 15km 15km": {"고급기술자": "7.15"}}},
            {"id": "p479-t1", "unit": "무차원", "values": {
                "표준 | 표고차 100m 이하": {"계수": "1.00"}, "산악지 | 표고차 100m 이하": {"계수": "1.25"},
                "시가지 | 표고차 100m 이하": {"계수": "1.25"}}},
            {"id": "p479-t2", "unit": "무차원", "values": {"계수": {
                "15이내": "1", "20": "0.95", "25": "0.92", "30": "0.90"}}},
        ], "quantity_model": {"params": {
            "derived": [
                {"kind": "table_cell", "name": "observation_rate", "cases": [{"table": "p479-t0",
                    "row": "관측 | 단위 15km 15km", "column": "고급기술자"}]},
                *[{"kind": "table_cell", "name": f"K_{area}", "cases": [{"table": "p479-t1", "row": row,
                    "column": "계수"}]}
                  for area, row in (("standard", "표준 | 표고차 100m 이하"),
                                    ("mountain", "산악지 | 표고차 100m 이하"),
                                    ("city", "시가지 | 표고차 100m 이하"))],
                {"kind": "expression", "name": "K_weighted", "unit": "무차원",
                 "expression": {"div": [{"add": [
                     {"mul": [{"input": "K_standard"}, {"input": "standard_terrain_distance"}]},
                     {"mul": [{"input": "K_mountain"}, {"input": "mountain_terrain_distance"}]},
                     {"mul": [{"input": "K_city"}, {"input": "city_terrain_distance"}]}]},
                     {"input": "total_distance"}]}},
                {"kind": "table_cell", "name": "P", "band_input": "total_distance",
                 "bands": [{"at_most": "15", "label": "15이내"}, {"at_most": "20", "label": "20"},
                           {"at_most": "25", "label": "25"}, {"at_most": "1000000", "label": "30"}],
                 "cases": [{"table": "p479-t2", "row": "계수"}]},
            ],
            "outputs": [{"kind": "formula", "name": "관측 고급기술자", "resource_kind": "labor", "unit": "인·일",
                "expression": {"mul": [{"div": [{"mul": [{"input": "observation_rate"}, {"input": "total_distance"}]}, {"number": "15"}]},
                    {"input": "K_weighted"}, {"input": "P"}]}}],
        }}}
        common = {"standard_elevation_diff": "100m 이하", "mountain_elevation_diff": "100m 이하",
                  "city_elevation_diff": "100m 이하", "tunnel_bridge_ratio_over_70": False}
        result15 = formula_quantity(spec, {**common, "total_distance": "15", "standard_terrain_distance": "5",
            "mountain_terrain_distance": "5", "city_terrain_distance": "5"})
        self.assertEqual(result15["status"], "computed", result15)
        self.assertEqual(result15["unit_lines"][0]["exact"], "1001/120")  # P=1 at 15km
        result45 = formula_quantity(spec, {**common, "total_distance": "45", "standard_terrain_distance": "15",
            "mountain_terrain_distance": "15", "city_terrain_distance": "15"})
        self.assertEqual(result45["status"], "computed", result45)
        self.assertEqual(result45["unit_lines"][0]["exact"], "22.5225")  # P=.90 at 45km


if __name__ == "__main__":
    unittest.main()
