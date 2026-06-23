import { v4 as uuidv4 } from 'uuid';
import { User, UserRole, AuthResponse, Project, ProjectMember, ProjectRole, Conversation, Message } from './types';

export const MOCK_MODE = process.env.REACT_APP_MOCK_MODE === 'true';

// ── Mock 사용자 ────────────────────────────────────────────────
export const MOCK_USERS: Record<string, User & { password: string }> = {
  'admin@example.com': {
    user_id: 'u-admin',
    name: '관리자',
    email: 'admin@example.com',
    role: 'admin' as UserRole,
    password: '1234',
  },
  'user@example.com': {
    user_id: 'u-user',
    name: '홍길동',
    email: 'user@example.com',
    role: 'user' as UserRole,
    password: '1234',
  },
};

export function mockLogin(email: string, password: string): AuthResponse | null {
  const found = MOCK_USERS[email];
  if (!found || found.password !== password) return null;
  const { password: _, ...user } = found;
  return { ...user, token: `mock-token-${user.user_id}` };
}

// ── Mock 멤버 ──────────────────────────────────────────────────
export const MOCK_MEMBERS: Record<string, ProjectMember[]> = {
  p1: [
    { user_id: 'u-admin', name: '관리자', email: 'admin@example.com', project_role: 'owner' },
    { user_id: 'u-user',  name: '홍길동', email: 'user@example.com',  project_role: 'member' },
  ],
  p2: [
    { user_id: 'u-admin', name: '관리자', email: 'admin@example.com', project_role: 'owner' },
  ],
};

export async function mockFetchMembers(projectId: string): Promise<ProjectMember[]> {
  await new Promise(r => setTimeout(r, 300));
  return JSON.parse(JSON.stringify(MOCK_MEMBERS[projectId] ?? []));
}

export async function mockAddMember(projectId: string, email: string, role: ProjectRole): Promise<ProjectMember> {
  await new Promise(r => setTimeout(r, 500));
  const found = Object.values(MOCK_USERS).find(u => u.email === email);
  if (!found) throw new Error('등록된 사용자를 찾을 수 없습니다.');
  const list = MOCK_MEMBERS[projectId] ?? [];
  if (list.some(m => m.email === email)) throw new Error('이미 프로젝트에 참여 중인 사용자입니다.');
  const { password: _, ...user } = found;
  const member: ProjectMember = { ...user, project_role: role };
  if (!MOCK_MEMBERS[projectId]) MOCK_MEMBERS[projectId] = [];
  MOCK_MEMBERS[projectId].push(member);
  return member;
}

export async function mockRemoveMember(_projectId: string, _userId: string): Promise<void> {
  await new Promise(r => setTimeout(r, 300));
}

// ── Mock 프로젝트 ──────────────────────────────────────────────
export const MOCK_PROJECTS: Project[] = [
  {
    id: 'p1',
    name: '서울 아파트 신축',
    site_name: '강남 현장',
    address: '서울특별시 강남구 삼성동',
    latitude: 37.5125,
    longitude: 127.0596,
    work_type: '철근콘크리트',
    start_date: '2026-04-01',
    end_date: '2026-12-31',
    description: '강남구 삼성동 35층 주거복합',
    created_by: 'u-admin',
    created_by_name: '관리자',
    my_project_role: 'owner',
    created_at: '2026-06-01T09:00:00',
    updated_at: '2026-06-01T09:00:00',
  },
  {
    id: 'p2',
    name: '부산 도로 포장',
    site_name: '해운대 현장',
    address: '부산광역시 해운대구 우동',
    latitude: 35.1631,
    longitude: 129.1636,
    work_type: '아스팔트 포장',
    start_date: '2026-06-10',
    end_date: '2026-09-30',
    description: '해운대구 우동 2차선 확장',
    created_by: 'u-admin',
    created_by_name: '관리자',
    my_project_role: 'owner',
    created_at: '2026-06-10T09:00:00',
    updated_at: '2026-06-10T09:00:00',
  },
];

// ── Mock 일반 대화 ─────────────────────────────────────────────
export const MOCK_QUICK_CONVS: Conversation[] = [
  {
    id: 'q1',
    project_id: null,
    owner_id: 'u-admin',
    owner_name: '관리자',
    title: '철골 세우기 인건비 산출해줘',
    visibility: 'private',
    can_write: true,
    message_count: 2,
    created_at: '2026-06-17T10:00:00',
    updated_at: '2026-06-17T10:05:00',
  },
  {
    id: 'q2',
    project_id: null,
    owner_id: 'u-admin',
    owner_name: '관리자',
    title: '콘크리트 타설 단가 알려줘',
    visibility: 'private',
    can_write: true,
    message_count: 2,
    created_at: '2026-06-16T14:00:00',
    updated_at: '2026-06-16T14:03:00',
  },
];

// ── Mock 프로젝트 대화 ─────────────────────────────────────────
export const MOCK_PROJECT_CONVS: Record<string, Conversation[]> = {
  p1: [
    {
      id: 'pc1',
      project_id: 'p1',
      owner_id: 'u-admin',
      owner_name: '관리자',
      title: '6월 기상 리스크 분석',
      visibility: 'project_shared',
      can_write: true,
      message_count: 2,
      created_at: '2026-06-15T09:00:00',
      updated_at: '2026-06-15T09:10:00',
    },
    {
      id: 'pc2',
      project_id: 'p1',
      owner_id: 'u-user',
      owner_name: '홍길동',
      title: '타워크레인 점검 일정',
      visibility: 'project_shared',
      can_write: false,
      message_count: 2,
      created_at: '2026-06-14T11:00:00',
      updated_at: '2026-06-14T11:08:00',
    },
  ],
  p2: [
    {
      id: 'pc3',
      project_id: 'p2',
      owner_id: 'u-admin',
      owner_name: '관리자',
      title: '아스팔트 자재 가격 조회',
      visibility: 'project_shared',
      can_write: true,
      message_count: 2,
      created_at: '2026-06-12T15:00:00',
      updated_at: '2026-06-12T15:05:00',
    },
  ],
};

// ── Mock 메시지 ────────────────────────────────────────────────
export const MOCK_MESSAGES: Record<string, Message[]> = {
  q1: [
    { id: 'm-q1-1', conversation_id: 'q1', role: 'user', content: '철골 세우기 인건비 산출해줘', agent: null, created_at: '2026-06-17T10:00:00' },
    {
      id: 'm-q1-2', conversation_id: 'q1', role: 'assistant', agent: 'labor',
      content: `## 철골 세우기 직접노무비 산출\n\n**기준: 2024년 표준품셈 (건축공사 편)**\n\n### 작업 단위: 1톤(ton) 기준\n\n| 직종 | 품 | 단가(원/일) | 금액(원) |\n|------|----|-----------|---------|\n| 특별인부 | 0.20 | 245,000 | 49,000 |\n| 보통인부 | 0.30 | 185,000 | 55,500 |\n| 철근공 | 0.50 | 310,000 | 155,000 |\n| **합계** | | | **259,500** |\n\n---\n\n### 주요 할증 사항\n\n- 층고 20m 초과 시 **+15%** 적용\n- 야간 작업 시 **+25%** 적용\n- 겨울철(12~2월) 한랭 할증 **+5~10%** 적용 가능\n\n> 위 단가는 직접노무비만 포함하며, 간접노무비·경비·재료비는 별도 산출이 필요합니다.`,
      created_at: '2026-06-17T10:01:00',
    },
  ],
  q2: [
    { id: 'm-q2-1', conversation_id: 'q2', role: 'user', content: '콘크리트 타설 단가 알려줘', agent: null, created_at: '2026-06-16T14:00:00' },
    {
      id: 'm-q2-2', conversation_id: 'q2', role: 'assistant', agent: 'labor',
      content: `## 콘크리트 타설 직접노무비\n\n**기준: 2024년 표준품셈**\n\n| 구분 | 단위 | 품 | 노무비(원) |\n|------|------|----|----------|\n| 슬래브 타설 | m³ | 0.42 | 77,700 |\n| 기둥·벽체 타설 | m³ | 0.55 | 101,750 |\n| 기초 타설 | m³ | 0.35 | 64,750 |\n\n- 펌프카 사용 시 장비비 별도 산출\n- 레미콘 재료비는 포함되지 않습니다`,
      created_at: '2026-06-16T14:02:00',
    },
  ],
  pc1: [
    { id: 'm-pc1-1', conversation_id: 'pc1', role: 'user', content: '이번 주 기상 리스크 분석해줘', agent: null, created_at: '2026-06-15T09:00:00' },
    {
      id: 'm-pc1-2', conversation_id: 'pc1', role: 'assistant', agent: 'weather',
      content: `## 6월 3주차 기상 리스크 분석\n\n### 현장: 서울 강남구 삼성동\n\n| 날짜 | 날씨 | 기온 | 풍속 | 리스크 |\n|------|------|------|------|--------|\n| 6/16 (월) | 맑음 | 28°C | 3m/s | **낮음** |\n| 6/17 (화) | 구름 | 26°C | 5m/s | **낮음** |\n| 6/18 (수) | 소나기 | 23°C | 8m/s | **중간** |\n| 6/19 (목) | 흐림 | 25°C | 6m/s | **낮음** |\n| 6/20 (금) | 맑음 | 29°C | 4m/s | **낮음** |\n\n### 리스크 요약\n\n- **수요일 소나기** 예보로 콘크리트 타설 작업 재검토 권장\n- 풍속 8m/s 구간 타워크레인 작업 모니터링 필요 (제한 기준 10m/s)\n- 주간 평균 26°C — 콘크리트 양생에 적합한 조건`,
      created_at: '2026-06-15T09:02:00',
    },
  ],
  pc2: [
    { id: 'm-pc2-1', conversation_id: 'pc2', role: 'user', content: '타워크레인 점검 현황 알려줘', agent: null, created_at: '2026-06-14T11:00:00' },
    {
      id: 'm-pc2-2', conversation_id: 'pc2', role: 'assistant', agent: 'equipment',
      content: `## 타워크레인 점검 현황\n\n### TC-01 (마스트 높이 80m)\n\n| 항목 | 최종 점검일 | 다음 점검일 | 상태 |\n|------|-----------|-----------|------|\n| 정기 안전검사 | 2026-05-15 | 2026-11-15 | **정상** |\n| 와이어로프 | 2026-06-01 | 2026-07-01 | **정상** |\n| 브레이크 | 2026-06-10 | 2026-07-10 | **주의** |\n\n- 브레이크 패드 마모율 72% — 다음 달 교체 권장\n- 오늘 풍속 예보상 오후 2시 이후 작업 주의`,
      created_at: '2026-06-14T11:03:00',
    },
  ],
  pc3: [
    { id: 'm-pc3-1', conversation_id: 'pc3', role: 'user', content: '아스팔트 현재 시세 알려줘', agent: null, created_at: '2026-06-12T15:00:00' },
    {
      id: 'm-pc3-2', conversation_id: 'pc3', role: 'assistant', agent: 'material',
      content: `## 아스팔트 자재 시세 (2026년 6월)\n\n| 자재 | 단위 | 현재가(원) | 전월 대비 |\n|------|------|----------|---------|\n| 아스팔트 콘크리트 | ton | 98,000 | **+3.2%** |\n| 구스 아스팔트 | ton | 142,000 | **+1.5%** |\n| 재생 아스팔트 | ton | 72,000 | **-0.8%** |\n\n### 조달 리스크\n\n- 국제 유가 상승으로 아스팔트 원자재 가격 강세 지속\n- 성수기(6~8월) 수요 증가로 납기 2~3주 지연 가능성\n- **재생 아스팔트 혼합 사용** 검토 시 원가 절감 가능`,
      created_at: '2026-06-12T15:03:00',
    },
  ],
};

const MOCK_RESPONSES: { content: string; agent: Message['agent'] }[] = [
  {
    agent: 'labor',
    content: `## 직접노무비 산출 결과\n\n표준품셈 2024년 기준으로 산출했습니다.\n\n| 항목 | 단위 | 품 | 단가(원) | 금액(원) |\n|------|------|----|---------|--------|\n| 보통인부 | 일 | 0.45 | 185,000 | 83,250 |\n| 특별인부 | 일 | 0.20 | 245,000 | 49,000 |\n| **합계** | | | | **132,250** |\n\n작업 조건에 따라 할증이 적용될 수 있습니다.`,
  },
  {
    agent: 'weather',
    content: `## 기상 리스크 평가\n\n현재 기상 데이터를 기반으로 분석했습니다.\n\n### 주요 리스크 요인\n\n- **강수 확률**: 30% (작업 지연 가능성 낮음)\n- **풍속**: 평균 4m/s (양호)\n- **기온**: 25°C (콘크리트 양생 적합)\n\n오늘은 **리스크 낮음** 수준입니다. 계획대로 진행하세요.`,
  },
  {
    agent: 'material',
    content: `## 자재 가격 조회 결과\n\n최근 시세 기준으로 조회했습니다.\n\n| 자재명 | 단위 | 현재가(원) | 전월비 |\n|--------|------|------------|-------|\n| 철근(SD400) | ton | 890,000 | +2.1% |\n| 레미콘(25-24-150) | m³ | 95,000 | +0.5% |\n| 합판거푸집 | m² | 8,500 | 변동없음 |\n\n철근 가격 소폭 상승 중입니다. 조기 발주를 검토하세요.`,
  },
  {
    agent: 'equipment',
    content: `## 장비 현황 분석\n\n현재 투입 장비 현황입니다.\n\n### 주요 장비 가동률\n\n- 타워크레인 TC-01: **가동중** (91%)\n- 이동식 크레인: **대기** (임차 예정)\n- 콘크리트 펌프카: **가동중** (78%)\n\n다음 주 콘크리트 타설 일정에 맞춰 펌프카 추가 투입을 권장합니다.`,
  },
];

let mockRespIdx = 0;

export async function mockSendMessage(convId: string, _content: string, signal?: AbortSignal): Promise<Message> {
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, 1600 + Math.random() * 1000);
    signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); });
  });
  const resp = MOCK_RESPONSES[mockRespIdx % MOCK_RESPONSES.length];
  mockRespIdx++;
  return {
    id: uuidv4(),
    conversation_id: convId,
    role: 'assistant',
    agent: resp.agent,
    content: resp.content,
    created_at: new Date().toISOString(),
  };
}

export function createMockConversation(
  ownerId: string,
  ownerName: string,
  projectId: string | null = null,
): Conversation {
  const now = new Date().toISOString();
  return {
    id: uuidv4(),
    project_id: projectId,
    owner_id: ownerId,
    owner_name: ownerName,
    title: '새 대화',
    visibility: projectId ? 'project_shared' : 'private',
    can_write: true,
    message_count: 0,
    created_at: now,
    updated_at: now,
  };
}
