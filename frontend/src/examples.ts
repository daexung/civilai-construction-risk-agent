export interface ExampleQuestion {
  kind: '견적' | '상담';
  text: string;
}

export const EXAMPLE_QUESTIONS: ExampleQuestion[] = [
  { kind: '견적', text: '자동문 3개소를 설치하려면 비용이 얼마나 드나요?' },
  { kind: '견적', text: '철근콘크리트 벽체 260㎥를 32m 붐 펌프차로 타설하면 비용이 얼마나 드나요?' },
  { kind: '상담', text: '콘크리트 타설 시 진동기를 사용하지 않으면 작업 인원을 줄일 수 있나요?' },
  { kind: '상담', text: 'D16 앵커를 설치할 때 기초앵커 품셈을 적용해도 되나요?' },
];
