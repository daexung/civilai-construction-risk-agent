# Active calculation ambiguities (2026-10-19)

These six IDs remain failed in the saved executable partition. The entries below preserve source-confirmed alternatives; no range endpoint, unit, or coefficient application is selected by the evaluator.

| ID | Source evidence | Ambiguity and consequence | Status |
|---|---|---|---|
| Mechanical 13-2-2 steel plate cutting | Physical p.800 / printed p.744, table p800-t1 and note ③ | Labor cells are explicit ranges without an endpoint selector. For 3 mm and 100 m, welder endpoints produce 0.55 vs 0.37 person-days and special-worker endpoints 0.27 vs 0.19. The 3% equipment-cost rule applies to labor cost but does not choose a labor endpoint. | Failed; source leaves selection open |
| Civil 7-3-1 caisson launching | Physical p.448 / printed p.392, p448-t0 | Per-piece worker quantities are ranges. Below 500 t, scaffold worker is 1–2 and ordinary worker 2–3; summing crews would yield 3–5 person-days, but no source condition selects a point in either range. | Failed; source leaves selection open |
| Civil 7-3-2 caisson placement | Physical p.448 / printed p.392, p448-t1 | Below 500 t, diver crew is 1–2 crews, scaffold worker 1–2, ordinary worker 2–3. The source gives no route to a single crew or labor quantity. | Failed; source leaves selection open |
| Mechanical 8-2-2 packaged HVAC installation | Physical p.750 / printed p.694, p750-t0 | Original matrix axes are output capacity, work count and floor; the table has no denominator/unit heading. Notes include carrying and equipment costs but do not state the quantity basis. Do not infer `per unit` from the section title. | Failed; denominator absent |
| Mechanical 13-7-4 hot-blast furnace body and accessories | Physical p.881 / printed p.825, p881-t0 | Original column is headed only `수량`; no unit is printed. Adjacent 13-7-5 explicitly says ton-based, but that is a separate work item and is not evidence for 13-7-4. | Failed; denominator absent |
| Civil 9-2-4 third-class leveling survey | Physical p.479 / printed p.423, p479-t0–t2 and p480-x0 | Table combines 15 km work rates and point-based rates. The source excludes point work from P; K varies by terrain/elevation, P varies with distance, and parentheses denote office work. A single km input cannot safely scale all rows; office/field split and coefficient application must be connected by task before a total is claimed. At 15/20/30 km, P is 1.00/0.95/0.90. | Failed; mixed denominators and task-scope routing |

Maintenance 2-1-6 roller count and rate-combination alternatives remain in `docs/reviews/interpretation-review-2026-10-19.md` and are not resolved by this list.
