export interface ExampleQuestion {
  kind: '견적' | '상담';
  text: string;
}

export const EXAMPLE_QUESTIONS: ExampleQuestion[] = [
  { kind: '견적', text: '자동문 3개소 설치 비용 알려줘' },
  { kind: '견적', text: '철근콘크리트 벽체 260㎥ 펌프차 32m 붐타설 비용' },
  { kind: '상담', text: '진동기 안 쓰면 콘크리트 타설 인원이 줄어?' },
  { kind: '상담', text: 'D16 앵커에 기초앵커 품셈 써도 돼?' },
];
