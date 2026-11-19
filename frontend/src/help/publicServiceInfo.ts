import { PUBLIC_PAGE_META, PublicPage } from './publicPageMeta';

export const SERVICE_DESCRIPTION = '건셈은 2026 건설공사 표준품셈 원문을 근거로 공사비 견적과 품셈 상담을 제공하는 웹 서비스입니다. 적용 조건과 산출근거를 확인하고 계산된 견적을 Excel로 내려받을 수 있습니다.';

export const SERVICE_FAQ = [
  { question: '건셈에서 무엇을 할 수 있나요?', answer: SERVICE_DESCRIPTION },
  { question: '로그인 없이 사용할 수 있나요?', answer: '비회원은 하루 5회, Google 로그인 회원은 하루 20회까지 무료로 이용할 수 있습니다. 한국 시간 매일 자정에 초기화되며, 서비스 전체의 하루 한도에 따라 이용이 제한될 수 있습니다. 베타 기간 중 기능과 한도는 변경될 수 있습니다.' },
  { question: '질문에 어떤 정보를 적어야 하나요?', answer: '견적은 공종·작업 범위·물량과 단위를 함께 적어 주세요. 알고 있는 규격과 장비·현장 조건도 적으면 좋습니다. 품셈 상담은 적용 기준이나 포함 작업 등 궁금한 내용을 구체적으로 질문해 주세요.' },
  { question: '견적 금액을 그대로 사용해도 되나요?', answer: '견적은 참고용 초안입니다. 실제 적용 전 현장 조건, 적용 품셈과 단가·산출근거를 검토해야 합니다. 미산정 항목은 비용이 없다는 뜻이 아니므로 별도로 확인해 주세요.' },
];

export function publicStructuredData(page?: PublicPage) {
  const site = 'https://www.geonsem.com/';
  const application = { '@type': 'WebApplication', '@id': `${site}#application`, name: '건셈', url: site,
    applicationCategory: 'BusinessApplication', operatingSystem: 'Web', inLanguage: 'ko-KR', description: SERVICE_DESCRIPTION };
  const website = { '@type': 'WebSite', '@id': `${site}#website`, name: '건셈', url: site, inLanguage: 'ko-KR', about: { '@id': application['@id'] } };
  const pages = page ? [{ '@type': 'WebPage', '@id': `${site}${page}#webpage`, url: `${site}${page}`,
    name: PUBLIC_PAGE_META[page].title, description: PUBLIC_PAGE_META[page].description, inLanguage: 'ko-KR',
    isPartOf: { '@id': website['@id'] }, about: { '@id': application['@id'] } }] : [];
  return { '@context': 'https://schema.org', '@graph': [website, application, ...pages] };
}
