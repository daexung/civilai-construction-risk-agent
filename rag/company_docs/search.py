"""
사내 문서 RAG 검색 모듈

기능
1. PostgreSQL(pgvector) rag.company_docs 테이블에서 자재명으로 과거 계약단가 조회
2. 계약서/견적서/기성청구서 등에서 계약조건 검색
3. 장비 대기료, 유휴장비비, 작업중지, 공기연장 관련 계약조건 검색

material_cost_agent, equipment_cost_agent에서 LangChain Tool로 직접 사용 가능

사용 예:
  from rag.company_docs.search import search_contract_price
  result = search_contract_price.invoke({"material_name": "철근 SD400"})

  from rag.company_docs.search import search_equipment_standby_terms
  result = search_equipment_contract_terms.invoke({
      "equipment_name": "크레인",
      "risk_type": "강풍"
  })
"""

import os
import re
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

import psycopg2
from pgvector.psycopg2 import register_vector
from langchain_aws import BedrockEmbeddings
from langchain_core.tools import tool


EMBED_MODEL = "amazon.titan-embed-text-v2:0"
N_RESULTS = 15


PRICE_PATTERN = re.compile(
    r"([가-힣a-zA-Z0-9\s\-\(\)×./]+?)"
    r"[\s:：|]*"
    r"([\d,]+)"
    r"\s*원"
    r"(?:/\s*([a-zA-Zㄱ-힣㎥㎡㎣㎤]+))?",
    re.UNICODE,
)


DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "material_cost"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}


def get_connection():
    """
    PostgreSQL 연결을 생성하고 pgvector 타입을 등록합니다.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    register_vector(conn)
    return conn


def _get_embedder():
    """
    Bedrock Titan Embedding 모델을 반환합니다.
    """
    return BedrockEmbeddings(
        model_id=EMBED_MODEL,
        region_name=os.getenv("AWS_BEDROCK_REGION", "us-east-1"),
    )


def _extract_prices(text: str) -> list[dict]:
    """
    문서 원문에서 '자재명 10,000원/단위' 형태의 단가 정보를 추출합니다.
    """
    results = []

    for match in PRICE_PATTERN.finditer(text):
        name = match.group(1).strip(" \t|")
        price = match.group(2).replace(",", "")
        unit = match.group(3) or ""

        try:
            results.append(
                {
                    "자재명": name,
                    "단가": int(price),
                    "단위": unit,
                }
            )
        except ValueError:
            continue

    return results


def search_raw(
    query: str,
    n_results: int = N_RESULTS,
    doc_type: str | None = None,
    year: str | None = None,
    project_id: str | None = None,
) -> list[dict]:
    """
    PostgreSQL pgvector에서 쿼리와 유사한 청크를 검색하고 원본 결과를 반환합니다.

    Args:
        query: 검색 쿼리
        n_results: 반환할 검색 결과 수
        doc_type: 문서 유형 필터
        year: 연도 필터
        project_id: 프로젝트/공사명 필터

    Returns:
        검색된 문서 청크 리스트
    """
    embedder = _get_embedder()
    query_embedding = embedder.embed_query(query)

    conn = get_connection()
    cur = conn.cursor()

    where_clauses = []
    filter_params = []

    if doc_type:
        where_clauses.append("doc_type = %s")
        filter_params.append(doc_type)

    if year:
        where_clauses.append("year = %s")
        filter_params.append(year)

    if project_id:
        where_clauses.append("project_id = %s")
        filter_params.append(project_id)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
        SELECT
            content,
            project_id,
            doc_type,
            year,
            file_name,
            embedding <=> %s::vector AS distance
        FROM rag.company_docs
        {where_sql}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """

    params = [query_embedding] + filter_params + [query_embedding, n_results]
    cur.execute(sql, params)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {
            "document": row[0],
            "metadata": {
                "project_id": row[1],
                "doc_type": row[2],
                "year": row[3],
                "file_name": row[4],
            },
            "distance": row[5],
        }
        for row in rows
    ]


@tool
def search_contract_price(material_name: str) -> str:
    """
    사내 문서(계약서, 견적서, 기성청구서)에서 특정 자재의 과거 계약단가를 전체 공사별로 조회합니다.

    모든 프로젝트의 계약단가를 반환하므로, 에이전트는 공사별 단가를 비교하고
    현재 조달청 단가 대비 절감률 등을 분석하여 리포트를 작성해야 합니다.

    Args:
        material_name: 조회할 자재명
                       예: "철근 SD400", "합판", "레미콘", "H형강"
    """
    try:
        chunks = search_raw(f"{material_name} 계약단가", n_results=N_RESULTS)
        keyword = material_name.split()[0]

        if not chunks:
            return json.dumps(
                {
                    "status": "not_found",
                    "query": material_name,
                    "message": "사내 문서에서 관련 계약단가를 찾을 수 없습니다. embed.py 실행 여부를 확인하세요.",
                },
                ensure_ascii=False,
                indent=2,
            )

        by_project: dict[str, dict] = {}

        for chunk in chunks:
            meta = chunk["metadata"]
            project_id = meta.get("project_id", "unknown")
            year = meta.get("year", "")
            file_name = meta.get("file_name", "")
            doc_type = meta.get("doc_type", "")
            proj_key = f"{project_id}_{year}"

            prices = _extract_prices(chunk["document"])
            relevant = [p for p in prices if keyword in p["자재명"]]

            if not relevant:
                if proj_key not in by_project:
                    by_project[proj_key] = {
                        "공사명": project_id,
                        "연도": year,
                        "문서유형": doc_type,
                        "출처파일": file_name,
                        "계약단가목록": [],
                        "원문_참고": chunk["document"][:300],
                    }
                continue

            if proj_key not in by_project:
                by_project[proj_key] = {
                    "공사명": project_id,
                    "연도": year,
                    "문서유형": doc_type,
                    "출처파일": file_name,
                    "계약단가목록": [],
                    "원문_참고": "",
                }

            for price_item in relevant:
                existing_prices = [
                    item["단가"]
                    for item in by_project[proj_key]["계약단가목록"]
                ]

                if price_item["단가"] not in existing_prices:
                    by_project[proj_key]["계약단가목록"].append(
                        {
                            "자재명": price_item["자재명"],
                            "단가": price_item["단가"],
                            "단위": price_item["단위"],
                        }
                    )

        projects_with_price = {
            key: value
            for key, value in by_project.items()
            if value["계약단가목록"]
        }

        if not projects_with_price:
            return json.dumps(
                {
                    "status": "found_context",
                    "query": material_name,
                    "message": "관련 문서는 검색됐으나 단가 패턴을 자동 추출하지 못했습니다. 아래 원문을 참고하세요.",
                    "context": [
                        {
                            "원문": chunk["document"][:300],
                            "출처파일": chunk["metadata"].get("file_name", ""),
                            "공사명": chunk["metadata"].get("project_id", ""),
                            "연도": chunk["metadata"].get("year", ""),
                        }
                        for chunk in chunks[:3]
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )

        sorted_projects = sorted(
            projects_with_price.values(),
            key=lambda item: item["연도"],
        )

        all_prices = [
            price_item["단가"]
            for project in sorted_projects
            for price_item in project["계약단가목록"]
        ]

        return json.dumps(
            {
                "status": "success",
                "query": material_name,
                "안내": "아래 공사별 계약단가를 현재 조달청 단가와 비교하여 절감률, 추이, 협상 근거를 리포트에 포함하세요.",
                "공사별_계약단가": sorted_projects,
                "통계": {
                    "공사_수": len(sorted_projects),
                    "최저_계약단가": min(all_prices),
                    "최고_계약단가": max(all_prices),
                    "평균_계약단가": round(sum(all_prices) / len(all_prices)),
                },
            },
            ensure_ascii=False,
            indent=2,
        )

    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "message": f"검색 오류: {str(e)}",
            },
            ensure_ascii=False,
        )


@tool
def search_contract_terms(query: str) -> str:
    """
    사내 문서에서 특정 계약 조건이나 특약 조항을 검색합니다.

    장비 대기료뿐 아니라 우천 작업중지, 강풍 작업중지, 공기연장,
    추가비용 인정 조건 등 일반 계약조건 검색에 사용할 수 있습니다.

    Args:
        query: 검색할 계약 조건 키워드
               예: "우천 장비 대기료", "강풍 작업중지",
                   "공기연장 추가비용", "유휴장비비 지급 조건"
    """
    try:
        chunks = search_raw(query, n_results=N_RESULTS)

        if not chunks:
            return json.dumps(
                {
                    "status": "not_found",
                    "query": query,
                    "message": "사내 문서에서 관련 계약 조건을 찾을 수 없습니다.",
                },
                ensure_ascii=False,
                indent=2,
            )

        results = []

        for chunk in chunks:
            meta = chunk["metadata"]

            results.append(
                {
                    "공사명": meta.get("project_id", ""),
                    "연도": meta.get("year", ""),
                    "문서유형": meta.get("doc_type", ""),
                    "출처파일": meta.get("file_name", ""),
                    "유사도거리": round(float(chunk["distance"]), 4),
                    "관련원문": chunk["document"][:500],
                }
            )

        return json.dumps(
            {
                "status": "success",
                "query": query,
                "안내": "아래 원문을 근거로 계약상 추가비용 인정 가능 여부, 장비 대기료 지급 조건, 공기연장 가능성을 판단하세요.",
                "검색결과": results,
            },
            ensure_ascii=False,
            indent=2,
        )

    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "message": f"계약 조건 검색 오류: {str(e)}",
            },
            ensure_ascii=False,
        )


@tool
def search_equipment_contract_terms(
    equipment_name: str,
    risk_type: str = "기상",
) -> str:
    """
    사내 계약 문서에서 장비 대기료, 유휴장비비, 작업중지, 공기연장 관련 조건을 검색합니다.

    equipment_cost_agent에서 우천, 강풍, 폭염 등으로 장비가 대기하는 경우
    계약상 대기료 인정 가능 여부를 판단할 때 사용합니다.

    Args:
        equipment_name: 장비명
                        예: "크레인", "굴삭기", "덤프트럭", "콘크리트 펌프카"
        risk_type: 리스크 유형
                   예: "우천", "강풍", "폭염", "기상", "작업중지"
    """
    try:
        search_query = (
            f"{equipment_name} {risk_type} 장비 대기료 유휴장비비 "
            f"작업중지 공기연장 추가비용 계약조건"
        )

        chunks = search_raw(search_query, n_results=N_RESULTS)

        if not chunks:
            return json.dumps(
                {
                    "status": "not_found",
                    "equipment_name": equipment_name,
                    "risk_type": risk_type,
                    "message": "사내 문서에서 장비 대기료 관련 계약 조건을 찾을 수 없습니다.",
                },
                ensure_ascii=False,
                indent=2,
            )

        results = []

        for chunk in chunks:
            meta = chunk["metadata"]

            results.append(
                {
                    "공사명": meta.get("project_id", ""),
                    "연도": meta.get("year", ""),
                    "문서유형": meta.get("doc_type", ""),
                    "출처파일": meta.get("file_name", ""),
                    "유사도거리": round(float(chunk["distance"]), 4),
                    "관련원문": chunk["document"][:600],
                }
            )

        return json.dumps(
            {
                "status": "success",
                "equipment_name": equipment_name,
                "risk_type": risk_type,
                "검색쿼리": search_query,
                "안내": (
                    "아래 계약 문서 근거를 바탕으로 장비 대기료 인정 여부, "
                    "대기 시간 산정 기준, 공기연장 가능성, 추가비용 청구 가능성을 판단하세요."
                ),
                "계약조건_검색결과": results,
            },
            ensure_ascii=False,
            indent=2,
        )

    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "message": f"장비 대기료 계약조건 검색 오류: {str(e)}",
            },
            ensure_ascii=False,
        )


@tool
def list_contract_documents() -> str:
    """
    사내 문서 DB에 저장된 문서 목록과 공사별 계약 현황을 반환합니다.

    어떤 프로젝트의 계약단가 또는 계약조건을 조회할 수 있는지 확인할 때 사용합니다.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                file_name,
                doc_type,
                project_id,
                year,
                COUNT(*) AS chunk_count
            FROM rag.company_docs
            GROUP BY file_name, doc_type, project_id, year
            ORDER BY year, project_id
            """
        )
        rows = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM rag.company_docs")
        total_chunks = cur.fetchone()[0]

        cur.close()
        conn.close()

        docs = [
            {
                "파일명": row[0],
                "문서유형": row[1],
                "공사명": row[2],
                "연도": row[3],
                "청크수": row[4],
            }
            for row in rows
        ]

        return json.dumps(
            {
                "status": "success",
                "총_문서수": len(docs),
                "총_청크수": total_chunks,
                "문서_목록": docs,
            },
            ensure_ascii=False,
            indent=2,
        )

    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "message": f"오류: {str(e)}",
            },
            ensure_ascii=False,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--query",
        type=str,
        default="철근 SD400 계약단가",
        help="검색 쿼리 또는 자재명",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="사내 문서 목록 조회",
    )

    parser.add_argument(
        "--terms",
        action="store_true",
        help="일반 계약조건 검색",
    )

    parser.add_argument(
        "--equipment",
        type=str,
        help="장비 대기료 계약조건 검색용 장비명",
    )

    parser.add_argument(
        "--risk",
        type=str,
        default="기상",
        help="리스크 유형 예: 우천, 강풍, 폭염, 기상, 작업중지",
    )

    args = parser.parse_args()

    if args.list:
        print(list_contract_documents.invoke({}))

    elif args.equipment:
        print(
            f"\n[장비 대기료 계약조건 검색] 장비='{args.equipment}', 리스크='{args.risk}'"
        )
        print(
            search_equipment_standby_terms.invoke(
                {
                    "equipment_name": args.equipment,
                    "risk_type": args.risk,
                }
            )
        )

    elif args.terms:
        print(f"\n[계약 조건 검색] '{args.query}'")
        print(search_contract_terms.invoke({"query": args.query}))

    else:
        print(f"\n[계약단가 검색] '{args.query}'")
        print(search_contract_price.invoke({"material_name": args.query}))