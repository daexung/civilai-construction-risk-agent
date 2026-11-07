export interface ExampleQuestion {
  kind: '견적' | '상담';
  text: string;
}

export const EXAMPLE_QUESTIONS: ExampleQuestion[] = [
  { kind: '견적', text: '자동문 3개소 설치비 견적 내주세요' },
  { kind: '견적', text: '벽체 콘크리트 260㎥를 32m 펌프카로 타설하면 얼마예요?' },
  { kind: '상담', text: '진동기 없이 콘크리트를 타설하면 인원을 줄여도 되나요?' },
  { kind: '상담', text: 'D16 앵커 설치에 기초앵커 품셈을 써도 되나요?' },
];
