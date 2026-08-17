# CivilAI Construction Risk Agent

공사 리스크 기반 추가비용 산정 AI 에이전트입니다.  
건설 현장의 기상 악화, 공정 지연, 추가 물량, 자재 단가 변화, 장비 대기 등의 리스크를 분석하고, 추가비용과 산정 근거를 공무용 리포트 형태로 제공합니다.

## Team & My Role

SK플래닛 생성형 AI 활용 데이터 엔지니어 부트캠프 · 팀 프로젝트

**담당 — 주대성**

* **주제 선정 · 도메인 리드** — 추가비용 산정이라는 주제를 제안하고, 표준품셈·일위대가 등 적산 도메인 지식을 정리해 팀에 공유. 이를 바탕으로 도메인 노드(weather · material · labor_cost · equipment) 구성을 설계·제안
* **표준품셈 · 노임단가 데이터 구축** — 표준품셈 PDF 추출·청킹·임베딩(pgvector 적재) 및 노임단가 DB 설계·구축
* **인건비(labor_cost) 노드** — 노임단가 DB 조회와 표준품셈 RAG 단위품량 fallback 기반 인건비 산정 구현
* **프론트엔드** — React·TypeScript 채팅 UI, structured response 카드 렌더링, 프로젝트별 대화 관리
* **구조화 응답 개선** — router·synthesize 노드를 보완해 최종 답변이 `structured_response` 카드(비용 내역·근거·가정)로 반환되도록 구성

**팀원 담당** — FastAPI 백엔드 · weather(기상 리스크) 노드 · equipment(장비 대기비) 노드

## 1. 프로젝트 개요

CivilAI Construction Risk Agent는 현장 공무·구매·조달·원가관리 담당자가 자연어로 질문하면, 필요한 데이터베이스·RAG·외부 API를 조회하고 추가비용 산정 리포트를 생성하는 멀티 에이전트 시스템입니다.

예시 질문:

```text
우레탄 방수 물량이 200㎡ 추가됐습니다.
계약단가 8,000원/㎡, 현재단가 8,700원/㎡, 고정단가 계약입니다.
자재비를 계산해 주세요.
````

```text
서울 문래동 콘크리트 타설 공정이 비로 인해 1일 지연될 경우,
펌프카 25m³ 장비 대기비를 산정해 주세요.
```

## 2. 핵심 특징

* LangGraph 기반 멀티 에이전트 워크플로우
* Router가 질문 의도와 도메인을 분류하고 필요한 노드만 동적 실행
* LLM은 분류·추출·설명에 사용하고, 실제 금액 계산은 deterministic service layer에서 수행
* 자재비·인건비·장비비를 도메인별 service로 분리
* PostgreSQL RDS에 정형 데이터와 pgvector 기반 벡터 데이터를 통합 관리
* 표준품셈 PDF를 임베딩해 RAG 기반 근거 검색 수행
* 기상청 KMA APIHub와 연동해 기상 리스크 및 예상 지연시간 분석
* 최종 답변은 자연어 리포트와 `structured_response` 카드 데이터로 반환

## 3. 전체 아키텍처

```text
React / TypeScript Frontend
        │
        │ HTTP
        ▼
FastAPI Backend
        │
        │ graph.stream()
        ▼
LangGraph Workflow
        │
        ├─ router_node
        ├─ extractor_node
        ├─ weather_node
        ├─ material_node
        ├─ labor_cost_node
        ├─ equipment_node
        ├─ aggregator_node
        └─ synthesize_node
        │
        ▼
PostgreSQL RDS + pgvector
Bedrock Claude / Titan Embeddings
KMA APIHub
```

## 4. LangGraph Workflow

```text
START
  ↓
router_node
  ├─ OUT_OF_DOMAIN → END
  ├─ CHAT          → synthesize_node → END
  ├─ LOOKUP        → synthesize_node → END
  ├─ CLARIFY       → synthesize_node → END
  └─ REPORT        → extractor_node
                       ├─ weather 필요
                       │    → weather_node
                       │         ├─ 비용 노드 없음 → aggregator_node
                       │         └─ 비용 노드 있음 → material/labor/equipment
                       └─ weather 불필요
                            → material/labor/equipment
                                      ↓
                               aggregator_node
                                      ↓
                               synthesize_node
                                      ↓
                                     END
```

각 노드는 서로 직접 호출하지 않고, LangGraph의 공용 `state`를 통해 입력과 결과를 공유합니다.

## 5. Cost Service Layer

비용 계산 노드는 LangGraph 연결만 담당하고, 실제 계산 흐름은 각 도메인 service가 수행합니다.

```text
material_node
  → agents/material_cost/service.py
  → material_price_tool.py / quantity_calculator.py

labor_cost_node
  → agents/labor_cost/service.py
  → labor_cost/tools.py

equipment_node
  → agents/equipment_cost/service.py
  → equipment_cost/tools.py
```

이 구조를 통해 node는 state 입출력에 집중하고, 도메인 계산 로직은 service 계층에서 관리합니다.

## 6. 비용 산정 방식

### Material Cost

자재비 service는 사용자 입력 또는 자재 단가 DB를 기반으로 추가 자재비를 계산합니다.

* 추가 물량
* 계약단가
* 현재단가
* 계약 유형
* 고정단가 여부
* 참고 차액

예시:

```text
계약단가 8,000원/㎡ × 추가 물량 200㎡ = 1,600,000원
```

고정단가 계약인 경우 현재단가와의 차액은 참고값으로 분리합니다.

### Labor Cost

인건비 service는 노임단가 DB와 표준품셈 RAG를 활용합니다.

* 사용자가 투입 인원과 작업일수를 입력한 경우: 직접 계산
* 인원 정보가 없는 경우: 표준품셈 RAG에서 단위품량을 찾아 추정
* 노임단가 DB에서 직종별 단가 조회

### Equipment Cost

장비비 service는 장비 단가 DB와 대기일수를 기반으로 장비 대기비를 계산합니다.

* 장비명 정규화
* 장비 규격 매칭
* 일대여료 조회
* 대기율 적용
* 대기일수 반영

예시:

```text
580,800원/일 × 50% × 1일 = 290,400원
```

## 7. RAG 구조

표준품셈 PDF와 내부 문서를 chunk 단위로 분리한 뒤, Amazon Titan Embeddings를 이용해 벡터화하고 PostgreSQL pgvector 테이블에 저장합니다.

```text
PDF / 문서
  → pdfplumber 텍스트·표 추출
  → 항목 번호 / 조항 단위 chunking
  → Titan Embeddings
  → PostgreSQL pgvector
  → similarity search
  → 근거 문단 반환
```

현재 RAG는 다음 용도로 사용됩니다.

* 표준품셈 기준 조회
* 인건비 단위품량 fallback
* 산정 근거 제시
* 향후 계약 조항 검색 확장

자재 단가는 RAG가 아니라 PostgreSQL 단가 테이블 조회 기반입니다.

## 8. 데이터베이스 구조

PostgreSQL에는 서비스 운영 데이터와 비용 산정 데이터를 함께 저장합니다.

주요 테이블:

* `projects`: 프로젝트 정보
* `conversations`: 프로젝트별 대화
* `messages`: 사용자/assistant 메시지 및 structured response
* `material_prices`: 자재 단가
* `labor_cost.labor_cost`: 직종별 노임단가
* `equipment_cost.equipment_rental`: 장비 임차료
* `rag.standard_spec`: 표준품셈 embedding chunk

## 9. AWS MVP Architecture

본 프로젝트는 학습 및 MVP 검증 목적으로 AWS 기반 배포 구조를 구성했습니다.

```text
User
 │
 ▼
EC2 Frontend
React + Nginx
 │
 │ /api
 ▼
EC2 Backend
FastAPI + LangGraph
 │
 ├─ AWS Bedrock
 │    ├─ Claude: routing / extraction / synthesis
 │    └─ Titan Embeddings: document embedding
 │
 ├─ KMA APIHub
 │    └─ weather forecast / risk analysis
 │
 ├─ RDS PostgreSQL
 │    ├─ service tables
 │    ├─ cost tables
 │    └─ pgvector tables
 │
 └─ Airflow Server
      └─ procurement material price batch
```

구성 요소:

| Component          | Role                                     |
| ------------------ | ---------------------------------        |
| EC2 Frontend       | React 정적 파일을 Nginx로 서비스            |
| EC2 Backend        | FastAPI 서버와 LangGraph workflow 실행   |
| RDS PostgreSQL     | 프로젝트, 대화, 메시지, 단가 DB, pgvector 저장 |
| AWS Bedrock Claude | 질문 분류, 입력값 추출, 최종 리포트 생성          |
| AWS Bedrock Titan  | 표준품셈 및 문서 embedding 생성            |
| KMA APIHub         | 기상 예보 조회                          |
| Airflow            | 자재 단가 배치 수집 및 적재                  |

현재 구조는 MVP 검증과 발표용 배포를 위해 구성한 형태입니다.

## 10. Cost-Optimized Operation Plan

장기 운영 시에는 비용 절감을 위해 더 가벼운 구조로 전환할 수 있습니다.

예상 전환 방향:

| MVP Architecture | Cost-Optimized Alternative                    |
| ---------------- | --------------------------------------------- |
| EC2 Frontend     | Vercel / Cloudflare Pages                     |
| EC2 Backend      | Render / Fly.io / Railway / 단일 저사양 VPS        |
| RDS PostgreSQL   | Supabase PostgreSQL / Neon PostgreSQL         |
| Airflow Server   | GitHub Actions Cron / Cloudflare Workers Cron |
| Bedrock          | 사용량 기반 LLM API                                |
| pgvector on RDS  | Supabase/Neon pgvector 유지                     |

AWS 기반 MVP 구조는 실제 배포 경험을 보여주기 위한 구성이며, 운영 단계에서는 트래픽과 비용에 맞춰 단순화할 수 있습니다.

## 11. Security

사용자 입력에 대해 프롬프트 인젝션 방어를 적용했습니다.

* 유니코드 정규화
* 전각 문자 및 특수 공백 정규화
* 위험 패턴 정규식 검사
* “이전 지시를 무시해라”, “시스템 프롬프트를 출력해라”, “API 키를 보여줘라” 등 차단
* Router 및 주요 노드 진입 전 공통 보안 검사 수행

## 12. Frontend

React와 TypeScript 기반 채팅 UI를 제공합니다.

주요 기능:

* 로그인
* 일반 대화
* 프로젝트별 대화
* structured response 카드 렌더링
* 비용 내역, 근거, 가정, 누락 정보 표시
* 프로젝트 생성 및 대화 히스토리 관리

## 13. Directory Structure

```text
.
├── agents/
│   ├── router/
│   ├── material_cost/
│   ├── labor_cost/
│   ├── equipment_cost/
│   └── weather_risk/
├── api/
├── db/
├── dags/
├── rag/
├── frontend/
│   └── client/
├── scripts/
├── evals/
└── common/
```

| Path                     | Description                               |
| ------------------------ | ----------------------------------------- |
| `agents/router/`         | LangGraph workflow, router, nodes, state  |
| `agents/material_cost/`  | 자재비 service, tool, calculator             |
| `agents/labor_cost/`     | 인건비 service, 노임단가/RAG tools               |
| `agents/equipment_cost/` | 장비비 service, 장비 단가 tools                  |
| `agents/weather_risk/`   | KMA API client, parser, risk rule engine  |
| `api/`                   | FastAPI app, routers, auth, DB connection |
| `db/`                    | DB initialization and migrations          |
| `dags/`                  | Airflow DAGs                              |
| `rag/`                   | embedding and vector search               |
| `frontend/client/`       | React + TypeScript frontend               |
| `evals/`                 | evaluation cases and runners              |
| `scripts/`               | smoke test and utility scripts            |

## 14. Tech Stack

### Backend

* Python 3.11
* FastAPI
* LangGraph
* LangChain
* PostgreSQL
* pgvector
* AWS Bedrock
* boto3

### Frontend

* React
* TypeScript
* Nginx
* Docker

### Data / Infra

* PostgreSQL RDS
* Airflow
* KMA APIHub
* Amazon Titan Embeddings
* Claude on Bedrock

## 15. Environment Variables

실제 secret은 포함하지 않습니다. `.env.example`을 참고해 로컬 환경에서 설정합니다.

```env
# PostgreSQL
DB_HOST=
DB_PORT=5432
DB_NAME=construction_risk_agent
DB_USER=
DB_PASSWORD=

# AWS Bedrock
AWS_BEDROCK_REGION=
AWS_BEARER_TOKEN_BEDROCK=
BEDROCK_MODEL_ID=
MODEL_ROUTER=
MODEL_EXTRACTOR=
MODEL_SYNTHESIZE=
MODEL_ID=

# KMA APIHub
KMA_API_KEY=
KMA_VILAGE_FCST_URL=
KMA_ULTRA_SRT_NCST_URL=

# Auth
JWT_SECRET_KEY=
```

## 16. Local Setup

### Backend

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

python db/run_migrations.py

uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

API 문서:

```text
http://localhost:8000/docs
```

### Frontend

```bash
cd frontend/client
npm install
npm start
```

Frontend:

```text
http://localhost:3000
```

### Docker

```bash
docker build -f Dockerfile.backend -t civilai-risk-agent-backend .
docker run -p 8000:8000 --env-file .env civilai-risk-agent-backend
```

## 17. Evaluation

라우팅 및 주요 시나리오 검증:

```bash
python agents/router/test_routing.py
```

평가 케이스 실행:

```bash
python evals/run_eval.py
```

Chat API smoke test:

```bash
python scripts/smoke_chat_api.py --base-url http://localhost:8000 --conv-id <conversation_id>
```

## 18. Example Output

```text
추가비용 리포트

우레탄 방수 200㎡ 추가에 따른 자재비는 1,600,000원입니다.
고정단가 계약이므로 계약단가 8,000원/㎡을 적용했습니다.

산출식:
8,000원/㎡ × 200㎡ = 1,600,000원

참고:
현재단가 8,700원/㎡와의 차액 140,000원은 고정단가 정산에 반영하지 않습니다.
```

## 19. Limitations

* 현재는 발표 및 MVP 검증 중심의 공종을 우선 지원합니다.
* 표준품셈 전체 공종 자동 산정은 향후 확장 대상입니다.
* 기상 분석은 KMA API 응답과 프로젝트 위치 정보에 의존합니다.
* 계약문서 RAG는 구조 설계 및 샘플 기반이며, 실제 사내 문서 적용 시 보안 검토가 필요합니다.
* 산정 결과는 의사결정 보조용이며, 실제 변경계약에는 발주처 기준과 계약 조항 검토가 필요합니다.

## 20. Future Work

* 표준품셈 전체 공종 확장
* 계약서 RAG 고도화
* 프로젝트 컨텍스트 기반 장기 메모리 개선
* LangGraph checkpoint 적용
* 비용 산정 partial report 고도화
* 저비용 운영 인프라 전환
* 테스트 커버리지 확대
* CI/CD 자동 배포 구성

## 21. Notes

이 레포지토리는 포트폴리오 공개용으로 정리한 버전입니다.
실제 API Key, DB 접속 정보, 원본 계약 문서, 민감 데이터는 포함하지 않습니다.

