# 검색 개발 기록 머지와 검색엔진 등록

작성일: 2026-10-14

## 머지 범위

최종 파싱 PR #32는 이미 머지됐다. 이후 원문 색인·청킹·임베딩·근거 선택·검증 코드와 단계별 계획·평가 기록, 기본 꺼짐인 로컬 서비스 시험 경로를 새 PR에 저장한다. 검색 구현은 현재 로컬 검증 DB를 사용한다. 운영 상담 경로의 새 검색 전환은 이번 범위가 아니다.

고정 질문·기대값·최종 설정·요약·해시는 Git에 보관한다. 약 2MB의 코드와 문서만 제출하고, 원문 출력·벡터·모델 응답·기준선·로그·쪽 이미지는 로컬에 보존한다. `.claude/`와 환경 변수 파일은 제출하지 않는다. Git 보존 범위는 `experiments/retrieval-v1/.gitignore`와 README에 기록했다.

## 공개 사이트 검색 준비

대상은 현재 공개 서비스 `https://poomsemi.vercel.app/`다.

- Google Search Console과 네이버 서치어드바이저의 홈페이지 소유권 확인 메타 태그.
- 홈페이지 선호 주소·공유 제목/설명·WebSite 구조 자료.
- `robots.txt`와 홈페이지 한 개를 포함한 `sitemap.xml`.
- 상담·인증·로컬 시험·약관·개인정보 경로에 검색 색인 제외 응답 헤더. 상담·인증·시험 API는 사이트맵에 넣지 않는다.

Google 속성을 추가했고 네이버 이용약관 동의는 사용자의 별도 승인을 받아 진행했다. 실제 소유권 확인과 사이트맵 제출 결과는 배포 뒤 확인해 추가 기록한다. 등록은 검색 노출이나 순위를 보장하지 않는다.

## 머지 전 검증

- 모델·DB를 사용하지 않는 로컬 답변 및 키 라우팅 검사: 52개 통과.
- 화면과 기존 동작 검사: 11개 묶음, 71개 통과.
- 프론트 운영 빌드 성공. 로컬 설치 의존성의 소스 맵 경고가 있으나 소스 오류는 없다.
- 제출 파일의 비밀 키 형식·대용량 산출물·원문 이미지 포함 점검과 `git diff --check` 통과.

기본 옵션은 꺼짐이며 운영 백엔드는 로컬 시험 라우터를 붙이지 않는다. main 머지는 기존 배포 워크플로를 실행할 수 있지만 새 RAG 릴리스가 운영 상담에 적용된 것으로 보고하지 않는다.

## 참고

- [Google 사이트맵 제출](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap)
- [네이버 소유권 확인](https://searchadvisor.naver.com/guide/faq-start-register)
- [Vercel 경로 응답 헤더](https://vercel.com/docs/project-configuration/vercel-json)
