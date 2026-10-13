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

Google 속성을 추가했고 네이버 이용약관 동의와 보안문자 입력은 사용자의 별도 승인을 받아 진행했다. 배포 뒤 소유권 확인과 사이트맵 제출까지 완료했다. 등록은 검색 노출이나 순위를 보장하지 않는다.

## 머지 전 검증

- 모델·DB를 사용하지 않는 로컬 답변 및 키 라우팅 검사: 52개 통과.
- 화면과 기존 동작 검사: 11개 묶음, 71개 통과.
- 프론트 운영 빌드 성공. 로컬 설치 의존성의 소스 맵 경고가 있으나 소스 오류는 없다.
- 제출 파일의 비밀 키 형식·대용량 산출물·원문 이미지 포함 점검과 `git diff --check` 통과.

기본 옵션은 꺼짐이며 운영 백엔드는 로컬 시험 라우터를 붙이지 않는다. main 머지는 기존 배포 워크플로를 실행할 수 있지만 새 RAG 릴리스가 운영 상담에 적용된 것으로 보고하지 않는다.

## 머지와 배포 결과

- [PR #33](https://github.com/daexung/civilai-construction-risk-agent/pull/33)을 머지했다. 제출 커밋은 `6822c8c40125ce885447ab07380ef5a077f51c5e`, main 머지 커밋은 `54e4253b673625bb50e43fe49c004c176cac5914`다.
- Vercel 운영 배포와 [백엔드 배포](https://github.com/daexung/civilai-construction-risk-agent/actions/runs/38431296543)가 성공했다. 공개 `/api/ready` 응답은 `{"status":"ok"}`다.
- 홈페이지, `robots.txt`, `sitemap.xml`은 모두 200 응답이다. 공개 홈페이지에 두 검색엔진 확인 태그가 있고, `/chat`의 색인 제외 헤더도 확인했다.
- 검색 개발 코드와 로컬 시험 경로는 Git에 저장됐지만 운영 `/api/chat`의 새 검색 전환은 하지 않았다. 로컬 시험 옵션은 기본 꺼짐이다.
- 진행 중인 다중 공종 PR #21은 이번 머지 대상이 아니며 그대로 남겼다.

## 검색엔진 등록 결과

| 대상 | 실제 완료 | 남은 상태 |
|---|---|---|
| Google Search Console | `https://poomsemi.vercel.app/` 소유권 확인, 사이트맵 제출, 화면의 `사이트맵 처리 완료`와 발견된 페이지 1개 확인 | 홈페이지 수동 색인 요청은 일일 할당량 초과로 처리되지 않음. 사이트맵 제출은 완료 상태이며 검색 색인은 대기 |
| 네이버 서치어드바이저 | 사이트 소유권 확인, `sitemap.xml` 제출, 홈페이지 `/` 수집 요청 | 실제 수집과 검색 노출은 대기 |

네이버 사이트맵 등록 시간은 2026-10-14 01:40:13, 홈페이지 수집 요청 기록은 01:41:47이다. Google 한도를 피하기 위한 계정 변경이나 반복 요청은 하지 않았다. 자동 재요청도 설정하지 않았다.

등록 화면 증빙은 로컬 `tmp/seo-registration/google-sitemap.jpg`와 `naver-sitemap.jpg`에 보존했다. 계정 정보가 보일 수 있는 화면 사진은 Git에 넣지 않았다.

이번 완료는 코드 보존·머지·배포와 검색엔진 등록이다. 새 검색의 운영 상담 적용이나 다중 공종 견적 완성을 뜻하지 않는다.

## 참고

- [Google 사이트맵 제출](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap)
- [네이버 소유권 확인](https://searchadvisor.naver.com/guide/faq-start-register)
- [Vercel 경로 응답 헤더](https://vercel.com/docs/project-configuration/vercel-json)
