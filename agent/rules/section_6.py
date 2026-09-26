"""Static section 6 specifications and the supported agent case."""

SPECS = {
    "6-1-1": {
        "rule": "per_day", "basis_label": "(일당)", "row_condition": "공법", "trade_re": r"^(\S+)$",
        "column_condition": "구조물", "column_re": r"^시공량\(㎥\) (\S+) (\S+)$", "crew_re": r"^수량 (\S+)$",
        "trades": ["콘크리트공", "보통인부"],
    },
    "6-1-2": {
        "rule": "per_unit", "basis_label": "(㎥당)", "row_condition": "유형", "trade_re": r"^구분 (\S+)$",
        "column_condition": "구조물", "column_re": r"^수량 (\S+) (\S+)$", "crew_re": None,
        "trades": ["콘크리트공", "보통인부"],
        # 원문 [주]가 현장 사실을 적용 기준으로 두는 값. 확인 항목 키에 명시적 true가 있어야 계산한다
        "confirmations": {
            ("구조물", "소형구조물"): {
                "key": "small_structure_scattered",
                "question": "현장이 원문 [주] ②의 소형구조물 적용 조건(소량의 콘크리트 구조물이 산재)에 해당합니까? (true/false)",
                "clause_marker": "소형구조물은",
            },
        },
    },
}

SUPPORTED_CASE = {
    "id": "6-1-1-manual-reinforced",
    "section": "6-1-1 레디믹스트콘크리트 타설('24년 보완)",
    "section_no": "6-1-1",
    "pdf_page": 185,
    "printed_page": 129,
    "method": "인력운반 타설",
    "structure": "철근구조물",
    "trades": ["콘크리트공", "보통인부"],
    "assumptions": [
        "인력운반 타설이 가능한 현장으로 가정한다. 공법 적합성을 판정하지 않는다.",
        "개소별 소량 타설 위치의 산재, 소규모 및 기타 할증/생산성 조정은 적용하지 않는다.",
    ],
    "not_calculated": ["공구손료/경장비 비용", "자재비, 기타 장비비", "별도 양생, 표면 마무리, 추가 인력",
                       "간접비, 이윤, 세금", "실제 공기 및 투입 인원 편성"],
}
