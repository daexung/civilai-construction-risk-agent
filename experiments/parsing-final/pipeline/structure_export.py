"""보관 구조(structure_store) -> 기존 청킹(chunk.make_chunks)이 받는 레코드 + 원문 연결 정보.

흐름
    structure_store.Store            원문 칸·병합·좌표·기준·주석·불확실 표시
      -> assemble.table_to_records   칸을 읽기 좋은 글 레코드로(행 분리 판정과 칸 추적을 함께 낸다)
      -> export()                    chunk.make_chunks 입력 필드 + 레코드/청크가 가리키는 원문 항목 연결
      -> chunk.make_chunks           변경 없이 호출

보관 상태 -> 청킹 structure 대응(청킹의 `uncertain`은 이 단계에서 표 레코드마다 `structure.status`로 정한다)
  보관 구조 표지                                  레코드 structure          issues 코드
  값 훼손 의심 칸(칸 경계 넘음·숫자 형식 의심)      uncertain(표 전체 레코드)  value_suspect, table_held
  행 대응 확인 필요(어댑터가 나누지 않은 쌓인 칸)   uncertain(표 전체 레코드)  row_alignment_unconfirmed
  조립 단계가 추정으로 나눈 행(value_lines 등)      uncertain(그 레코드)       row_split_unconfirmed
  머리글을 숫자 규칙으로 정하지 못함                uncertain(그 레코드)       header_fallback
  위 표지가 하나도 없음                             ok                        (없음)
  `ok`는 '구조 표지가 없다'일 뿐이며 계산 명세·값·단위 검증이나 사람 검토를 뜻하지 않는다.
  한 레코드라도 uncertain이면 chunk.make_chunks가 표 청크 전체를 uncertain으로 둔다(기존 청킹 원칙).

규칙
  - 레코드의 `text`는 읽기용이다. 원문은 보관 구조의 칸(`cell_id`)이고, 레코드는 `links`에서 칸으로 돌아간다.
  - 위치·글자 일치로 추정한 관계는 `confirmed=False`로 두고 근거 문자열을 그대로 남긴다. 확정으로 올리지 않는다.
  - 표에 값 훼손 의심 칸이 있으면 그 표의 모든 레코드에 보류 사유를 싣는다(결함 칸이 없는 행에도).
  - 구조 `ok`는 '구조 표지가 없다'일 뿐 계산 명세 승인이 아니다.
  - 값·단위·글자는 고치지 않는다.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import assemble  # noqa: E402
from parse import SECTION_RE, SUBSECTION_RE  # noqa: E402
from structure_store import BOTTOM_RATIO, ITEM_TITLE_RE, VALUE_RE  # noqa: E402

# 상위 절 제목이 이 출력에 없을 때의 표시. 쪽마다 달라야 떨어진 쪽의 소제목이 청킹에서 서로 이어지지 않는다
UNKNOWN_SECTION = "(절 제목 미확인·{page}쪽)"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
SUBMARK = "㉮㉯㉰㉱㉲㉳"
# 조립 단계가 어댑터 없이 정한 행 분리 근거. 어댑터가 확정한 분리가 아니므로 대응 확인 전까지 불확실로 둔다
ASSEMBLY_SPLIT_BASIS = ("value_lines", "shared_value", "line_count")
HEADER_ISSUES = ("header_fallback", "header_extended_numeric")

REF_PART_RE = re.compile(r"[‘'“\"]?\s*\[(?P<part>[^\[\]]+)\]\s*(?P<num>\d+(?:-\d+)+)\s*(?P<title>[^’'”\"]*?)\s*[’'”\"]")
REF_QUOTED_RE = re.compile(r"[‘'“\"]\s*(?P<num>\d+(?:-\d+)+)\s+(?P<title>[^’'”\"]+?)\s*[’'”\"]")
REF_TITLE_RE = re.compile(r"[‘'“]\s*(?P<title>\d+\.\s*[^’'”]+?)\s*[’'”]")


# ---------------- 작은 도우미 ----------------
def sha256_of(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def one_line(text: str) -> str:
    return " ".join((text or "").split())


def section_of(path: list[str], page: int) -> tuple[str, str]:
    """제목 경로 -> (레코드 section, 판정). 운영 parse.title_above와 같이 3단 절을 2단 절보다 먼저 쓴다."""
    for pattern in (SECTION_RE, SUBSECTION_RE, ITEM_TITLE_RE):
        for title in reversed(path):
            if pattern.match(title + " ") or pattern.match(title):
                return title, "절 제목 확인" if pattern is not ITEM_TITLE_RE else "품목 코드 제목"
    return UNKNOWN_SECTION.format(page=page), "상위 절 제목이 이 출력에 없음"


def find_refs(text: str) -> list[dict]:
    """주석 안의 참조 표기(‘[공통부문] 6-1-3 표면 마무리’). 시제품 evidence.find_refs와 같다. 대상은 조회하지 않는다."""
    out = []
    for m in REF_PART_RE.finditer(text):
        out.append({"part": m.group("part"), "num": m.group("num"), "title": m.group("title").strip(), "span": m.span()})
    for m in REF_QUOTED_RE.finditer(text):
        if not any(r["span"][0] <= m.start() < r["span"][1] for r in out):
            out.append({"part": None, "num": m.group("num"), "title": m.group("title").strip(), "span": m.span()})
    for m in REF_TITLE_RE.finditer(text):
        if not any(r["span"][0] <= m.start() < r["span"][1] for r in out):
            out.append({"part": None, "num": None, "title": m.group("title").strip(), "span": m.span()})
    return out


def reference_parts(text: str, span) -> tuple[str, str]:
    start = max(text.rfind(".", 0, span[0]), text.rfind("\n", 0, span[0]))
    end = text.find(".", span[1])
    sentence = text[start + 1: end + 1 if end >= 0 else len(text)].strip()
    cond = re.sub(r"^\[주\]\s*", "", text[start + 1: span[0]].strip())
    return sentence, re.sub(r"^[①-⑳㉮-㉳]\s*", "", cond)


def norm_scope(text: str) -> str:
    return re.sub(r"[\s·･ㆍ]", "", text)


def mentioned_groups(note_text: str, tb: dict) -> list[int]:
    """주석 문장이 행 묶음 이름을 글자로 언급하는 묶음 번호. 적용 범위 후보일 뿐 확정 규칙이 아니다."""
    t = norm_scope(note_text)
    hits = []
    for gi, g in enumerate(tb["groups"]):
        if g["kind"] != "data":
            continue
        lab = norm_scope(g["row_labels"][0][-1]) if g["row_labels"] and g["row_labels"][0] else ""
        labs = {lab} | {norm_scope(x) for x in g["group_label"]}
        if any(x and len(x) >= 3 and x in t for x in labs):
            hits.append(gi)
    return hits


# ---------------- 공동 값 ----------------
def shared_cells(tb: dict) -> dict[int, dict]:
    """여러 행에 걸쳐 칸 하나로 적힌 숫자 칸 -> {칸 위치: 적용 행·이름}.

    칸 하나가 몇 행에 걸쳐 표시되는지는 원문 병합 범위다. 적용 행의 이름은 라벨 열(단위·규격 제외)의 마지막 열에서 읽는다.
    """
    out = {}
    item_cols = [k for k in tb["label_cols"] if (tb["col_path"][k] or [""])[-1] not in ("단위", "규격")]
    for i, c in enumerate(tb["cells"]):
        if c["r1"] - c["r0"] <= 1 or c["r0"] < tb["header_rows"] or c["cell_id"] not in tb["_numeric"]:
            continue
        who = []
        for r in range(c["r0"], c["r1"]):
            j = tb["cover"][r][item_cols[-1]] if item_cols else None
            if j is not None and tb["cells"][j]["label"] not in who:
                who.append(tb["cells"][j]["label"])
        out[i] = {"cell_id": c["cell_id"], "rows": [c["r0"], c["r1"]], "names": who, "text_raw": c["text_raw"]}
    return out


def shared_tag(info: dict) -> str:
    n = info["rows"][1] - info["rows"][0]
    return (f" [공동값 {info['cell_id']}: {'·'.join(info['names'])} {n}행에 표시된 같은 값"
            f"(여러 행에 표시된 같은 값을 중복 합산하지 않음)]")


# ---------------- 표 상태 ----------------
def table_issues(tb: dict) -> tuple[list[str], bool]:
    """표 단위 불확실 사유와 계산 보류 여부. 한 칸이라도 값 훼손이 의심되면 표 전체를 보류한다(기존 청킹 원칙)."""
    issues, hold = [], False
    value_flags = [f for f in tb["flags"] if f["severity"] == "value"]
    for f in value_flags:
        issues.append(f"value_suspect: {f['code']} — {f['detail']} ({f['cell_id']}, 원문 글자 {f['text']!r})")
    if value_flags:
        hold = True
        issues.append("table_held: 값 훼손 의심 칸이 같은 표에 있어 표 전체 계산 사용 보류(결함 칸이 없는 행도 포함)")
    for f in tb["flags"]:
        if f["severity"] == "alignment":
            issues.append(f"row_alignment_unconfirmed: {f['detail']} ({', '.join(f.get('cell_ids') or [f['cell_id']])})")
            hold = True
        elif f["severity"] == "formula":
            issues.append(f"formula_unconfirmed: {f['code']} — {f['detail']} ({', '.join(f['cell_ids'])})")
            hold = True
        elif f["severity"] == "graphic":
            issues.append(f"graphic_unconfirmed: {f['code']} — {f['detail']}")
            hold = True
        elif f["severity"] == "semantic":
            issues.append(f"semantic_unconfirmed: {f['code']} — {f['detail']} ({f['cell_id']})")
            hold = True
    return issues, hold


# ---------------- 내보내기 ----------------
class Export:
    def __init__(self, store, generation: dict):
        self.s = store
        self.gen = generation
        self.records: list[dict] = []
        self.rlinks: list[dict] = []          # records와 같은 순서: 레코드가 가리키는 원문 항목
        self.shared: dict[str, dict] = {}     # cell_id -> 공동 값 연결
        self.relations: list[dict] = []
        self._seq: dict[str, int] = {}
        self.tb_by_id = {t["table_id"]: t for t in store.tables}
        self.record_issues: dict[int, list[str]] = {}

    # --- 레코드 추가 ---
    def uid(self, source_id: str) -> str:
        self._seq[source_id] = self._seq.get(source_id, -1) + 1
        return f"{self.gen['id']}:{source_id}#{self._seq[source_id]}"

    def add(self, record: dict, link: dict) -> int:
        idx = len(self.records)
        record["record_uid"] = link["record_uid"] = self.uid(link["source_id"])
        link["record_idx"] = idx
        self.records.append(record)
        self.rlinks.append(link)
        return idx

    def relate(self, kind: str, src: str, dst: str, status: str, confirmed: bool, **extra):
        self.relations.append({"relation_id": f"{self.gen['id']}:rel{len(self.relations)}", "type": kind, "from": src,
                               "to": dst, "status": status, "confirmed": confirmed, **extra})

    # --- 글(기준·주석·소제목) ---
    def add_text(self, source_id, kind, path, page, text, extra_link):
        section, section_status = section_of(path, page)
        record = {"text": f"{section} | 설명 | {one_line(text)}", "section": section, "page": page,
                  "kind": "text", "table_id": None, "bbox": None, "generation_id": self.gen["id"]}
        return self.add(record, {"source_id": source_id, "role": kind, "kind": "text", "page": page, "section": section,
                                 "section_status": section_status, "section_path": path, "source_text": text, **extra_link})

    def export_basis(self, b):
        if not b.get("emit_record", True):
            return      # 번호 제목 끝의 기준: 제목 레코드가 이미 담고, 청킹이 제목에서 읽는다. 관계만 남는다
        self.add_text(b["basis_id"], "basis", b["path"], b["page"], b["text"],
                      {"basis_id": b["basis_id"], "odl_id": b["odl_id"], "bbox": b["bbox"], "confirmed_text": True,
                       "split_from": b.get("split_from"), "origin": b.get("origin"),
                       "after_subheading": b.get("after_subheading")})

    def export_note(self, n):
        self.add_text(n["note_id"], "note", n["path"], n["page"], n["text"],
                      {"note_id": n["note_id"], "odl_id": n["odl_id"], "bbox": n["bbox"], "marker": n["marker"],
                       "scope": n["scope"], "path_status": n["path_status"],
                       **({"correction": n["correction"]} if n.get("correction") else {}),
                       # 변경(본문 완전성): 하위 글의 원시 상위 항목과 깊이, 표 영역 안 미확정 표시
                       **({"nesting": n["nesting"]} if n.get("nesting") else {}),
                       **({"table_region": n["table_region"]} if n.get("table_region") else {})})

    def export_heading(self, h):
        # 번호 소제목('4. 전기아크용접(X형)')은 운영 파서처럼 설명 레코드로 두어 청킹이 소제목 경계로 쓴다.
        # 장 제목·절 제목은 section 으로 남으므로 레코드로 만들지 않는다
        title = h["text"]
        if (SECTION_RE.match(title + " ") or SUBSECTION_RE.match(title + " ") or ITEM_TITLE_RE.match(title)
                or re.match(r"^제\d+장", title)):
            return
        self.add_text(h["heading_id"], "subheading", h["path"][:-1], h["page"], title,
                      {"heading_id": h["heading_id"], "odl_id": h["odl_id"], "bbox": h["bbox"], "level": h["level"]})

    # --- 표 ---
    def export_table(self, tb: dict, nested_in: dict | None = None):
        """표 하나의 레코드. 칸 안의 작은 표는 자기 table_id·bbox를 가진 별도 표로 바로 뒤에 내보낸다.

        청킹은 '표 하나가 청크 하나'이므로 작은 표의 불확실 상태(예: 머리글 가정)가 바깥 표 청크로 번지지 않는다.
        바깥 표와의 연결은 links(nested_in_cell·parent_table_id)와 relations에 남는다.
        """
        section, section_status = section_of(tb["section_path"], tb["page"])
        host = tb
        page = tb["page"]
        traced = assemble.table_to_records(tb["common"], tb["shades"], section, page, trace=True)
        issues, hold = table_issues(tb)
        shared = shared_cells(tb)
        for i, info in shared.items():
            self.shared[info["cell_id"]] = {**info, "table_id": tb["table_id"], "odl_row_span":
                                            tb["cells"][i]["src"]["odl_row_span"], "record_uids": [], "group_ids": []}
        nested_cells = {c["cell_id"]: c for c in tb["cells"] if c.get("nested_table_ids")}
        place = ({"nested_in_cell": nested_in["cell_id"], "parent_table_id": nested_in["table_id"]}
                 if nested_in else {})
        bbox = host["common"]["bbox_pt"]      # 운영 레코드와 같은 왼쪽 위 원점(pt)

        def cid(i):
            return tb["cells"][i]["cell_id"]

        wrote_remark_cells = set()
        for t in traced:
            role = t["role"]
            record_issues = list(issues)
            note_cells = [cid(i) for i in (t.get("cells") or {}).get("note", [])]
            if role == "remark" and any(c in nested_cells for c in note_cells):
                # 비고 칸 안에 작은 표가 있으면 칸 글을 문단별로 남기고 작은 표는 바로 뒤에 별도 표로 내보낸다
                if note_cells[0] in wrote_remark_cells:
                    continue
                wrote_remark_cells.add(note_cells[0])
                cell = nested_cells[note_cells[0]]
                for p in cell["paras"]:
                    self.add_table_record(host, bbox, section, section_status, page,
                                          f"{section} | 비고 | {one_line(p['text'])}",
                                          {"role": "remark", "source_id": tb["table_id"], "table_id": tb["table_id"],
                                           "cell_ids": [cid(i) for i in t["cells"]["label"]] + [cell["cell_id"]],
                                           "para_odl_id": p["odl_id"], "bbox_para": p["bbox"],
                                           "grid_rows": t["grid_rows"], "parts": [], "omitted": [], "source_text": p["text"],
                                           **place},
                                          record_issues)
                continue
            link = {"role": role, "source_id": tb["table_id"], "table_id": tb["table_id"], "grid_rows": t["grid_rows"],
                    "header": t["header"], "parts": [], "omitted": [], **place}
            if tb.get("correction"):
                link["correction"] = tb["correction"]
            if tb.get('source_review'):
                link['source_review']=tb['source_review']
            if tb.get('graphic_source'):
                link['graphic_legend']={'page':tb['graphic_source']['legend_page'],'odl_id':tb['graphic_source']['legend_odl_id'],
                                       'basis':tb['graphic_source']['basis']}
            text = t["text"]
            if role == "row":
                bits, cell_ids, shared_here = [], [], []
                for part in t["parts"]:
                    ids = [cid(i) for i in part.get("cells", [])]
                    if (tb.get('source_review') and ids and set(ids) <= set(cell_ids)
                            and all(tb['cells'][i]['c0'] in tb['label_cols'] for i in part.get('cells', []))):
                        link.setdefault('duplicate_label_parts', []).append({'col':part.get('col'),'cell_ids':ids})
                        continue
                    rendered = part["text"]
                    semantic = None
                    source_text = part["text"]
                    if len(ids) == 1:
                        cell = tb["cells"][part["cells"][0]]
                        semantic = cell.get("semantic")
                        if (cell.get('source_review') or {}).get('kind')=='reviewed_label_span' and part['role']=='label':
                            rendered=assemble.clean(cell['text_raw']).replace('\n',' ')
                        if cell.get('graphic_conditions'):
                            info=cell['graphic_conditions']
                            link.setdefault('graphic_conditions',[]).append({'cell_id':cell['cell_id'],**info})
                            above=[str(x['converted_kw']) for x in info['conditions'] if x['source_position']=='선 위쪽 값 영역']
                            below=[str(x['converted_kw']) for x in info['conditions'] if x['source_position']=='선 아래쪽 값 영역']
                            clipped=[str(x['converted_kw']) for x in info['conditions'] if x.get('boundary_clipped_at_chart_bottom')]
                            rendered += ' [계단선 위치: 위쪽 출력 '+('·'.join(above) or '없음')+'㎾; 아래쪽 출력 '+('·'.join(below) or '없음')+'㎾'
                            if clipped:rendered+='; 아래끝 밖 경계 '+ '·'.join(clipped)+'㎾'
                            rendered+=']'
                            link['graphic_legend']={'page':tb['graphic_source']['legend_page'],'odl_id':tb['graphic_source']['legend_odl_id'],
                                'basis':tb['graphic_source']['basis']}
                        if semantic and semantic["kind"] == "label_scope":
                            # 묶음 전체 이름을 각 행의 확정 이름처럼 복사하지 않는다. 원문은 칸과 연결 자료에 남는다.
                            head = " ".join(tb["col_path"][part["col"]])
                            rendered = f"{head} [이름 적용 범위 미확정]".strip()
                        elif semantic and semantic["kind"] == "classification_code" and semantic["status"] == "derived":
                            raw = (assemble.clean(cell["text_raw"]) or "").replace("\n", " ").strip()
                            if raw and rendered.endswith(raw):
                                rendered = rendered[:-len(raw)] + semantic["normalized"]
                            else:
                                record_issues.append(f"semantic_render_unconfirmed: 정리한 코드와 표시 글을 연결하지 못함 ({cell['cell_id']})")
                    tag = ""
                    for i in part.get("cells", []):
                        if i in shared and part["role"] == "value":
                            tag = shared_tag(shared[i])
                            shared_here.append(cid(i))
                    bits.append(rendered + tag)
                    cell_ids += [c for c in ids if c not in cell_ids]
                    link["parts"].append({"role": part["role"], "col": part.get("col"), "cell_ids": ids,
                                          "line": part.get("line"), "repeated": part.get("repeated", False),
                                          "shared": bool(tag), "text": rendered,
                                          **({"source_text": source_text, "semantic": semantic} if semantic else {})})
                text = " | ".join(bits)
                link["omitted"] = [{"col": o["col"], "cell_ids": [cid(i) for i in o["cells"]], "raw": o["raw"]}
                                   for o in t["omitted"]]
                omitted_distances=[]
                for omitted in t['omitted']:
                    for i in omitted['cells']:
                        c=tb['cells'][i]
                        if not c.get('graphic_conditions'):continue
                        info=c['graphic_conditions']
                        link.setdefault('graphic_conditions',[]).append({'cell_id':c['cell_id'],'omitted':True,**info})
                        omitted_distances.append(str(info['distance_m']))
                if omitted_distances:text+=' | 원문 값 없음(-): 배사거리 '+ '·'.join(omitted_distances)+'m'
                rm = tb["row_map"][t["grid_rows"][0]] if t["grid_rows"] and t["grid_rows"][0] < len(tb["row_map"]) else {}
                link["row_split"] = {**t["row_split"], "odl_row": rm.get("odl_row"), "coord_kind": rm.get("coord_kind"),
                                     "confirmed": (rm.get("coord_kind") == "pdf_baseline") if rm.get("state") == "split"
                                     else True if rm.get("state") == "confirmed_single" else None,
                                     **({"row_mapping": rm["row_mapping"]} if rm.get("row_mapping") else {})}
                link["cell_ids"] = cell_ids
                link["shared_cell_ids"] = shared_here
                if t["row_split"]["basis"] in ASSEMBLY_SPLIT_BASIS:
                    record_issues.append(f"row_split_unconfirmed: 어댑터가 쌓인 행을 나누지 못해({rm.get('reason')}) 조립 단계가 "
                                         f"{t['row_split']['basis']}로 {t['row_split']['depth']}행으로 나눈 후보")
                elif rm.get("state") == "split" and rm.get("coord_kind") != "pdf_baseline":
                    record_issues.append("row_split_unconfirmed: 행 분리에 쓴 줄 위치가 문단 높이로 추정한 값(실제 글자 좌표 아님)")
            else:
                cells = t.get("cells") or {}
                link["cell_ids"] = [cid(i) for v in cells.values() for i in v]
            if t["header"]["basis"] in HEADER_ISSUES:
                record_issues.append(f"{t['header']['basis']}: 숫자 칸 규칙으로 머리글을 정하지 못해 첫 줄(또는 첫 숫자 행 앞)을 머리글로 가정")
            self.add_table_record(host, bbox, section, section_status, page, text, link, record_issues)
        for cell in nested_cells.values():
            for nid in cell["nested_table_ids"]:
                self.relate("nested_table_in_cell", nid, cell["cell_id"], "표 안 칸에 든 작은 표(구조로 확인)", True,
                            parent_table=tb["table_id"])
                self.export_table(self.tb_by_id[nid], {"cell_id": cell["cell_id"], "table_id": tb["table_id"]})

    def add_table_record(self, host, bbox, section, section_status, page, text, link, issues):
        status = "uncertain" if issues else "ok"
        record = {"text": text, "section": section, "page": page, "kind": "table", "table_id": host["table_id"],
                  "bbox": bbox, "structure": {"status": status, "issues": list(issues)},
                  "generation_id": self.gen["id"]}
        link.update(kind="table", page=page, section=section, section_status=section_status,
                    host_table_id=host["table_id"], structure=record["structure"])
        link.setdefault("shared_cell_ids", [])
        idx = self.add(record, link)
        # 공동 값 -> 적용 레코드
        for c in link["shared_cell_ids"]:
            self.shared[c]["record_uids"].append(link["record_uid"])
        return idx

    # --- 관계 ---
    def build_relations(self):
        s = self.s
        by_note = {n["note_id"]: n for n in s.notes}
        for b in s.basis:
            owners = [t for t in s.tables if t["basis"] is b]
            extra = {"text_confirmed": True, "origin": b.get("origin"), "split_from": b.get("split_from"),
                     "after_subheading": b.get("after_subheading"), "candidate_tables": b.get("candidate_tables", [])}
            if owners:
                many = len(b.get("candidate_tables", [])) > 1
                self.relate("basis_of", b["basis_id"], owners[0]["table_id"],
                            "후보(다음 제목·기준 전에 표가 여러 개)" if many else "위치 근거(표 바로 위, 사이에 다른 제목·표 없음)",
                            False, **extra)
            else:
                self.relate("basis_of", b["basis_id"], None, "붙은 표 없음(기준 글만 남음)", False, **extra)
        for lt in s.logical_tables:
            self.relate("table_continues", lt["parts"][0], lt["parts"][1], lt["status"], False, logical_id=lt["logical_id"],
                        evidence=lt["evidence"], parts=lt["parts"],
                        pages=[self.tb_by_id[x]["page"] for x in lt["parts"]])
        for n in s.notes:
            scope = n["scope"]
            if scope["kind"] == "table_tail":
                tb = self.tb_by_id[scope["owner"]]
                self.relate("note_of_table", n["note_id"], tb["table_id"], scope["status"], False,
                            owner_calc_status=tb["calc_status"], cross_page=bool(scope.get("cross_page")),
                            evidence=scope.get("evidence"), owner_page=scope.get("owner_page", tb["page"]))
                hits = mentioned_groups(n["text"], tb)
                if hits:
                    self.relate("mentions_groups", n["note_id"], tb["table_id"],
                                "문장이 행 묶음 이름을 글자로 언급(적용 범위 후보, 확정 규칙 아님)", False,
                                groups=[f"{tb['table_id']}:g{gi}" for gi in hits])
                if n["marker"] and n["marker"][-1] in SUBMARK:
                    parents = [m for m in s.notes if m["scope"].get("owner") == scope["owner"] and m["marker"]
                               and m["marker"][-1] in CIRCLED and m["bbox"][1] > n["bbox"][1]]
                    if parents:
                        self.relate("sub_note_of", n["note_id"], parents[-1]["note_id"], "위치 근거(㉮㉯는 앞선 ①② 항목 아래)", False)
            elif scope["kind"] == "list_child":
                # 변경(본문 완전성): 원시 출력의 상하 관계. 상위 항목의 소속(표·절)은 상위 항목 관계를 따른다
                self.relate("child_of_item", n["note_id"], scope["owner"], scope["status"], False,
                            owner_kind=scope["owner_kind"])
            elif scope["kind"] == "section_intro":
                self.relate("note_of_section", n["note_id"], scope.get("owner"), scope["status"], False)
            else:
                self.relate("note_of_unknown", n["note_id"], None, scope["status"], False)
            if (n.get("nesting") or {}).get("after_table_in_item"):
                self.relate("follows_table_in_item", n["note_id"], n["nesting"]["after_table_in_item"],
                            "후보(같은 목록 항목 안에서 표 뒤에 있음. 표 주석으로 확정하지 않음)", False)
            if n.get("continues"):
                self.relate("note_sentence_continues", n["note_id"], n["continues"],
                            "위치 근거(앞 쪽 마지막 항목이 문장으로 끝나지 않고 다음 쪽 첫머리가 표지 없는 문장)", False)
            for ref in find_refs(n["text"]):
                sentence, cond = reference_parts(n["text"], ref["span"])
                self.relate("reference", n["note_id"], None,
                            "대상 미조회(이번 범위에서 참조 대상 원문을 조회하지 않음)", False,
                            target={"part": ref["part"], "number": ref["num"], "title": ref["title"]},
                            condition_text=cond, sentence=sentence, cost_effect="자동 가산 없음(조건 판정 전에는 금액에 넣지 않는다)")
        for t in s.tables:
            if t["role"] == "note_table":
                owner = t.get("note_table_of")
                self.relate("note_table_of", t["table_id"], owner, "위치 근거(주석 아래에 붙은 표)", False,
                            note_id=t.get("note_table_of_note"))
            # 안쪽 작은 표의 구분 칸 글자가 바깥 표 행 묶음 이름과 같으면 정의 관계(글자 일치)
            for nid in [i for c in t["cells"] for i in c.get("nested_table_ids", [])]:
                nt = self.tb_by_id[nid]
                for ng in nt["groups"]:
                    lab = ng["group_label"][0] if ng["group_label"] else ""
                    for gi, g in enumerate(t["groups"]):
                        if g["kind"] == "data" and lab and (norm_scope(lab) == norm_scope(" ".join(g["group_label"]))):
                            self.relate("defines_group", f"{nid}:rows{ng['rows']}", f"{t['table_id']}:g{gi}",
                                        "라벨 글자 일치", True, label=lab)
            open_items = []
            if t["role"] == "table":
                tail = [n for n in s.notes if n["scope"].get("owner") == t["table_id"]]
                near_bottom = t["bbox_native"][1] <= BOTTOM_RATIO * s.page_top[t["page"]]
                nxt = t["page"] + 1
                if any(n["page"] != t["page"] for n in tail):
                    open_items.append(f"다음 쪽 주석 {sum(1 for n in tail if n['page'] != t['page'])}건을 위치 근거로 연결함(확정 아님)")
                elif near_bottom and not any(g["kind"] == "remark" for g in t["groups"]) and not tail:
                    nxt_known = (s.pages is None or nxt in s.pages) and any(n.get("page number") == nxt for n in s.doc["kids"])
                    if nxt_known:
                        open_items.append("쪽 맨 아래 표이고 다음 쪽 첫머리에 이어진 주석이 없음(다음 쪽 출력으로 확인함)")
                    else:
                        open_items.append("쪽 맨 아래 표라 표 아래 주석이 다음 쪽에 이어질 수 있다(다음 쪽 출력이 없어 확인하지 못함, 미확정)")
                if t.get("continues_next_page") and not t.get("continues_next_page", {}).get("target"):
                    open_items.append("이어짐 표시(→)가 있으나 다음 쪽 표를 이 출력에서 확인하지 못함(미확인)")
            t["open_items"] = open_items


def export(store, generation: dict) -> dict:
    """보관 구조 -> {"records": [...], "links": {...}}. chunk.make_chunks 호출은 호출자가 한다(변경 없는 함수 그대로)."""
    ex = Export(store, generation)
    items = ([(b["order"], "basis", b) for b in store.basis]
             + [(n["order"], "note", n) for n in store.notes]
             + [(h["order"], "heading", h) for h in store.headings]
             + [(t["order"], "table", t) for t in store.tables if t["role"] in ("table", "note_table")])
    for _, kind, obj in sorted(items, key=lambda x: x[0]):
        {"basis": ex.export_basis, "note": ex.export_note, "heading": ex.export_heading, "table": ex.export_table}[kind](obj)
    ex.build_relations()
    for cell_id, sh in ex.shared.items():
        tb = ex.tb_by_id[sh["table_id"]]
        sh["group_ids"] = sorted({f"{tb['table_id']}:g{gi}" for gi, g in enumerate(tb["groups"])
                                  if any(r in g["rows"] for r in range(sh["rows"][0], sh["rows"][1]))})
    return {"records": ex.records, "record_links": ex.rlinks, "shared_values": list(ex.shared.values()),
            "relations": ex.relations, "logical_tables": store.logical_tables, "boundaries": store.boundaries,
            "context_out": store.context_out,
            "open_items": {t["table_id"]: t.get("open_items", []) for t in store.tables}}


def chunk_links(chunks: list[dict], exported: dict, store, generation_id: str) -> list[dict]:
    """청크 -> 레코드 -> 원문 칸·주석·기준. make_chunks 결과를 읽기만 한다."""
    rl, out = exported["record_links"], []
    tb_by_id = {t["table_id"]: t for t in store.tables}
    note_owner = {r["from"]: r for r in exported["relations"] if r["type"] == "note_of_table"}
    for ch in chunks:
        recs = [rl[i] for i in ch["record_ids"]]
        cells, notes, basis_ids = [], [], []
        for r in recs:
            cells += [c for c in r.get("cell_ids", []) if c not in cells]
            if r.get("note_id"):
                notes.append(r["note_id"])
            if r.get("basis_id"):
                basis_ids.append(r["basis_id"])
        host = tb_by_id.get(ch["source"]["table_id"]) if ch["kind"] == "table" else None
        if host and ch["basis"] and host["basis"] and host["basis"]["text"] == ch["basis"]:
            basis_ids.append(host["basis"]["basis_id"])
        if ch["kind"] != "table":
            use = "해당 없음(줄글 청크, 표 상태는 related_table_status 참고)"
        elif ch["structure"] != "ok":
            use = "계산 사용 보류: 구조 불확실(uncertain_record_uids·chunk_issues 참고)"
        else:
            use = "계산 승인 아님(구조 표지가 없을 뿐이다. 값·단위·산식 검증과 사람 검토는 별도)"
        out.append({"chunk_id": ch["chunk_id"], "kind": ch["kind"], "generation_id": generation_id, "calc_use": use,
                    "record_idx": list(ch["record_ids"]), "record_uids": [r["record_uid"] for r in recs],
                    "table_id": ch["source"]["table_id"], "cell_ids": cells, "note_ids": notes, "basis_ids": basis_ids,
                    "structure": ch["structure"],
                    "uncertain_record_uids": [rl[i]["record_uid"] for i in ch["uncertain_record_ids"]],
                    "chunk_issues": ch.get("issues", []),
                    "table_calc_status": host["calc_status"] if host else None,
                    # 표 아래 주석 청크가 보류 표의 주석이면 그 상태를 함께 싣는다
                    "related_table_status": [{"note_id": n, "table_id": note_owner[n]["to"],
                                              "calc_status": note_owner[n]["owner_calc_status"]}
                                             for n in notes if n in note_owner]})
    return out
