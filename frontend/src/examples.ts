export interface ExampleQuestion {
  label: string;
  text: string;
}

export const EXAMPLE_QUESTIONS: ExampleQuestion[] = [
  {
    label: '한 번에 계산',
    text: '철근콘크리트 벽체 260㎥ 펌프차 32m 붐타설 슬럼프 15cm 시설유형 Type-Ⅱ 현장조건 Type-Ⅱ 진동기 사용 재셋팅 없음 레미콘 관급 비용 알려줘',
  },
  {
    label: '되묻기 흐름',
    text: '철근콘크리트 벽체 260㎥ 펌프차로 타설 비용',
  },
  {
    label: '보류',
    text: '철근콘크리트 벽체 260㎥ 펌프차 32m 붐타설 슬럼프 15cm 시설유형 Type-Ⅱ 현장조건 Type-Ⅱ 진동기 사용 재셋팅 있음 레미콘 관급 비용 알려줘',
  },
  {
    label: '근거만(계산 지원 전)',
    text: '합판거푸집 설치 인건비',
  },
];
