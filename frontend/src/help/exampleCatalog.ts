import { EXAMPLE_QUESTIONS } from '../examples';

export const chatExampleUrl = (question: string) => `/chat?q=${encodeURIComponent(question)}`;

export const QUESTION_EXAMPLES = [
  { id: 'automatic-door', kind: '견적', title: '자동문 설치', question: EXAMPLE_QUESTIONS[0].text,
    note: '설치할 개소 수부터 적어 보세요. 규격과 시공 조건은 확인 과정에서 보완할 수 있어요.', facts: '수량, 문 규격, 설치·철거 범위' },
  { id: 'concrete-pump', kind: '견적', title: '콘크리트 펌프차 타설', question: EXAMPLE_QUESTIONS[1].text,
    note: '타설 부위·물량·펌프차 규격을 함께 적으면 계산 조건을 확인하기 쉬워요.', facts: '타설 부위, 콘크리트 물량, 펌프차 규격' },
  { id: 'paving', kind: '견적', title: '보도블록 설치', question: '보도블록 200㎡ 설치 견적을 내주세요.',
    note: '새로 설치하는지 보수하는지, 현장 여건과 작업 범위를 이어서 확인할 수 있어요.', facts: '면적, 블록 규격, 바탕 작업 포함 여부' },
  { id: 'multiple-trades', kind: '견적', title: '여러 공종을 함께 요청', question: '다음 두 작업의 견적을 내주세요.\n1. 합판거푸집 120㎡ 설치·해체\n2. 기초 콘크리트 30㎥ 펌프차 타설',
    note: '작업마다 물량을 적고 줄을 나눠 보세요. 작업별 포함 여부와 조건을 확인한 뒤 계산합니다.', facts: '공종별 물량·단위, 포함할 작업, 공통 현장 조건' },
  { id: 'vibrator', kind: '품셈 상담', title: '장비를 쓰지 않을 때의 적용 기준', question: EXAMPLE_QUESTIONS[2].text,
    note: '작업 조건을 바꿨을 때 품셈을 어떻게 적용해야 하는지 근거와 함께 물어보세요.', facts: '공종, 실제 사용하는 장비, 바꾸려는 조건' },
  { id: 'anchor', kind: '품셈 상담', title: '이 품셈을 적용해도 될까요?', question: EXAMPLE_QUESTIONS[3].text,
    note: '알고 있는 품셈과 실제 작업의 차이를 구체적으로 적어 보세요.', facts: '자재 규격, 설치 방법, 비교할 품셈' },
  { id: 'formwork-height', kind: '품셈 상담', title: '높이에 따른 할증', question: '거푸집 품셈에서 작업 높이가 높을 때 할증은 어떤 기준으로 적용하나요?',
    note: '실제 적용 전에는 거푸집 종류·높이·양중장비 사용 여부 등 해당 조건을 확인하세요.', facts: '거푸집 종류, 작업 높이, 장비 사용 여부' },
  { id: 'scope-check', kind: '품셈 상담', title: '별도 계산해야 할 작업 확인', question: '보도블록 설치 품셈에 바탕 기층 작업도 포함되나요? 별도로 계산할 항목과 원문 근거를 알려주세요.',
    note: '품셈에 포함된 작업과 별도 계상할 작업을 구분하고 싶을 때 사용해 보세요.', facts: '확인할 공종, 포함 여부가 궁금한 작업' },
];
