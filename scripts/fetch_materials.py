"""
조달청 시설공통자재 가격정보 API 호출 스크립트
- 사업부문(토목/건축/기계설비/전기정보통신)별로 URL이 다른 경우 대응
- Airflow DAG 또는 단독 실행 모두 가능

실행 전 확인사항:
- .env 파일에 GONGGONG_API_KEY 설정 필요
- DIVISION_MAP의 url을 실제 사용한 엔드포인트로 교체
"""

import time
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw" / "material_cost"
RAW_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("GONGGONG_API_KEY", "")

# ── 사업부문별 URL + 저장 파일명 ──────────────────────────────────
DIVISION_MAP = [
    {
        "name": "토목",
        "url": os.getenv("GONGGONG_API_URL_CIVIL"),
        "filename": "civil_materials.csv",
    },
    {
        "name": "건축",
        "url": os.getenv("GONGGONG_API_URL_ARCH"),
        "filename": "arch_materials.csv",
    },
    {
        "name": "기계설비",
        "url": os.getenv("GONGGONG_API_URL_MECH"),
        "filename": "mech_materials.csv",
    },
    {
        "name": "전기정보통신",
        "url": os.getenv("GONGGONG_API_URL_ELEC"),
        "filename": "elec_materials.csv",
    },
]

NUM_OF_ROWS = 100  # 페이지당 조회 건수 (API 최대 100건)


def fetch_division(name: str, url: str, filename: str) -> pd.DataFrame:
    """
    특정 사업부문의 자재 단가를 전체 페이징 조회.
    """
    all_rows = []
    page_no = 1

    print(f"  [API] {name} 조회 시작... ({url})")

    while True:
        params = {
            "serviceKey": API_KEY,
            "pageNo": page_no,
            "numOfRows": NUM_OF_ROWS,
            "type": "json",
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"  ⚠ API 호출 실패 (페이지 {page_no}): {e}")
            break
        except ValueError:
            print(f"  ⚠ JSON 파싱 실패 (페이지 {page_no})")
            break

        # 응답 구조: response.body.items 가 list로 바로 옴
        try:
            items = (
                data.get("response", {})
                    .get("body", {})
                    .get("items", [])
            )
            # 일부 API는 items 안에 item 키로 한번 더 감싸는 경우 대응
            if isinstance(items, dict):
                items = items.get("item", [])
        except AttributeError:
            print(f"  ⚠ 응답 구조 파싱 실패. 실제 응답: {data}")
            break

        if not items:
            break

        if isinstance(items, dict):
            items = [items]

        all_rows.extend(items)
        print(f"    페이지 {page_no}: {len(items)}건 수집 (누적: {len(all_rows)}건)")

        total_count = (
            data.get("response", {})
                .get("body", {})
                .get("totalCount", 0)
        )
        if len(all_rows) >= int(total_count):
            break

        page_no += 1
        time.sleep(0.3)

    df = pd.DataFrame(all_rows)
    output_path = RAW_DIR / filename
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"  ✔ 저장 완료: {output_path} ({len(df):,}행)")
    return df


def fetch_all() -> bool:
    """
    전체 사업부문 자재 단가 수집.
    Airflow에서 호출하거나 단독 실행 가능.
    """
    if not API_KEY:
        raise EnvironmentError(
            ".env 파일에 GONGGONG_API_KEY가 없습니다.\n"
            "공공데이터포털(data.go.kr)에서 발급받은 API 키를 설정하세요."
        )

    print("=" * 50)
    print("조달청 자재 단가 API 수집 시작")
    print("=" * 50)

    success_count = 0
    for division in DIVISION_MAP:
        try:
            df = fetch_division(division["name"], division["url"], division["filename"])
            if not df.empty:
                success_count += 1
        except Exception as e:
            print(f"  ✗ {division['filename']} 수집 실패: {e}")

    print(f"\n✅ 수집 완료: {success_count}/{len(DIVISION_MAP)}개 부문")
    return success_count == len(DIVISION_MAP)


if __name__ == "__main__":
    fetch_all()
