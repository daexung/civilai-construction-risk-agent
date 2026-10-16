# Multi-trade estimate expectations

## Fixed calculation basis

- Basis date: `2026-10-16` (Asia/Seoul).
- Request: `수성페인트 롤러칠 2회 벽면100㎡ + 실내 방수모르타르10㎜ 바닥20㎡`.
- Before aggregation, each confirmed item was independently passed through the existing `compute_labor` and `price_unit` calculators.
- Direct costs include materials, labor, and expenses only. The existing cost statement calculator handles shared overhead and tax once after direct costs are combined.
- Quantities remain item-specific (100㎡ and 20㎡); they are never added across the two scopes.
- Missing material prices remain unpriced; they are not treated as zero.

## Independently calculated item expectations

| Stable item ID | Work | Quantity | Materials | Labor | Expenses | Direct subtotal | Unpriced scope |
|---|---|---:|---:|---:|---:|---:|---|
| `w2_5` | 수성페인트 롤러칠 2회 벽면 | 100㎡ | 미산정 | 712,800원 | 14,200원 | 727,000원 | 재료 단가 미입력 |
| `w25_27` | 실내 방수모르타르 10㎜ 바닥 | 20㎡ | 미산정 | 383,240원 | 7,660원 | 390,900원 | 재료 단가 미입력 |

Direct cost subtotal expected for aggregation: **1,117,900원**, partial because material prices are absent.

Selected rate versions: labor `2026H2`, equipment `2026`; overhead version effective on the fixed basis date: `260413`.

## Aggregate comparison

The expected aggregate direct subtotal is the sum of the two direct subtotals above. The shared cost statement must use the combined direct costs and common conditions in one call. Record the actual statement totals and the comparison here after the aggregate path has been exercised.
