"""ODL 원본 JSON -> '원문 보관 구조'.

기존 시제품(_parser-lab-2026-10-10/pilot/store.py)과 2026-10-10 전용 폴더의 수정본을 바탕으로 한다.
이 파일은 (1) 문서 문맥(부문·장·절·소제목, 기준·주석, 쪽 경계), (2) 칸 단위 추적(ODL 칸 id·좌표·병합·분리 근거),
(3) 불확실 표시를 보관한다. LLM·임베딩은 쓰지 않는다. 쪽·공종마다의 예외나 숫자 보정은 없다.

2026-10-11 변경(`# 변경:`)
  - 표·주석·기준 식별자에 원시 출력 이름(run)을 붙인다. 다른 ODL 실행의 id를 섞지 않는다
  - 쪽 높이는 실제 PDF 쪽 크기를 쓴다(다른 쪽의 가장 높은 글자 좌표로 대신하지 않는다)
  - 머리글은 assemble.header_of(음영 → 숫자 규칙 → 가정)의 판정을 그대로 쓴다. 보관과 조립이 같은 근거를 갖는다
  - 칸은 공통 표의 odl_cell(원래 칸 id)과 split(분리 기록)에서 읽는다. 좌표 일치로 되짚지 않는다
  - 행 대응 문제는 어댑터의 row_map(stacked_unsplit)에서 낸다
  - 번호 없는 소제목·목록 항목 끝의 기준을 분리해 별도 기준 항목으로 둔다(원래 글은 그대로)
  - 쪽 경계: 부문이 바뀌면 문맥을 끝낸다. 다음 쪽 첫머리 주석을 앞 쪽 마지막 표에 위치 근거로 연결한다.
    이어짐 표시(→)가 있는 표와 다음 쪽 첫 표의 관계를 논리 표로 둔다
"""
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import assemble  # noqa: E402
import odl_tables as ot  # noqa: E402

CHILD = ot.CHILD_KEYS
VALUE_RE = ot.VALUE_RE
MAX_GROUP_ROWS = 6      # 큰 표에서 한 묶음이 이 줄 수를 넘으면 다음 라벨 열 경계로 다시 나눈다
SMALL_TABLE_ROWS = 8    # 본문 하위 행이 이 수 이하면 표 통째로 유지
TEXT_TYPES = ("paragraph", "list item", "caption", "heading", "text block")
BOTTOM_RATIO = 155 / 864   # 표 아래끝이 쪽 높이의 이 비율 안이면 쪽 맨 아래 표로 본다(시제품 가정값)
HEADER_ASSUMED = ("header_fallback", "header_extended_numeric")


def squash(text: str) -> str:
    """줄바꿈·한 글자씩 띄운 글을 한 줄 라벨로. '인 력 운 반\\n타 설' -> '인력운반 타설'"""
    out = []
    for line in (text or "").split("\n"):
        parts = line.split()
        if len(parts) > 1 and all(len(p) == 1 for p in parts):
            parts = ["".join(parts)]
        out += parts
    return " ".join(out)


FULL_CODE_RE = re.compile(r"^(\d{3,6})-(\d{3,6})$")
NAME_HEADERS = {"기종", "명칭", "작업명", "공종", "종류", "구분"}


def cell_display(cell):
    """원문 칸은 그대로 두고, 행에 확정해 표시할 수 있는 이름·코드를 구별한다."""
    semantic = cell.get("semantic") or {}
    if semantic.get("kind") == "label_scope" and semantic["status"] == "unresolved":
        return "[이름 적용 범위 미확정]"
    if semantic.get("kind") == "classification_code" and semantic["status"] == "derived":
        return semantic["normalized"]
    return cell["label"]


def analyze_cell_semantics(tb):
    """이름의 범위는 추측하지 않고, 분류 번호는 같은 원문 칸의 명시적 앞자리만 잇는다.

    PDF 기준선 확정은 행 위치의 근거다. 병합 이름의 의미가 확정됐다는 근거로 쓰지 않는다.
    여러 문단이 든 병합 이름 칸은 소속 후보로 남긴다. 문단 하나의 단순 줄바꿈은 그대로 둔다.
    """
    headers = [re.sub(r"\s+", "", " ".join(p)) for p in tb["col_path"]]
    bodies = [c for c in tb["cells"] if c["r0"] >= tb["header_rows"] and not c["has_nested_table"]]
    for c in bodies:
        if c["c1"] - c["c0"] != 1 or c["r1"] - c["r0"] <= 1:
            continue
        is_name = c["c0"] in tb["label_cols"] or headers[c["c0"]] in NAME_HEADERS
        # 비고 문장·숫자와 정의 표는 행 이름 후보로 다루지 않는다.
        if not is_name or c["cell_id"] in tb["_numeric"] or headers[c["c0"]] in {"비고", "분류번호"}:
            continue
        ps = [p for p in c["paras"] if p["text"].strip()]
        if len(ps) < 2:
            continue
        c["semantic"] = {"kind": "label_scope", "status": "unresolved", "raw_text": c["text_raw"],
                         "candidate_labels": [{"text": squash(p["text"]), "odl_id": p["odl_id"], "bbox": p["bbox"]}
                                              for p in ps],
                         "rows": [c["r0"], c["r1"]],
                         "basis": "병합 이름 칸에 여러 문단이 있으나 문단별 적용 행을 확정하지 못함"}
        tb["flags"].append({"cell_id": c["cell_id"], "code": "이름 적용 범위 미확정", "severity": "semantic",
                            "detail": c["semantic"]["basis"], "text": c["text_raw"]})

    code_cols = {i for i, h in enumerate(headers) if h == "분류번호"}
    # 변경: 표 마지막 앞자리(다음 쪽 이어짐 표의 근거). 칸 글의 줄을 위에서 아래로 읽는다
    last = None
    for c in sorted((c for c in bodies if c["c0"] in code_cols), key=lambda c: c["r0"]):
        for line in c["text_raw"].split("\n"):
            m = re.fullmatch(r"(\d{4})-(\d{4})?", re.sub(r"\s+", "", line))
            if m:
                last = m.group(1)
    tb["_code_last_prefix"] = last
    if tb["common"].get("line_regrid") and code_cols:
        # 변경: 원문 글자 위치로 다시 짠 표는 줄마다 행이다. 분류 번호 열을 위에서 아래로 읽어
        # 완전한 번호(XXXX-YYYY)의 앞자리를 같은 열 아래 줄임 번호(YYYY, -YYYY)에 잇는다.
        # 표 첫 줄이 줄임 번호면 (1) 표 바로 위 항목 제목 '(XXXX) 기종'의 번호, 또는 (2) 앞 쪽 표가 '→'로 이어지고
        # 같은 절이며 그 표의 마지막 앞자리가 있을 때만 그 앞자리를 쓴다. 근거가 없으면 미확정으로 둔다.
        ctx = tb.get("_code_context") or {}
        for col in sorted(code_cols):
            prefix, basis = None, None
            m = re.match(r"^\((\d{4})\)", (tb["section_path"] or [""])[-1])
            if m:
                prefix, basis = m.group(1), {"rule": "표 바로 위 항목 제목의 분류 번호", "heading": tb["section_path"][-1]}
            elif ctx.get("prefix"):
                prefix, basis = ctx["prefix"], {"rule": "앞 쪽에서 '→'로 이어진 같은 절 표의 마지막 앞자리",
                                                "previous_table": ctx["table_id"], "previous_code": ctx["code"]}
            for c in sorted((c for c in bodies if c["c0"] == col and c["c1"] == col + 1), key=lambda c: c["r0"]):
                text = re.sub(r"\s+", "", c["text_raw"])
                sem = {"kind": "classification_code", "raw_text": c["text_raw"], "status": "literal", "normalized": None}
                c["semantic"] = sem
                full = FULL_CODE_RE.fullmatch(text)
                head = re.fullmatch(r"(\d{4})-", text)
                short = re.fullmatch(r"-?(\d{4})", text)
                if full:
                    sem["normalized"] = text
                    prefix, basis = full.group(1), {"rule": "같은 열 위쪽의 완전한 분류 번호", "prefix_cell_id": c["cell_id"],
                                                    "prefix_raw": c["text_raw"]}
                elif head:
                    sem.update(status="prefix", normalized=None)
                    prefix, basis = head.group(1), {"rule": "같은 열 위쪽의 앞자리 표시", "prefix_cell_id": c["cell_id"],
                                                    "prefix_raw": c["text_raw"]}
                elif short and prefix:
                    sem.update(status="derived", normalized=f"{prefix}-{short.group(1)}", basis=dict(basis, header="분류 번호"))
                elif text not in ("", "-", "〃"):
                    sem.update(status="unresolved", basis="앞자리 근거(같은 열 위쪽 번호, 항목 제목, 앞 쪽 이어짐)가 없음")
                    tb["flags"].append({"cell_id": c["cell_id"], "code": "코드 연결 미확정", "severity": "semantic",
                                        "detail": sem["basis"], "text": c["text_raw"]})
            tb["_code_last_prefix"] = prefix
        code_cols = set()
    by_origin = {}
    for c in bodies:
        if c["c0"] in code_cols and c["c1"] == c["c0"] + 1:
            by_origin.setdefault((c["src"]["odl_id"], c["c0"]), []).append(c)
    for cs in by_origin.values():
        cs.sort(key=lambda c: c["r0"])
        prefix_cell = None
        for c in cs:
            text = re.sub(r"\s+", "", c["text_raw"])
            full = FULL_CODE_RE.fullmatch(text)
            sp = c.get("split") or {}
            sem = {"kind": "classification_code", "raw_text": c["text_raw"], "status": "literal",
                   "normalized": None}
            c["semantic"] = sem
            if full:
                sem["normalized"] = text
                prefix_cell = (c, full)
                continue
            # 숫자 앞의 0은 지우지 않는다. 다른 칸·다른 표로 앞자리를 넘기지 않는다.
            if (text.isascii() and text.isdigit() and prefix_cell is not None
                    and len(text) == len(prefix_cell[1].group(2))
                    and sp.get("role") == "piece" and sp.get("confirmed") is True
                    and (prefix_cell[0].get("split") or {}).get("confirmed") is True):
                pc, pm = prefix_cell
                sem.update(status="derived", normalized=f"{pm.group(1)}-{text}",
                           basis={"rule": "같은 원문 분류 번호 칸의 앞선 완전한 코드와 같은 자리수의 끝 번호",
                                  "header": "분류 번호", "origin_odl_id": c["src"]["odl_id"],
                                  "prefix_cell_id": pc["cell_id"], "prefix_raw": pc["text_raw"],
                                  "row_mapping": "pdf_baseline"})
                continue
            # 알 수 없는 표기와 빈 표시는 앞자리 이어받기를 끊는다.
            if text not in ("", "-", "〃"):
                sem.update(status="unresolved", basis="같은 원문 칸의 확정된 앞자리와 번호 형식으로 완전한 코드를 정할 수 없음")
                tb["flags"].append({"cell_id": c["cell_id"], "code": "코드 연결 미확정", "severity": "semantic",
                                    "detail": sem["basis"], "text": c["text_raw"]})
            prefix_cell = None


def paras(node):
    """칸 안 글(문단·목록 항목)을 문서 순서대로. 중첩 표 안은 건너뛴다."""
    got = []

    def walk(n):
        if isinstance(n, list):
            for c in n:
                walk(c)
            return
        if not isinstance(n, dict) or n.get("type") == "table":
            return
        if isinstance(n.get("content"), str) and n.get("type") in TEXT_TYPES:
            got.append(n)
        for k in CHILD:
            for c in n.get(k) or []:
                walk(c)

    for k in CHILD:
        for c in node.get(k) or []:
            walk(c)
    return got


def bbox_of(n):
    b = n.get("bounding box")
    return [round(v, 1) for v in b] if b else None


def marker_of(text):
    m = re.match(r"^\s*(\[주\]\s*)?([①-⑳㉮-㉳]|[-※◦ㅇ○]|\d+\))?", text)
    return (m.group(0).strip() if m else "") or None


BASIS_RE = re.compile(r"\((?:단위\s*:)?[^()]*당\)|\(단위\s*:[^)]*\)")
# 글 끝에 붙은 기준 표기: '… 재료량 (㎥당)', '… 참고한다.\n(㎡당)'
TRAILING_BASIS_RE = re.compile(r"(?:^|\s)(\((?:단위\s*:)?[^()]*당\))\s*$")
NOTE_START_RE = re.compile(r"^(?:[※◦ㅇ○-]\s*)?(?:\[주\]\s*)?①")
# 품목 코드가 붙은 제목: '(7750) 취부기(녹생토 암절개면 보호식재용)'. ODL이 제목이 아닌 글(caption·목록 항목)로 내는 일이 있다
ITEM_TITLE_RE = re.compile(r"^\(\d{3,6}\)\s*\S[^\n]{0,60}$")
ARROW_TYPES = ("heading", "caption", "paragraph", "text block")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def sentence_complete(text: str) -> bool:
    return bool(re.search(r"(?:[.!?]|다)\s*$", (text or "").strip()))


def looks_like_subheading(text: str) -> bool:
    """문장이 아닌 짧은 이름 줄('[참고자료] 모르타르 배합 재료량'). 제목 표지가 있는 번호 제목은 따로 다룬다."""
    t = (text or "").strip()
    return 0 < len(t) <= 60 and "\n" not in t and not sentence_complete(t) and not re.match(r"^([①-⑳㉮-㉳]|\[주\]|[-※◦ㅇ○])", t)


class Store:
    def __init__(self, doc: dict, pages: list[int] | None = None, *, run: str = "r0", probe=None,
                 divisions: dict[int, str | None] | None = None, row_mappings: dict | None = None,
                 completeness: dict | None = None):
        self.doc = doc
        self.row_mappings = dict(row_mappings or {})            # 변경: 원문 대조로 확정한 행 연결(source_corrections)
        self.completeness = completeness                        # 변경: 복구 표 누락 보완(분수식 읽기·확인한 보류)
        self._completeness_seen = set()
        self.run = run                                          # 변경: 원시 출력 이름. 식별자에 붙는다
        self.probe = probe                                      # 변경: structure_rules.PdfProbe(없으면 추정 좌표)
        self.divisions = divisions or {}                        # 변경: 쪽별 부문(기존 page_map.json, 읽기 전용)
        self.pages = sorted(pages) if pages else None
        self.tables, self.notes, self.headings, self.basis = [], [], [], []
        self.logical_tables = []
        self.boundaries = []                                    # 변경: 문맥을 끝낸 쪽 경계 기록
        self.skipped_text = []                                  # 변경(본문 완전성): 하위 글 중 내보내지 않은 글과 사유
        self.page_top, self.printed_page, self.part_marks = {}, {}, {}
        self.page_height_source = "PDF 쪽 크기(PyMuPDF)" if probe is not None else "ODL 출력의 최대 좌표(추정)"
        self.context_out = None
        self._order = 0
        self._build()

    def _next(self) -> int:
        """문서 순서 번호. 표·주석·기준·제목이 만들어진 차례다."""
        self._order += 1
        return self._order

    def _id(self, kind: str, page: int, odl_id) -> str:
        return {"t": f"{self.run}-p{page}-o{odl_id}", "n": f"{self.run}-p{page}:n{odl_id}",
                "b": f"{self.run}-p{page}:b{odl_id}", "h": f"{self.run}-p{page}:h{odl_id}"}[kind]

    # ---------------- 문서 문맥 ----------------
    def _build(self):
        kids = [n for n in self.doc["kids"] if self.pages is None or n.get("page number") in self.pages]
        if self.probe is None:
            top = max(n["bounding box"][3] for n in self.doc["kids"] if n.get("bounding box"))
        for n in kids:
            p = n.get("page number")
            if p and p not in self.page_top:
                self.page_top[p] = self.probe.page_height(p) if self.probe is not None else top   # 변경: 실제 쪽 높이
        self.page_height = self.page_top
        page_last_bottom = {}      # 쪽마다 마지막 내용(표·주석)의 아래끝(PDF 아래 원점 좌표)
        open_basis = None          # 다음 제목·기준 전까지 이어지는 표를 후보로 모으는 기준
        stack, last_page, gap = [], None, True
        cur, note_mode, pending_basis, intro_owner = None, False, None, None
        at_top, cont_pending, prev_note, prev_item = True, None, None, None
        last_table_of_page = None
        def push_heading(n, lvl, text, p, b, from_text, next_is_table):
            """제목 하나를 문맥에 올린다. ODL이 제목으로 낸 것과, 제목처럼 쓰인 글(품목 코드 제목)을 같게 다룬다."""
            nonlocal stack, cur, note_mode, pending_basis, intro_owner, at_top, prev_note, prev_item, open_basis
            while stack and stack[-1]["level"] >= lvl:
                stack.pop()
            h = {"level": lvl, "text": squash(text), "odl_id": n["id"], "page": p, "bbox": b, "from_text": from_text,
                 "order": self._next(), "heading_id": self._id("h", p, n["id"])}
            stack.append(h)
            self.headings.append({**h, "path": [x["text"] for x in stack], "context_gap": gap,
                                  "path_complete": bool(stack and re.match(r"제\d+장", stack[0]["text"]))})
            cur, note_mode, pending_basis, intro_owner = None, False, None, h
            at_top, prev_note, prev_item, open_basis = False, None, ("heading", h), None
            # 번호 제목 끝의 기준 '3. 일일시공량 (일당)': 청킹이 제목에서 직접 읽는다. 관계만 별도 항목으로 남긴다
            m = TRAILING_BASIS_RE.search(h["text"]) if next_is_table else None
            if m and h["text"][:m.start(1)].strip():
                pending_basis = self._basis_item(m.group(1), n, p, [x["text"] for x in stack], emit=False,
                                                 split_from=h["heading_id"], origin="번호 제목 끝")
            return h

        def handle_table(node, p, path, gap):
            """본표 하나를 문맥에 올린다(기준 연결, 이어짐 연결, 주석 속 표 판정)."""
            nonlocal cur, note_mode, pending_basis, open_basis, cont_pending, at_top, prev_note, prev_item
            tb = self._table(node, p, path, gap, None)
            page_last_bottom[p] = min(page_last_bottom.get(p, 1e9), tb["bbox_native"][1])
            tb["basis"] = pending_basis
            if pending_basis is not None:
                pending_basis.setdefault("candidate_tables", []).append(tb["table_id"])
                open_basis = pending_basis
            elif open_basis is not None and not (cur is not None and note_mode):
                open_basis["candidate_tables"].append(tb["table_id"])    # 같은 기준 뒤에 이어지는 다른 본표
            pending_basis = None
            if cont_pending is not None and at_top and cont_pending["page"] == p - 1 and not tb["nested_in"]:
                self._link_continuation(cont_pending, tb)
            cont_pending = None
            if cur is not None and note_mode:
                tb["note_table_of"] = cur["table_id"]
                tb["role"] = "note_table"
            else:
                cur, note_mode = tb, False
            at_top, prev_note, prev_item = False, None, ("table", tb)
            return tb

        def skip_top(n, text, reason):
            """변경(본문 완전성): 맨 위 단계에서 본문으로 내보내지 않는 글(기존 규칙 그대로)을 사유와 함께 기록만 한다."""
            self.skipped_text.append({"odl_id": n["id"], "page": n.get("page number"), "bbox": bbox_of(n), "text": text,
                                      "odl_type": n.get("type"), "container_odl_ids": [], "reason": reason,
                                      "level": "맨 위(하위 글 포함)"})

        def no_table(nt):
            raise ValueError(f"이 위치의 표를 처리하는 기존 규칙이 없음(odl {nt.get('id')})")

        def read_nested(node, anc, p, path, complete, on_table, chain=None, state=None):
            """변경(본문 완전성): 목록 항목·글 상자 안의 하위 글(문단·하위 목록·글 상자)을 원문 순서대로 읽는다.

            기존에는 맨 위 항목과 맨 위 목록의 직속 항목 글만 읽어 이 글들이 빠졌다.
            표는 기존 규칙(on_table) 그대로 만든다. 하위 글은 문맥 상태(열린 표·주석 구간·기준 대기·쪽 첫머리)를
            바꾸지 않고, 소속은 원시 출력의 상위 항목으로만 기록한다(가까운 표에 붙이지 않는다).
            """
            chain = (chain or []) + [node["id"]]
            state = state if state is not None else {"after_table": None}
            for k in ("kids", "list items"):
                for ch in node.get(k) or []:
                    if ch.get("type") == "table":
                        state["after_table"] = on_table(ch)["table_id"]
                        continue
                    if ch.get("type") == "image":
                        continue
                    tx = (ch.get("content") if isinstance(ch.get("content"), str) else "").strip()
                    ref = (nested_text(ch, tx, anc, p, path, complete, chain, state) if tx else None) or anc
                    read_nested(ch, ref, p, path, complete, on_table, chain, state)

        def nested_text(ch, tx, anc, p, path, complete, chain, state):
            b = bbox_of(ch)
            base = {"odl_id": ch["id"], "page": p, "bbox": b, "text": tx, "odl_type": ch.get("type"),
                    "container_odl_ids": chain}
            # 맨 위 단계와 같은 쪽 머리·바닥 띠 규칙(부문 표기·쪽 번호·띠 안 짧은 글)
            if b and ch.get("type") != "heading" and (b[1] <= 75 or b[3] >= self.page_top[p] - 12):
                reason = ("쪽 머리·바닥 띠의 부문 표기" if re.search(r"\S+부문", tx) and len(tx) < 15 else
                          "쪽 머리·바닥 띠의 쪽 번호" if re.fullmatch(r"\d{1,4}", tx) else
                          "쪽 바닥 띠의 짧은 글" if b[1] <= 75 and len(tx) < 30 else None)
                if reason:
                    self.skipped_text.append({**base, "reason": reason})
                    return None
            if re.fullmatch(r"[→⇒>]+", tx):
                self.skipped_text.append({**base, "reason": "이어짐 표시(→). 하위 글 안에 있어 표 이어짐 연결에는 쓰지 않음"})
                return None
            # 부모 항목과 같은 원문: 글 위치의 중심이 부모 영역 안이고 글자가 부모 글에 들어 있을 때만 같은 원문으로 본다
            if anc and anc[2] and b and anc[3]:
                ab, cx, cy = anc[2], (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                if ab[0] <= cx <= ab[2] and ab[1] <= cy <= ab[3] and re.sub(r"\s+", "", tx) in re.sub(r"\s+", "", anc[3]):
                    self.skipped_text.append({**base, "reason": "부모 항목 글과 같은 원문(위치와 글자가 부모에 포함)",
                                              "parent": anc[1]})
                    return None
            note_id = self._id("n", p, ch["id"])
            if anc:
                scope = {"kind": "list_child", "owner": anc[1], "owner_kind": anc[0], "path": path,
                         "status": "구조 근거(원시 출력에서 이 항목의 하위 글. 원문 대조 확정 아님)"}
            else:
                scope = {"kind": "unassigned_body", "owner": None, "path": path,
                         "status": "미확정(글 상자 또는 글 없는 목록 항목 안의 글. 소속 표·항목을 정하지 않음)"}
            self.notes.append({
                "note_id": note_id, "order": self._next(), "page": p, "odl_id": ch["id"], "bbox": b,
                "text": tx, "marker": marker_of(tx), "scope": scope, "path": path,
                "path_status": "완전" if complete else "일부(상위 제목이 이 쪽 출력에 없음)", "continues": None,
                "nesting": {"read": "하위 글(목록 항목·글 상자 안)", "odl_type": ch.get("type"),
                            "container_odl_ids": chain, "depth": len(chain),
                            "after_table_in_item": state["after_table"]},
            })
            return ("note", note_id, b, tx)

        for idx, n in enumerate(kids):
            p, t = n.get("page number"), n.get("type")
            if p != last_page:
                contiguous = last_page is not None and p == last_page + 1
                # 부문 경계: 두 쪽의 부문을 모두 알고 서로 다를 때만 문맥을 끝낸다(부문을 모르는 쪽은 경계로 보지 않는다)
                d_prev, d_now = self.divisions.get(last_page), self.divisions.get(p)
                div_changed = bool(contiguous and d_prev and d_now and d_prev != d_now)
                if not contiguous or div_changed:
                    if last_page is not None:
                        self.boundaries.append({"from_page": last_page, "to_page": p,
                                                "reason": "부문이 바뀜" if div_changed else "연속하지 않은 쪽",
                                                "ended": [h["text"] for h in stack]})
                    stack, gap, cur, note_mode, pending_basis, intro_owner = [], True, None, False, None, None
                    cont_pending, prev_note, prev_item = None, None, None
                else:
                    gap = False
                last_page, at_top = p, True
            content = n.get("content") if isinstance(n.get("content"), str) else None
            b = bbox_of(n)
            top = self.page_top[p]
            if t == "image":
                continue
            # 쪽 머리·바닥 띠: 부문 표기와 인쇄 쪽 번호
            if b and t != "heading" and (b[1] <= 75 or b[3] >= top - 12):
                txt = content or " ".join(x["content"] for x in paras(n))
                if txt and re.search(r"\S+부문", txt) and len(txt) < 15:
                    self.part_marks[p] = txt.strip()
                    skip_top(n, txt, "쪽 머리·바닥 띠의 부문 표기")
                    continue
                if content and re.fullmatch(r"\d{1,4}", content.strip()):
                    self.printed_page[p] = int(content)
                    skip_top(n, content, "쪽 머리·바닥 띠의 쪽 번호")
                    continue
                if txt and b[1] <= 75 and len(txt) < 30:
                    skip_top(n, txt, "쪽 바닥 띠의 짧은 글")
                    continue
            if t in ARROW_TYPES and content and re.fullmatch(r"[→⇒>]+", content.strip()):
                # '→'는 제목이나 주석이 아니라 '표가 다음 쪽으로 이어짐' 표시다(ODL이 제목·caption으로 내기도 한다)
                skip_top(n, content, "이어짐 표시(→). 표 이어짐 연결에 사용" if cur is not None else "이어짐 표시(→). 열린 표 없음")
                if cur is not None:
                    cur["continues_next_page"] = {"odl_id": n["id"], "bbox": b, "page": p}
                    cont_pending = cur
                continue
            next_is_table = (idx + 1 < len(kids) and kids[idx + 1].get("type") == "table"
                             and kids[idx + 1].get("page number") == p)
            if t == "heading":
                push_heading(n, n.get("heading level", 9), content, p, b, False, next_is_table)
                continue
            path = [x["text"] for x in stack]
            complete = bool(stack and re.match(r"제\d+장", stack[0]["text"]))
            self._ps = "완전(장 제목부터)" if complete else "일부(상위 제목이 이 쪽 출력에 없음)"
            if t == "table":
                handle_table(n, p, path, gap)
                continue
            items = n.get("list items") if t == "list" else None
            units = [(x, x.get("content")) for x in items] if items else [(n, content)]
            for ui, (src, text) in enumerate(units):
                tx = (text or "").strip()
                note_id = None
                last_unit = ui == len(units) - 1
                before_table = next_is_table and last_unit
                inner_tables = [nt for nt, depth in ot.find_tables(src) if depth == 0] if items else []
                if tx and (before_table or inner_tables) and ITEM_TITLE_RE.fullmatch(tx):
                    # 표 바로 앞(또는 표를 품은 목록 항목)의 품목 코드 제목은 새 표의 제목이다. 앞 표의 주석이 아니다
                    h = push_heading(src, 1, tx, p, bbox_of(src), True, next_is_table)
                    path = [x["text"] for x in stack]
                    # 변경(본문 완전성): 표는 기존과 같은 handle_table로, 하위 글은 원문 순서대로 읽는다
                    read_nested(src, ("heading", h["heading_id"], h["bbox"], tx), p, path, complete,
                                lambda nt: handle_table(nt, p, path, gap))
                    continue
                if tx:
                    if BASIS_RE.fullmatch(tx) and (cur is None or not note_mode or before_table):
                        # 표 바로 앞에 따로 인쇄된 기준. 주석 구간이어도 곧바로 표가 오면 새 표의 기준이다
                        pending_basis = self._basis_item(tx, src, p, path, emit=True, origin="따로 인쇄된 줄")
                        open_basis = None
                        if prev_item and prev_item[0] == "note" and looks_like_subheading(prev_item[1]["text"]):
                            prev_item[1]["role_hint"] = "unnumbered_subheading"
                            pending_basis["after_subheading"] = prev_item[1]["note_id"]
                        if before_table:
                            cur, note_mode = None, False
                        prev_item, at_top = ("basis", pending_basis), False
                        read_nested(src, ("basis", pending_basis["basis_id"], bbox_of(src), tx), p, path, complete, no_table)
                        continue
                    owner = cur["table_id"] if cur is not None else None
                    cross = cur is not None and cur["page"] != p
                    scope_extra = {}
                    if owner:
                        note_mode = True
                    # 쪽 첫머리(제목·표보다 앞)에 [주]·①이 나오면 앞 쪽 표의 이어진 주석이다
                    orphan = (owner is None and not any(h["page"] == p for h in self.headings)
                              and not any(x["page"] == p for x in self.tables)
                              and re.match(r"^(\[주\]|[①-⑳㉮-㉳])", tx) is not None)
                    status = "위치 근거(표 아래·다음 제목 전)"
                    if cross:
                        # 변경: 쪽 경계를 건너는 연결은 근거를 남기고, 새 주석 목록이 시작되면 잇지 않는다
                        own_tail = [x for x in self.notes if x["scope"].get("owner") == owner]
                        evid = ["앞 쪽 마지막 표 뒤", "사이에 제목·다른 표 없음"]
                        evid.append("다음 쪽 첫머리" if at_top else "다음 쪽 첫머리가 아님")
                        near_bottom = page_last_bottom.get(cur["page"], 1e9) <= BOTTOM_RATIO * self.page_top[cur["page"]]
                        evid.append("앞 쪽이 이 표(또는 그 주석)로 끝남" if near_bottom else "앞 쪽의 마지막 내용이 쪽 맨 아래가 아님")
                        if NOTE_START_RE.match(tx) and own_tail:
                            # 앞 표에 이미 주석 목록이 있는데 ①부터 다시 시작하면 새 주석 목록이다. 앞 표에 잇지 않는다
                            owner = None
                            orphan = True
                            status = "미확정(앞 표에는 이미 주석이 있어 새 주석 목록으로 보임)"
                            cur, note_mode = None, False
                        else:
                            mk = marker_of(tx)
                            if mk:
                                evid.append(f"주석 표지 {mk}")
                            last_mark = next((x["marker"] for x in reversed(own_tail) if x["marker"] and x["marker"][-1] in CIRCLED), None)
                            if mk and last_mark and mk[-1] in CIRCLED and CIRCLED.index(mk[-1]) == CIRCLED.index(last_mark[-1]) + 1:
                                evid.append(f"번호가 이어짐({last_mark[-1]} 다음 {mk[-1]})")
                            status = ("위치 근거(쪽 경계 건너 연결)" if near_bottom else
                                      "위치 근거(쪽 경계 건너 연결); 앞 쪽이 쪽 맨 아래에서 끝나지 않아 확신 낮음")
                            scope_extra = {"cross_page": True, "owner_page": cur["page"], "evidence": evid}
                    note_id = self._id("n", p, src["id"])
                    cont_of = None
                    if (prev_note is not None and prev_note["page"] == p - 1 and not marker_of(tx)
                            and not sentence_complete(prev_note["text"]) and at_top and owner is not None):
                        cont_of = prev_note["note_id"]            # 문장이 쪽을 건너 이어짐
                    note = {
                        "note_id": note_id, "order": self._next(), "page": p, "odl_id": src["id"], "bbox": bbox_of(src),
                        "text": tx, "marker": marker_of(tx),
                        "scope": ({"kind": "table_tail", "owner": owner, "status": status, **scope_extra}
                                  if owner else {"kind": "orphan_tail", "owner": None, "path": path,
                                                 "status": status if status.startswith("미확정") else
                                                 "미확정(앞 쪽에서 이어진 주석·항목으로 보임. 소속 표·절이 이 출력에 없음)"}
                                  if orphan else {"kind": "section_intro", "owner": intro_owner and intro_owner["text"],
                                                  "path": path, "status": "미확정(상위 절 전체. '본 품'이 가리키는 범위는 문장만으로 불명)"}),
                        "path": path,
                        "path_status": "완전" if complete else "일부(상위 제목이 이 쪽 출력에 없음)",
                        "continues": cont_of,
                    }
                    if src.get("_correction"):
                        note["correction"] = src["_correction"]
                    if cont_of:
                        prev_note["continued_by"] = note_id
                    self.notes.append(note)
                    page_last_bottom[p] = min(page_last_bottom.get(p, 1e9), note["bbox"][1]) if note["bbox"] else page_last_bottom.get(p, 1e9)
                    prev_note, prev_item = note, ("note", note)
                    # 쪽 첫머리 구간은 앞 쪽에서 이어진 주석이 계속되는 동안만 이어진다
                    at_top = at_top and (bool(scope_extra.get("cross_page")) or orphan)
                    # 글 끝에 붙은 기준: 원래 글은 그대로 두고 기준만 별도 항목으로 분리한다
                    m = TRAILING_BASIS_RE.search(tx) if before_table else None
                    if m and tx[:m.start(1)].strip():
                        pending_basis = self._basis_item(m.group(1), src, p, path, emit=True, split_from=note_id,
                                                         origin="글 끝에 붙은 기준(원래 글에서 분리)")
                        if looks_like_subheading(tx[:m.start(1)]):
                            note["role_hint"] = "unnumbered_subheading"
                            pending_basis["after_subheading"] = note_id
                        cur, note_mode = None, False
                # 목록 항목 안에 든 표는 그 항목(주석) 소속 표로 둔다
                def sub_table(nt, note_id=note_id):
                    sub = self._table(nt, p, path, gap, None)
                    sub["role"], sub["note_table_of_note"] = "note_table", note_id
                    sub["note_table_of"] = cur["table_id"] if cur else None
                    return sub
                # 변경(본문 완전성): 항목 안의 표는 기존 규칙 그대로 만들고, 그 사이의 하위 글도 원문 순서대로 읽는다
                anc = ("note", note_id, bbox_of(src), tx) if note_id else None
                read_nested(src, anc, p, path, complete, sub_table if items else no_table)
        self._drop_table_region_text()
        for tb in self.tables:
            tb["printed_page"] = self.printed_page.get(tb["page"])
            tb["part_mark"] = self.part_marks.get(tb["page"])
        last = kids[-1] if kids else None
        self.context_out = {
            "run": self.run, "last_page": last.get("page number") if last else None,
            "division": self.divisions.get(last.get("page number")) if last else None,
            "stack": [{k: h[k] for k in ("level", "text", "odl_id", "page")} for h in stack],
            "open_table": cur["table_id"] if cur else None, "note_mode": note_mode,
            "open_continuation": ({"table_id": cont_pending["table_id"], "page": cont_pending["page"]}
                                  if cont_pending is not None else None),
            "pending_basis": pending_basis["basis_id"] if pending_basis else None,
            "note": "구간을 나눠 처리할 때 다음 구간이 이어받아야 하는 상태(제목 경로·열린 표와 그 주석·이어짐 대기·"
                    "대기 중인 기준). 이번 구현은 이 상태를 기록만 하고 이어받아 처리하는 기능은 없다",
        }

    def _drop_table_region_text(self):
        """변경(본문 완전성): 새로 읽은 하위 글이 표 영역 안에 있고 줄마다 그 표 칸 글에 들어 있으면 이미 표로 전달된 글이다.

        원문 글자로 다시 짠 표(68쪽)나 괄호 그림 표(443·523쪽)는 원시 출력에서 표 밖 글이던 것을 칸으로 옮겼다.
        표 영역 안이지만 칸에서 찾지 못하면 본문으로 남기고 미확정 표시를 단다.
        """
        def overlap(a, t):
            w, h = min(a[2], t[2]) - max(a[0], t[0]), min(a[3], t[3]) - max(a[1], t[1])
            return w * h / max(1e-6, (a[2] - a[0]) * (a[3] - a[1])) if w > 0 and h > 0 else 0

        keep, removed = [], set()
        for n in self.notes:
            hit = None
            if n.get("nesting") and n["bbox"]:
                hit = next((t for t in self.tables if t["page"] == n["page"] and overlap(n["bbox"], t["bbox_native"]) > 0.5), None)
            if hit is None:
                keep.append(n)
                continue
            cells = re.sub(r"\s+", "", "".join(c["text_raw"] for c in hit["cells"]))
            lines = [re.sub(r"\s+", "", x) for x in n["text"].split("\n") if x.strip()]
            if all(x in cells for x in lines):
                removed.add(n["note_id"])
                self.skipped_text.append({"odl_id": n["odl_id"], "page": n["page"], "bbox": n["bbox"], "text": n["text"],
                                          "odl_type": n["nesting"]["odl_type"],
                                          "container_odl_ids": n["nesting"]["container_odl_ids"],
                                          "reason": "이미 표 칸으로 전달(표 영역 안이고 줄마다 그 표 칸 글에 있음)",
                                          "table_id": hit["table_id"]})
                continue
            n["table_region"] = {"table_id": hit["table_id"], "status": "미확정(표 영역 안 글이지만 표 칸에서 찾지 못함)"}
            keep.append(n)
        if any(n["scope"].get("owner") in removed for n in keep):
            raise ValueError("표로 전달되어 뺀 글을 상위 항목으로 둔 하위 글이 있음")
        self.notes = keep

    def _basis_item(self, text, src, page, path, *, emit, origin, split_from=None) -> dict:
        b = {"basis_id": self._id("b", page, src["id"]) + (":tail" if split_from else ""), "order": self._next(),
             "text": text, "odl_id": src["id"], "page": page, "bbox": bbox_of(src), "path": path,
             "emit_record": emit, "origin": origin, "split_from": split_from, "candidate_tables": []}
        self.basis.append(b)
        return b

    def _link_continuation(self, prev_tb: dict, tb: dict) -> None:
        """이어짐 표시(→)가 있는 표와 다음 쪽 첫머리 표를 논리 표로 잇는다. 원래 표 조각은 각자 남긴다."""
        evid = ["이어짐 표시(→) 있음", "다음 쪽 첫머리의 첫 표", "사이에 제목 없음"]
        same_cols = prev_tb["n_cols"] == tb["n_cols"]
        evid.append("열 수 일치" if same_cols else f"열 수 다름({prev_tb['n_cols']}→{tb['n_cols']})")
        # 이어지는 쪽이 머리글을 되풀이하면(열 이름이 글자까지 같으면) 같은 표일 가능성이 더 높다
        if same_cols and prev_tb.get("col_path") and prev_tb["col_path"] == tb.get("col_path"):
            evid.append("머리글 글자가 앞 쪽과 같음(머리글 반복)")
        self.logical_tables.append({
            "logical_id": f"{self.run}-lt{len(self.logical_tables)}",
            "parts": [prev_tb["table_id"], tb["table_id"]], "evidence": evid,
            "status": "표시·위치 근거(확정 아님)" if same_cols else "후보(열 수가 다름)",
            "confirmed": False,
        })
        prev_tb["continues_next_page"]["target"] = tb["table_id"]
        tb["continues_from"] = prev_tb["table_id"]

    # ---------------- 표 ----------------
    def _table(self, node, page, path, gap, parent):
        H = self.page_top[page]
        nested = parent is not None
        regridded = bool(node.get("_regrid"))
        # 변경: 원문 글자 위치로 다시 짠 표는 이미 줄 단위 행이라 행 분리 어댑터를 다시 쓰지 않는다
        common = ot.to_common(node, H, nested=nested, split_rows=not regridded, probe=self.probe,
                              height_source=self.page_height_source)
        if regridded:
            common["line_regrid"] = True
        override = node.get("_header_override")
        if override is None and regridded:
            override = node["_regrid"]["config"].get("header_rows")
        if override is not None:
            common["header_override"] = override
        tid = self._id("t", page, node["id"])
        raw = {c["id"]: c for row in node.get("rows") or [] for c in row.get("cells") or []}
        cells, flags, nested_nodes = [], [], []
        for i, cm in enumerate(common["cells"]):
            oc = cm["odl_cell"]
            rc = raw.get(oc["id"])
            has_nested = bool(rc) and bool(ot.find_tables(rc))
            own = "\n".join(x["content"] for x in paras(rc)) if rc is not None else cm["text"]
            text_raw = own if has_nested else cm["text"]
            native = oc["bbox_native"]
            sp = cm.get("split")
            is_piece = bool(sp) and sp["role"] == "piece"
            cell = {
                "cell_id": f"{tid}:c{i}", "r0": cm["r0"], "r1": cm["r1"], "c0": cm["c0"], "c1": cm["c1"],
                "text_raw": text_raw, "label": squash(text_raw),
                "src": {"odl_id": oc["id"], "odl_row": oc["row"], "odl_col": oc["col"],
                        "odl_row_span": oc["row_span"], "odl_col_span": oc["col_span"], "bbox": native},
                "split": sp,
                "split_piece": is_piece,
                "split_basis": (f"행 분리 기록(odl_tables.split_row: {sp['basis']}, 위치 {sp['coord_kind']}, "
                                f"{'확정' if sp['confirmed'] else '미확정'})" if is_piece else None),
                "coord_basis": "ODL 칸 좌표(실제)",
                "line_position_basis": ((("PDF 글자 기준선(실제)" if sp["coord_kind"] == "pdf_baseline"
                                          else "추정(문단 높이를 줄 수로 나눈 위치, 실제 글자 좌표 아님)")) if is_piece else None),
                "has_nested_table": has_nested,
                "paras": [{"odl_id": x["id"], "text": x["content"], "bbox": bbox_of(x)} for x in paras(rc)] if rc else [],
            }
            if rc and rc.get("_correction"):
                cell["correction"] = rc["_correction"]
            if rc and rc.get("_source_kind"):
                cell["coord_basis"] = "PDF 칸 좌표(PyMuPDF 보충)"
                cell["src"]["source_kind"] = rc["_source_kind"]
            if rc and rc.get('_regrid'):
                cell['source_review'] = rc['_regrid']
                cell['coord_basis'] = 'PDF 실제 글자 위치와 원문 대조 행 구조'
                cell['src']['original_odl_ids'] = rc['_regrid'].get('orig_ids', [rc['_regrid']['orig_id']])
            if rc is not None:
                for k in paras(rc):
                    kb = k.get("bounding box")
                    cb = native
                    if kb and (kb[2] > cb[2] + 1 or kb[0] < cb[0] - 1):
                        flags.append({"cell_id": cell["cell_id"], "code": "칸 경계 넘음",
                                      "detail": f"글 좌표 x {kb[0]:.0f}~{kb[2]:.0f}가 칸 x {cb[0]:.0f}~{cb[2]:.0f}를 벗어남",
                                      "text": k.get("content")})
            if re.fullmatch(r"\.\d+|\d+\.", cell["label"]):
                flags.append({"cell_id": cell["cell_id"], "code": "숫자 형식 의심", "detail": f"'{cell['label']}'", "text": cell["label"]})
            cells.append(cell)
            if has_nested:
                nested_nodes.append((cell, rc))
        tb = {"table_id": tid, "run": self.run, "order": self._next(), "common": common,
              "page": page, "odl_id": node["id"], "bbox_native": bbox_of(node), "bbox_pt": common["bbox_pt"],
              "bbox_origin": "왼쪽 아래(PDF 점)", "coord": common["coord"],
              "section_path": path, "path_status": self._ps, "context_gap": gap,
              "role": "nested" if nested else "table", "nested_in": parent,
              "n_rows": common["n_rows"], "n_cols": common["n_cols"], "rows_split": common["rows_split"],
              "row_splits": common["row_splits"], "row_map": common["row_map"],
              "odl_rows": node["number of rows"], "cells": cells, "flags": flags, "basis": None}
        self.tables.append(tb)
        if node.get("_source_kind"):
            tb["extractor"] = node["_source_kind"]
            tb["bbox_origin"] = "PDF 칸 좌표를 왼쪽 아래 원점으로 변환"
            tb["coord"]["native_origin"] = "PDF 칸 좌표를 왼쪽 아래 원점으로 변환"
        if node.get("_correction"):
            tb["correction"] = node["_correction"]
        if node.get('_reviewed'):
            tb['source_review'] = node['_reviewed']
            if node['_reviewed'].get('hold'):
                tb['flags'].append({'cell_id':None, 'text':'', **node['_reviewed']['hold']})
        if node.get('_graphic'):
            tb['graphic_source']={k:v for k,v in node['_graphic'].items() if k!='cells'}
            mapped={x['odl_id']:x for x in node['_graphic']['cells']}
            for cell in cells:
                item=mapped.pop(cell['src']['odl_id'],None)
                if item is None:continue
                if item['expected_text']!=cell['text_raw']:raise ValueError('계단선 숫자 칸의 원문 불일치')
                cell['graphic_conditions']=item
            if mapped:raise ValueError('계단선 조건에 연결할 숫자 칸이 없음')
        tb["shades"] = self.probe.shades(page) if self.probe is not None else []
        prev = getattr(self, "_code_prev", None)
        if (prev and not nested and prev.get("continues_next_page") and prev["page"] == page - 1
                and prev["section_path"] == path and prev.get("_code_last_prefix")):
            tb["_code_context"] = {"prefix": prev["_code_last_prefix"], "table_id": prev["table_id"],
                                   "code": prev["_code_last_prefix"]}
        self._analyze(tb)
        if not nested:
            self._code_prev = tb
        for cell, rc in nested_nodes:
            for nt, depth in ot.find_tables(rc):
                if depth == 0:
                    sub = self._table(nt, page, path, gap, {"table_id": tid, "cell_id": cell["cell_id"]})
                    cell.setdefault("nested_table_ids", []).append(sub["table_id"])
        return tb

    # ---------------- 표 해석(머리글·행·묶음) ----------------
    def _analyze(self, tb):
        n_r, n_c = tb["n_rows"], tb["n_cols"]
        cov = [[None] * n_c for _ in range(n_r)]
        for i, c in enumerate(tb["cells"]):
            for r in range(c["r0"], c["r1"]):
                for k in range(c["c0"], c["c1"]):
                    cov[r][k] = i
        tb["cover"] = cov

        def numeric(c):
            ls = [l.strip() for l in c["text_raw"].split("\n") if l.strip()]
            return bool(ls) and all(VALUE_RE.match(re.sub(r"\s+", "", l)) for l in ls) and any(re.search(r"\d", l) for l in ls)

        tb["_numeric"] = {c["cell_id"] for c in tb["cells"] if numeric(c)}
        # 변경: 머리글은 조립과 같은 판정(음영 → 숫자 규칙 → 첫 줄 가정)을 쓴다
        hdr, hdr_basis = assemble.header_of(tb["common"], tb["shades"])
        tb["header_rows"], tb["header_basis"] = hdr, hdr_basis
        first_num = n_c
        for k in range(n_c):
            if any(cov[r][k] is not None and tb["cells"][cov[r][k]]["cell_id"] in tb["_numeric"] for r in range(hdr, n_r)):
                first_num = k
                break
        tb["label_cols"] = list(range(max(first_num, 1)))     # 첫 열은 값이 숫자여도 행 구분 열이다(두께 16·18 …)
        paths = []
        for k in range(n_c):
            seen, p = [], []
            for r in range(hdr):
                i = cov[r][k]
                if i is not None and i not in seen:
                    seen.append(i)
                    if tb["cells"][i]["label"]:
                        p.append(tb["cells"][i]["label"])
            paths.append(p)
        tb["col_path"] = paths
        analyze_cell_semantics(tb)
        rows = []
        for r in range(hdr, n_r):
            labels, seen = [], []
            for k in tb["label_cols"]:
                i = cov[r][k]
                if i is not None and i not in seen:
                    seen.append(i)
                    if tb["cells"][i]["label"]:
                        labels.append(cell_display(tb["cells"][i]))
            rows.append({"row": r, "labels": labels})
        tb["body_rows"] = rows

        parent = list(range(n_r))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        shared = [c["cell_id"] for c in tb["cells"]
                  if c["r1"] - c["r0"] > 1 and c["r0"] >= hdr and c["cell_id"] in tb["_numeric"]]
        for c in tb["cells"]:
            if c["r1"] - c["r0"] > 1 and c["r0"] >= hdr and (c["cell_id"] in tb["_numeric"] or c["c0"] == 0):
                for r in range(c["r0"] + 1, c["r1"]):
                    parent[find(r)] = find(c["r0"])
        groups = {}
        for r in range(hdr, n_r):
            groups.setdefault(find(r), []).append(r)
        gl = [sorted(g) for g in groups.values()]
        gl.sort(key=lambda g: g[0])
        if n_r - hdr > SMALL_TABLE_ROWS:
            for k in range(1, len(tb["label_cols"])):
                if all(len(x) <= MAX_GROUP_ROWS for x in gl):
                    break
                nxt = []
                for x in gl:
                    if len(x) <= MAX_GROUP_ROWS:
                        nxt.append(x)
                        continue
                    cur, key = [], None
                    for r in x:
                        i = cov[r][k]
                        if key is not None and i != key:
                            nxt.append(cur)
                            cur = []
                        cur.append(r)
                        key = i
                    nxt.append(cur)
                gl = nxt
        out = []
        for g in gl:
            glabels, seen = [], []
            for k in tb["label_cols"]:
                i = cov[g[0]][k]
                c = tb["cells"][i] if i is not None else None
                if c and i not in seen and c["r0"] <= g[0] and c["r1"] > g[-1] and c["label"]:
                    seen.append(i)
                    glabels.append(cell_display(c))
            # 묶음 전체를 덮는 라벨이 없으면(한 줄짜리) 라벨 열 전체를 경로로 쓴다
            if not glabels:
                glabels = rows[g[0] - hdr]["labels"]
            remark = len(g) == 1 and rows[g[0] - hdr]["labels"][:1] == ["비고"]
            out.append({"rows": g, "group_label": glabels, "kind": "remark" if remark else "data",
                        "row_labels": [rows[r - hdr]["labels"] for r in g]})
        tb["groups"] = out
        tb["shared_cells"] = shared
        # 열 단위: 머리글 괄호 안 표기('시공량(㎥)' -> ㎥). 없으면 None(단위 미확정)
        tb["col_units"] = [(re.findall(r"\(([^()]+)\)", " ".join(p)) or [None])[-1] for p in paths]
        # 변경: 어댑터가 쌓였다고 표시했으나 나누지 못한 본문 행은 행 대응 미확정으로 남긴다(머리글 행은 제외)
        # 변경: 원문 대조로 확정한 행 연결은 해당 행의 행 대응 보류를 만들지 않는다. 판정 밖 보류는 그대로 남긴다
        entry = self.row_mappings.pop(tb["table_id"], None)
        if entry is not None:
            import source_corrections
            tb["flags"] += source_corrections.confirm_rows(tb, entry)
        if self.completeness is not None:
            import source_corrections
            extra = source_corrections.apply_completeness(tb, self.completeness)
            if extra or any(f["table_id"] == tb["table_id"] for f in self.completeness["fractions"]):
                self._completeness_seen.add(tb["table_id"])
            resolved=set(tb.get('source_review',{}).get('resolved_holds',[]))
            tb["flags"] += [f for f in extra if f['code'] not in resolved]
        seen_rows = set()
        for g_row, m in enumerate(tb["row_map"]):
            if g_row < hdr or m["state"] != "stacked_unsplit" or m["odl_row"] in seen_rows:
                continue
            seen_rows.add(m["odl_row"])
            cs = [c for c in tb["cells"] if c["r0"] == g_row and not c["has_nested_table"]
                  and len([l for l in c["text_raw"].split("\n") if l.strip()]) >= 2]
            if not cs:
                continue
            lines = [[l for l in c["text_raw"].split("\n") if l.strip()] for c in cs]
            same = len({len(x) for x in lines}) == 1
            cand = [[ln[i] for ln in lines] for i in range(len(lines[0]))] if same else None
            geo = {True: "PDF 기준선 일치", False: "PDF 기준선 불일치", None: "확인 불가"}[m.get("aligned")]
            tb["flags"].append({"cell_id": cs[0]["cell_id"], "cell_ids": [c["cell_id"] for c in cs], "code": "행 대응 확인 필요",
                                "severity": "alignment",
                                "detail": f"ODL {m['odl_row']}행에 줄이 쌓인 칸 {len(cs)}개. 행 분리 어댑터가 나누지 못함"
                                          f"({m.get('reason')}). 줄 위치 {geo}",
                                "candidate_rows": cand, "pdf_aligned": m.get("aligned"),
                                "text": " / ".join(c["text_raw"].replace("\n", "·") for c in cs)[:100]})
        if hdr_basis in HEADER_ASSUMED:
            tb["flags"].append({"cell_id": tb["cells"][0]["cell_id"] if tb["cells"] else None, "code": "머리글 가정",
                                "severity": "header",
                                "detail": f"음영과 숫자 규칙으로 머리글을 정하지 못해 {hdr}행을 머리글로 가정({hdr_basis})",
                                "text": ""})
        for f in tb["flags"]:
            f.setdefault("severity", "value")
        if any(f["severity"] == "value" for f in tb["flags"]):
            tb["calc_status"] = "보류(값 훼손 의심)"
        elif any(f["severity"] == "alignment" for f in tb["flags"]):
            tb["calc_status"] = "행 대응 확인 필요(후보 정렬만 있음)"
        elif any(f["severity"] == "formula" for f in tb["flags"]):
            tb["calc_status"] = "보류(식 표기 확인 필요)"
        elif any(f["severity"] == "graphic" for f in tb["flags"]):
            tb["calc_status"] = "보류(원문 그림 표지 미반영)"
        elif any(f["severity"] == "semantic" for f in tb["flags"]):
            tb["calc_status"] = "보류(이름·코드 연결 미확정)"
        elif tb["flags"]:
            tb["calc_status"] = "머리글 가정(계산 사용 보류)"
        else:
            tb["calc_status"] = "구조 표지 없음(값 검증은 별도)"
        tb["calc_reason"] = [f"{f['code']}: {f['detail']} ({f['cell_id']})" for f in tb["flags"]]


def load_store(json_path, pages: list[int] | None = None, *, corrections=None, row_mappings=None, completeness=None, reviewed_tables=None,
               diagram_tables=None, **kwargs) -> Store:
    doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    audit = []
    comp = None
    if completeness is not None:
        if corrections is None or kwargs.get("probe") is None:
            raise ValueError("누락 보완 교정에는 칸 교정 자료와 원문 PDF가 필요합니다.")
        import source_corrections
        comp = source_corrections.load_completeness(completeness, json_path, kwargs["probe"].path, corrections)
        kwargs["completeness"] = comp
    if row_mappings is not None:
        if corrections is None or kwargs.get("probe") is None:
            raise ValueError("행 연결 교정에는 칸 교정 자료와 원문 PDF가 필요합니다.")
        import source_corrections
        kwargs["row_mappings"] = source_corrections.load_row_mappings(row_mappings, json_path, kwargs["probe"].path, corrections)
    if corrections is not None:
        if kwargs.get("probe") is None:
            raise ValueError("교정 자료 적용에는 원문 PDF 위치 확인이 필요합니다.")
        import source_corrections
        doc, audit = source_corrections.apply(doc, json_path, kwargs["probe"].path, corrections, comp)
    if reviewed_tables is not None:
        import reviewed_tables as rt
        doc, review_audit = rt.apply(doc, reviewed_tables, json_path, kwargs['probe'].path, corrections, completeness, row_mappings)
        if diagram_tables is not None:
            # 변경: 괄호 그림 표 교정(443·523쪽). reviewed_tables 결과 위에만 적용
            import diagram_tables as dt
            doc, diagram_audit = dt.apply(doc, diagram_tables, json_path, kwargs['probe'].path, reviewed_tables)
            review_audit = review_audit + diagram_audit
    else:
        review_audit = []
    store = Store(doc, pages, **kwargs)
    store.review_audit = review_audit
    if store.row_mappings:
        raise ValueError(f"행 연결 교정 대상 표를 찾지 못함: {sorted(store.row_mappings)}")
    if comp is not None and pages is None:
        want = {x["table_id"] for x in comp["fractions"] + comp["holds"]}
        if want - store._completeness_seen:
            raise ValueError(f"누락 보완 교정 대상 표를 찾지 못함: {sorted(want - store._completeness_seen)}")
        recovered = {t["correction"]["target"] for t in store.tables if (t.get("correction") or {}).get("completeness")}
        if {x["target"] for x in comp["tables"]} - recovered:
            raise ValueError("누락 보완 표가 보관 결과에 없음")
    store.correction_audit = audit
    return store
