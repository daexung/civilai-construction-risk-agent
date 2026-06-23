"""
조달청 CSV 전처리 스크립트
- data/raw/material_cost/ 의 CSV 4개를 읽어 정제
- data/raw/material_cost/supplement_materials.csv (보조 자재 단가) 병합
- 자재명 기준 최신 단가 추출
- data/processed/materials_db.csv 저장
"""

import pandas as pd
from pathlib import Path

# 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw" / "material_cost"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# 조달청 CSV 파일 목록
CSV_FILES = [
    "civil_materials.csv",
    "arch_materials.csv",
    "mech_materials.csv",
    "elec_materials.csv",
]

# 보조 자재 단가 파일 (조달청 미포함 자재: 레미콘, 시멘트, 골재 등)
SUPPLEMENT_FILE = "supplement_materials.csv"

# 사용할 컬럼만 추출 (조달청 원본 컬럼명 → 한국어 컬럼명)
COLUMN_MAP = {
    "krnPrdctNm": "자재명",
    "unit": "단위",
    "prce": "현재단가",
    "nticeDt": "공시일자",
    "bsnsDivNm": "자재분류",
    "prdctClsfcNoNm": "품목분류",
    "vatYnNm": "부가세여부",
}


def load_csv(filepath: str) -> pd.DataFrame:
    """CSV 파일을 읽어 DataFrame 반환. 인코딩은 UTF-8 → EUC-KR 순으로 시도."""
    for enc in ["utf-8", "utf-8-sig", "euc-kr", "cp949"]:
        try:
            df = pd.read_csv(filepath, encoding=enc, low_memory=False)
            print(f"  ✔ {Path(filepath).name} 로드 완료 ({len(df):,}행, 인코딩: {enc})")
            return df
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"파일을 읽을 수 없습니다: {filepath}")


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    """필요한 컬럼 추출 및 기본 정제."""
    # 존재하는 컬럼만 선택
    available = {k: v for k, v in COLUMN_MAP.items() if k in df.columns}
    df = df[list(available.keys())].rename(columns=available)

    # 단가가 없는 행 제거
    df = df.dropna(subset=["현재단가", "자재명"])
    df["현재단가"] = pd.to_numeric(df["현재단가"], errors="coerce")
    df = df[df["현재단가"] > 0]

    # 공시일자 datetime 변환
    if "공시일자" in df.columns:
        df["공시일자"] = pd.to_datetime(df["공시일자"], errors="coerce")

    # 자재명 공백 정리
    df["자재명"] = df["자재명"].astype(str).str.strip()

    return df


def get_latest_prices(df: pd.DataFrame) -> pd.DataFrame:
    """
    같은 자재명 + 단위 조합에서 가장 최신 공시 단가만 남긴다.
    시황성 자재(단가 변동이 있는 자재)는 최신값이 현재 시장가에 가장 가깝다.
    """
    if "공시일자" in df.columns:
        df = df.sort_values("공시일자", ascending=False)

    # 자재명 + 단위 기준 중복 제거 (최신 단가만 유지)
    df = df.drop_duplicates(subset=["자재명", "단위"], keep="first")
    return df.reset_index(drop=True)


def add_market_sensitive_flag(df: pd.DataFrame) -> pd.DataFrame:
    """
    단가 변동이 있는 자재 = '시황성 자재'로 표시.
    같은 자재명+단위의 기간 내 가격 변동이 있으면 시황성으로 판단.
    """
    # 전체 데이터에서 자재별 가격 표준편차 계산
    price_std = (
        df.groupby(["자재명", "단위"])["현재단가"]
        .std()
        .reset_index()
        .rename(columns={"현재단가": "단가변동성"})
    )
    df = df.merge(price_std, on=["자재명", "단위"], how="left")
    df["시황성자재"] = df["단가변동성"].fillna(0) > 0
    df = df.drop(columns=["단가변동성"])
    return df


def load_supplement(filepath: Path) -> "pd.DataFrame | None":
    """
    보조 자재 단가 CSV 로드.
    조달청 데이터와 달리 이미 한국어 컬럼으로 작성된 파일.
    """
    if not filepath.exists():
        print(f"  ⚠ 보조 파일 없음 (건너뜀): {filepath.name}")
        return None

    df = pd.read_csv(filepath, encoding="utf-8-sig")
    df["현재단가"] = pd.to_numeric(df["현재단가"], errors="coerce")
    df = df[df["현재단가"] > 0].dropna(subset=["자재명", "현재단가"])
    df["자재명"] = df["자재명"].astype(str).str.strip()
    df["공시일자"] = pd.to_datetime(df["공시일자"], errors="coerce")

    # 조달청 데이터에 없는 컬럼 제거 (출처 컬럼은 내부용이므로 제외)
    df = df.drop(columns=["출처"], errors="ignore")

    # 시황성자재 기본값: 보조 데이터는 단일 시점이므로 False
    df["시황성자재"] = False

    print(f"  ✔ {filepath.name} 로드 완료 ({len(df):,}행)")
    return df


def main():
    print("=" * 50)
    print("조달청 자재 단가 데이터 전처리 시작")
    print("=" * 50)

    all_dfs = []

    # 1. 각 CSV 로드 및 정제
    for fname in CSV_FILES:
        fpath = RAW_DIR / fname
        if not fpath.exists():
            print(f"  ⚠ 파일 없음: {fname}")
            continue
        df_raw = load_csv(str(fpath))
        df_clean = preprocess(df_raw)
        all_dfs.append(df_clean)

    if not all_dfs:
        print("처리할 파일이 없습니다.")
        return

    # 2. 전체 합치기
    df_all = pd.concat(all_dfs, ignore_index=True)
    print(f"\n조달청 데이터: {len(df_all):,}행")

    # 3. 시황성 여부 판단 (전체 데이터 기준)
    df_all = add_market_sensitive_flag(df_all)

    # 4. 자재명+단위 기준 최신 단가만 남기기
    df_final = get_latest_prices(df_all)
    print(f"중복 제거 후: {len(df_final):,}개 자재")

    # 5. 보조 자재 단가 병합 (조달청에 없는 자재만 추가)
    print("\n[보조 자재 단가 병합]")
    df_supplement = load_supplement(RAW_DIR / SUPPLEMENT_FILE)
    if df_supplement is not None:
        # 조달청에 이미 있는 자재명+단위는 제외 (조달청 우선)
        existing_keys = set(zip(df_final["자재명"], df_final["단위"].fillna("")))
        mask = ~df_supplement.apply(
            lambda r: (r["자재명"], r.get("단위", "")) in existing_keys, axis=1
        )
        df_new = df_supplement[mask].copy()
        print(f"  추가된 자재: {len(df_new):,}개 (조달청 중복 제외)")

        df_final = pd.concat([df_final, df_new], ignore_index=True)

    # 6. 저장
    output_path = PROCESSED_DIR / "materials_db.csv"
    df_final.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ 저장 완료: {output_path}")
    print(f"   - 자재 종류: {len(df_final):,}개")
    print(f"   - 자재 분류: {df_final['자재분류'].nunique()}개 카테고리")
    print(f"   - 시황성 자재: {df_final['시황성자재'].sum()}개")
    print("\n분류별 자재 수:")
    print(df_final["자재분류"].value_counts().to_string())


if __name__ == "__main__":
    main()
