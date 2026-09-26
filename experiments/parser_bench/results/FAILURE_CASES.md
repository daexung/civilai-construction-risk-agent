# 파서 비교 실험 기록 (5개 정답 표)

기록일: 2026-09-24 · 정답: `evals/golden_tables/` T1~T5 · 채점: `score.py` (층 A 원시 구조 / 층 B 레코드·노무량)
기존 `pipeline/parse.py`와 `evals/golden_parse.json`·`golden_estimate.json`은 수정하지 않았다. 층 B는 운영 조립 로직을 import해 그대로 쓴다.

## 실행 목록

| 결과 폴더 | 파서 | 설정 | 버전 | 실행 시간 (4쪽) |
|---|---|---|---|---|
| `pymupdf` | PyMuPDF | `find_tables()` 기본값, 병합은 셀 좌표로 복원 | 1.28.2 | 0.9초 (프로세스 안) |
| `docling_accurate` | Docling | TableFormer ACCURATE, 셀 매칭 켬, OCR 끔, CPU | 2.130.0 | 초기화 114.7초(첫 실행, 모델 내려받기 포함) + 쪽당 12.7~17.9초 |
| `docling_accurate_nomatch` | Docling | 위와 같고 셀 매칭 끔 | 2.130.0 | 초기화 34.2초 + 쪽당 14.3~27.1초 |
| `odl_local` | OpenDataLoader | local, table-method default, keep-line-breaks | 2.5.11 / Temurin 21.0.12 | 5.5초 (JVM 기동 포함) |
| `odl_local_cluster` | OpenDataLoader | local, table-method cluster | 2.5.11 | 5.5초 |
| `odl_hybrid_auto` | OpenDataLoader | hybrid docling-fast, 분기 auto | 2.5.11 + 백엔드 Docling 2.130.0 | 서버 기동 44.8초 + 52.8초 |
| `odl_hybrid_full` | OpenDataLoader | hybrid docling-fast, 분기 full | 같음 | 서버 기동 44.8초 + 54.2초 |
| `paddle_vl16` | PaddleOCR-VL | 파이프라인 v1.6, CPU, Paddle 네이티브 추론 | paddleocr 3.7.0 / paddlex 3.7.2 / paddlepaddle 3.2.1 | **실행 불가 — 정확도 미측정.** 초기화 276초 + 193쪽 추론 약 302초 후 미완료로 중단 |

설치: Docling 전용 환경 837초·1.5GB. OpenDataLoader hybrid 추가 설치 725초. JRE는 시스템 설치 없이 `.venv-odl/jre`에 압축본을 풀어 사용.

### hybrid 백엔드는 Docling이다

- `opendataloader-pdf[hybrid]` 의존성: `docling[easyocr]>=2.126,<3`, fastapi, uvicorn.
- 백엔드 서버(`opendataloader_pdf/hybrid_server.py`)는 Docling `DocumentConverter`를 `TableStructureOptions(mode=ACCURATE)`로 만든다. 셀 매칭은 Docling 기본값(켬).
- 이번 실험의 백엔드 Docling 버전(2.130.0, core 2.98.0, ibm-models 4.0.3, torch 2.14.0)은 `docling_accurate`와 같다.
- 서버는 `--no-ocr --device cpu`로 띄웠다(서버 기본값은 EasyOCR 켬). 디지털 원문이고 `docling_accurate`와 조건을 맞추기 위함.
- 각 `tables.json`의 `config.hybrid_backend`, `config.hybrid_backend_note`, `server`에 같은 내용을 남겼다. 서버 로그: `odl_hybrid_server.log`.

## 실패 사례

근거 파일은 `results/<실행>/raw/`(원시 출력), `results/<실행>/tables.json`(공통 형식), `results/<실행>/scores.json`(채점 상세)이다.

### Docling (셀 매칭 켬) — `docling_accurate`
- **T1이 두 표로 쪼개짐.** 본표(IoU 0.51)와 비고 안 중첩 표가 별개 표로 나온다. 본표는 3행뿐이고, 장비사용 행에서 콘크리트공·보통인부·굴착기가 한 칸에 합쳐진다. 단위와 수량이 `인3 인1 대`처럼 한 칸에 붙는다.
- **T2 글자가 옆 칸으로 샘.** 행 분리와 펌프차 가로 병합(1×2)은 맞게 인식했지만, 단위가 값 칸에 붙고(`인 3`, `대 1대(80㎥/hr 이상)`) 특별인부가 한 열 밀린다.
- **T5 자간 라벨이 열마다 흩어짐.** 행 분리는 성공했지만 `형 | 명 틀 | 칭 목 | 공`처럼 균등배분 글자가 여러 열로 갈라진다. 표 밖 `(100㎡당)`이 표 안 머리글로 들어온다.
- **T3 비고 문장이 여러 칸으로 찢어짐.**

### Docling (셀 매칭 끔) — `docling_accurate_nomatch`
- **칸 구조는 나오지만 글자가 대부분 빈 문자열.** T4 머리글 `7∼9층`~`16∼18층`, T2 직종 라벨 전부가 비어 있다. 이 문서 특성인지 설정 문제인지는 확인하지 않았다.

### OpenDataLoader local — `odl_local`, `odl_local_cluster`
- **괄호 글리프가 값과 한 줄로 붙음(T3).** 도장공 칸이 `⌉⌋ 0.12인`으로 나온다. 운영 `clean_cell()`은 괄호만 있는 줄만 지우므로 괄호가 레코드에 남고, 기존 골든 `6-1-5 Epoxy 접착제`(괄호 금지 조건)가 실패한다. 값 자체는 맞다. 파서 교체 시 조립 휴리스틱이 깨지는 사례.
- **불규칙한 자간(T3 둘째 라벨).** `기타 접 착제 바르 기`처럼 한 글자·두 글자가 섞여, 한 글자씩 띄어 쓴 줄만 붙이는 운영 규칙이 적용되지 않는다. 공백 무시 비교에서는 통과한다.
- default와 cluster의 결과가 5개 표에서 완전히 같았다.

### OpenDataLoader hybrid — `odl_hybrid_auto`, `odl_hybrid_full`
- **auto 분기가 4쪽 모두 백엔드로 보냄.** 콘솔 로그 `Triage summary: JAVA=0, BACKEND=1`이 네 번 나온다. 그래서 auto와 full의 결과가 같다.
- **같은 버전 Docling 단독보다 낮음.** Java 쪽이 Docling이 예측한 칸 위치에 자기가 뽑은 글자 조각을 다시 배정하는 과정에서 머리글과 첫 행이 섞이고(T3 `구 분 신 구 - 콘 크`), 글자가 옆 열로 밀린다(T2 `배관타설`). T4만 Docling 단독과 셀 구조가 같다.

### PaddleOCR-VL 1.6 (CPU) — `paddle_vl16` · 실행 불가, 정확도 미측정
- **이 노트북의 CPU 환경에서 1쪽도 완료하지 못했다.** 상세 수치는 `paddle_vl16/RUN_STATUS.json`.
- 환경: i5-10210U(4코어 8스레드), RAM 7.8GB(시작 시 가용 0.9GB), 페이지 파일 10GB. GPU(MX250 2GB)는 쓰지 않았다.
- 모델: PaddleOCR-VL-1.6 0.9B(저장 bfloat16, 1.8GB) + PP-DocLayoutV3(126MB). 추론 엔진은 Paddle 네이티브(`paddle_dynamic`).
- 초기화 276초(모델 캐시 사용, 내려받기 없음). 최대 커밋 메모리 **9.1GB**, 최대 상주 3.7GB, 페이지 폴트 788만 회.
- 193쪽 추론 약 302초 동안 초당 페이지 폴트 **약 11만 회**. 578초 경과에 CPU 누적 407초라 연산보다 디스크 대기가 지배적이었다.
- 사용자 지시로 16:08:15에 중단. 중단 후 시스템 가용 메모리 612MB → 2,123MB.
- 1차 시도는 PaddleOCR-VL이 아니라 **실험 스크립트의 메모리 측정 코드 오류**(ctypes 핸들 타입)로 추론 전에 종료됐다. 이때 로그는 2차 시도가 같은 파일명에 덮어써서 남지 않았고, 핵심 내용은 `RUN_STATUS.json`에 옮겨 적었다.
- 결론: 이 결과는 정확도 근거가 아니라 실행 가능성 기록이다. 숫자·단위 오독 점검(`token_audit.json`)도 출력이 없어 미측정이다.

### 모든 설정에서 풀리지 않은 것
- **가로선 없는 병합(unruled) 23·20**: 원시 구조 0/4. 행이 분리되지 않으면 확인할 수 없다.
- **T3 해석 I1(작업유형당 1회 계상)**: 0/2. 파서가 아니라 조립 로직의 값 복제 규칙 문제다.

## 비교 공정성 점검 (2026-09-24)

1. **원본 PDF vs 단쪽 PDF**: 7개 설정 모두 5개 표의 셀 위치·병합·글자가 완전히 같고 점수도 같다(`source_comparison.json`). 이후 채점은 운영과 같은 조건인 원본 PDF 결과(`__fullpdf`, PyMuPDF는 `pymupdf`)를 기준으로 한다. 처리 시간은 달랐다: ODL local 5.5초 → 14.6초(982쪽 PDF를 여는 비용), ODL hybrid 53초 → 113~126초(원본 PDF 전체를 백엔드로 보냄).
2. **글자 누락 판정**: 부분 문자열 판정을 버리고, 칸 안의 연속된 어절이 정답과 정확히 같을 때만 보존으로 센다. 띄어쓰기 없이 붙은 어절(`인3`)은 원문 칸들로 정확히 분해될 때만 인정하고, 숫자만으로 된 어절은 분해하지 않는다. 같은 행의 칸을 이어 복원되는 경우는 '칸 경계에서 쪼개짐'으로 따로 센다.
3. **레코드 실패 분류**: 형식(괄호·공백 등 표기만 다름) / 값 오류(같은 열에 다른 값) / 구조(행·열을 못 찾거나 값이 없음)로 나눈다. 기존 골든 해당분과 노무량 사례에도 같은 분류를 붙인다.
4. **빈 칸 표기 통일**: 파서마다 `None`과 `''`로 다른 빈 칸을 어댑터에서 `None`으로 맞췄다. 5표 점수 변화 없음.

재채점 결과 요약(원본 PDF 기준): PyMuPDF와 ODL local의 차이는 **형식 1건**(ODL이 괄호 글리프를 값과 한 줄로 줌)뿐이고 값·구조 오류는 둘 다 0건이다. Docling·ODL hybrid의 실패는 대부분 구조 유형이다.

## 별도 검증 세트 (PyMuPDF vs ODL local)

기존 5표 밖 10쪽·22표. 상세는 `validation/ADJUDICATION.md`.
- 함께 찾은 표 20개 중 17개가 완전히 같다.
- ODL 우세 3건: 세로선 없는 표에서 PyMuPDF가 값 열을 통째로 잃음(180쪽), 가로선 없는 12행을 PyMuPDF가 한 칸에 쌓아 조립 후 11행에 틀린 조건이 붙음(885쪽), 아래첨자 분리(500쪽).
- PyMuPDF 우세 2건: 대각선 머리칸 표 2개를 ODL이 표로 인식하지 못함(396·500쪽).

## 실험자 오류와 정정

1. **ODL 변환 코드가 `list items`를 따라가지 않았다.** 그래서 처음 실행에서 T4를 못 찾고 T1 비고 두 문장이 빠졌다. 원시 JSON에는 모두 있었다(T1 비고 칸 안의 목록, [주] ② 목록 항목 안의 T4 표). 코드를 고친 뒤 다시 추출했다. 이 오류를 ODL 안전 필터 탓으로 잘못 짐작해 필터를 끈 진단 실행 두 번을 했는데, 잘못된 전제였으므로 결과 폴더를 지웠다.
2. **표를 못 찾으면 그 표의 문항이 분모에서 빠졌다.** 이 때문에 ODL local 기대값이 49/49처럼 보였다. 빈 표로 채점해 전부 실패로 세도록 고쳤다.
3. **텍스트 보존 지표가 병합 칸 안의 줄바꿈 분할을 누락으로 셌다.** 칸 안에 글자가 이어져 있으면 '합쳐진 칸 안'으로 세도록 고쳤다. 이 정정으로 앞서 보고한 Docling 누락이 셀 매칭 켬 50→14, 끔 74→45로 바뀌었다.
4. **숫자·단위 오독 점검(`audit_tokens.py`) 초안의 오류 두 가지.** 공백을 모두 지우고 숫자를 세서 쌓인 칸의 `0.12`와 `0.02`가 `0.120.02`로 붙어 누락처럼 보였고, 정답 토큰의 일부인 변형(`㎥/h` ⊂ `㎥/hr`)을 오독으로 셌다. 숫자는 공백을 구분자로 남기고, 부분 변형은 정답 등장분을 빼도록 고쳤다. 고친 뒤 PyMuPDF·Docling·ODL 모두 지정 토큰의 오독·표기 변형은 0건이다(Docling 셀 매칭 끔의 185쪽 값 누락만 있음).
5. **PaddleOCR-VL 실험 스크립트의 메모리 측정 오류.** ctypes로 64비트 프로세스 핸들을 넘길 때 타입을 선언하지 않아 1차 시도가 추론 전에 종료됐다. 타입을 선언해 고쳤다. 1차 로그는 덮어써져 남지 않았다.
