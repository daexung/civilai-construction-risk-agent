export const PUBLIC_PAGE_META = {
  guide: {
    title: '건셈 사용 가이드 — 질문 작성부터 견적·품셈 근거 확인까지',
    description: '건셈의 공사비 견적과 품셈 상담 사용법. 질문 작성, 작업 범위와 조건 선택, 견적·원문 확인, 무료 이용 횟수와 Excel 다운로드를 안내합니다.',
  },
  examples: {
    title: '건셈 질문 예시 — 공사비 견적·표준품셈 상담',
    description: '자동문, 콘크리트 펌프차, 보도블록과 여러 공종의 견적 질문, 표준품셈 상담 질문을 살펴보고 내 조건에 맞게 수정해 시작하세요.',
  },
};
export type PublicPage = keyof typeof PUBLIC_PAGE_META;
