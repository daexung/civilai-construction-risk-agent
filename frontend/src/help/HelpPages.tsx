import React, { useEffect, useState } from 'react';
import { trackPage } from '../analytics';
import LandingPreview from '../landing/LandingPreview';
import demo from '../landing/demo.json';
import { PUBLIC_PAGE_META, PublicPage } from './publicPageMeta';
import { QUESTION_EXAMPLES, chatExampleUrl } from './exampleCatalog';
import '../landing/Landing.css';
import './HelpPages.css';

const sections = [
  ['start', '무엇을 할 수 있나요'], ['question', '질문 작성하기'], ['cards', '조건 선택하기'],
  ['result', '결과 확인하기'], ['usage', '이용·저장·다운로드'], ['faq', '자주 묻는 질문'],
];

function HelpLayout({ page, children }: { page: PublicPage; children: React.ReactNode }) {
  useEffect(() => {
    const meta = PUBLIC_PAGE_META[page];
    document.title = meta.title;
    document.querySelector('meta[name="description"]')?.setAttribute('content', meta.description);
    document.querySelector('link[rel="canonical"]')?.setAttribute('href', `https://www.geonsem.com/${page}`);
    trackPage(`/${page}`);
  }, [page]);
  return <div className="civil-landing help-site">
    <a className="lp-skip" href="#help-main">본문으로 건너뛰기</a>
    <header className="lp-header"><div className="lp-container lp-header-inner">
      <a className="lp-wordmark" href="/" aria-label="건셈 홈">건셈</a>
      <nav aria-label="주 메뉴">
        <a href="/guide" aria-current={page === 'guide' ? 'page' : undefined}>사용 가이드</a>
        <a href="/examples" aria-current={page === 'examples' ? 'page' : undefined}>질문 예시</a>
        <a className="lp-button help-start" href="/chat">질문 시작</a>
      </nav>
    </div></header>
    <main id="help-main">{children}</main>
    <footer className="lp-container help-footer"><a className="lp-wordmark" href="/">건셈</a>
      <nav aria-label="하단 메뉴"><a href="/guide">사용 가이드</a><a href="/examples">질문 예시</a><a href="/terms">이용약관</a><a href="/privacy">개인정보 처리방침</a></nav>
      <p>견적은 참고용 초안입니다. 실제 적용 전 조건과 산출근거를 확인해 주세요.</p>
    </footer>
  </div>;
}

function Section({ id, eyebrow, title, children }: { id: string; eyebrow: string; title: string; children: React.ReactNode }) {
  return <section className="help-section" id={id} aria-labelledby={`${id}-title`}>
    <p className="help-eyebrow">{eyebrow}</p><h2 id={`${id}-title`}>{title}</h2>{children}
  </section>;
}

function Guide() {
  return <>
    <div className="lp-container help-hero"><p className="help-eyebrow">건셈 사용 가이드</p>
      <h1>첫 질문부터<br />견적 확인까지.</h1>
      <p className="help-lead">무엇을 적어야 할지, 확인 카드는 어떻게 선택해야 할지.<br className="help-desktop-break" /> 건셈으로 견적과 품셈 근거를 확인하는 순서를 안내합니다.</p>
      <div className="help-actions"><a className="lp-button" href="/chat">건셈에 질문하기</a><a className="help-text-link" href="/examples">질문 예시 먼저 보기</a></div>
    </div>
    <div className="lp-container help-guide-grid">
      <aside className="help-toc"><nav aria-label="사용 가이드 목차"><p>이 페이지에서</p>{sections.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}</nav></aside>
      <div className="help-article">
        <Section id="start" eyebrow="시작하기" title="견적이 필요한가요, 적용 기준이 궁금한가요?">
          <p>질문의 목적을 평소 쓰는 말로 적어 주세요. 처음부터 모든 조건을 알 필요는 없어요. 모르는 조건은 임의로 채우지 말고, 답변에 나오는 확인 사항을 살펴보세요.</p>
          <div className="help-two-up"><div className="help-info-card"><h3>공사비 견적</h3><p>작업과 물량을 적고 비용 계산을 요청해요. 필요한 공종과 조건을 확인한 뒤 계산 가능한 범위를 보여줍니다.</p><a href={chatExampleUrl(QUESTION_EXAMPLES[1].question)}>견적 질문 입력해 보기</a></div>
            <div className="help-info-card"><h3>품셈 상담</h3><p>적용 기준, 포함 작업, 할증 등 궁금한 내용을 물어보세요. 답변에 붙은 품셈 근거와 적용 조건을 함께 확인합니다.</p><a href={chatExampleUrl(QUESTION_EXAMPLES[6].question)}>품셈 상담 입력해 보기</a></div></div>
          <p className="help-small">예시 링크는 질문을 입력창에 채웁니다. 내용을 확인하고 직접 보내 주세요.</p>
        </Section>
        <Section id="question" eyebrow="질문 작성" title="공종·물량·알고 있는 조건을 함께 적어요">
          <ul className="help-checklist"><li><strong>어떤 작업인가요?</strong> 설치·철거·보수 등 작업 범위를 적어요.</li><li><strong>얼마나 하나요?</strong> ㎡, ㎥, m, 개소처럼 단위와 물량을 함께 적어요.</li><li><strong>어떤 조건인가요?</strong> 알고 있는 규격, 장비, 시공 위치와 포함·제외할 작업을 적어요.</li></ul>
          <div className="help-question-example"><span>이렇게 적어 보세요</span><blockquote>{QUESTION_EXAMPLES[1].question}</blockquote><p>‘콘크리트 비용’보다 타설 부위·물량·장비 규격을 확인하기 쉬워요.</p></div>
          <h3>여러 공종은 작업마다 줄을 나눠요</h3><blockquote className="help-prompt">{QUESTION_EXAMPLES[3].question}</blockquote>
          <p>건셈이 나눈 작업이 의도와 맞는지 먼저 확인하세요. 필요한 작업이 누락됐거나 다른 뜻으로 해석됐다면 질문을 수정해 주세요.</p>
          <a className="help-text-link" href="/examples">공종별 질문 예시 더 보기</a>
        </Section>
        <Section id="cards" eyebrow="확인 카드" title="선택하고, 확인한 뒤 확정해서 보내요">
          <p>견적 요청 뒤 바로 금액 대신 확인 카드가 나올 수 있어요. 작업 포함 여부, 적용할 공종, 시공 조건을 차례로 확인하는 과정입니다.</p>
          <ol className="help-process"><li><strong>작업 범위 확인</strong><p>질문에서 나눈 작업을 이번 견적에 넣을지 선택해요.</p></li><li><strong>공종·조건 선택</strong><p>실제 작업과 맞는 품셈 후보와 현장 조건을 고르세요. 판정표나 원문이 있으면 함께 확인해요.</p></li><li><strong>선택 내용 전송</strong><p>선택한 카드는 녹색과 체크로 표시돼요. ‘작업 선택 확정하기’ 또는 ‘선택한 조건 보내기’를 눌러 진행합니다.</p></li></ol>
          <h3>작업 범위의 네 선택지는 이렇게 달라요</h3><dl className="help-definition"><div><dt>이 작업 비용 계산</dt><dd>이번 견적에 포함해 작업비를 계산해요.</dd></div><div><dt>이 작업 제외</dt><dd>이번 견적의 계산 대상에서 빼요.</dd></div><div><dt>시공 조건으로만 사용</dt><dd>별도 작업비 대신 다른 작업의 시공 조건으로 반영해요.</dd></div><div><dt>기존 바탕 상태로만 사용</dt><dd>이미 있는 바탕면 정보로 사용하고 이 작업비는 계산하지 않아요.</dd></div></dl>
          <div className="help-notice"><strong>선택과 전송은 달라요</strong><p>카드를 누르는 것만으로는 이용 횟수가 차감되지 않아요. 확정 요청의 차감 여부는 카드 아래 안내를 확인하세요. 한 번 확정한 뒤에도 추가 확인이 이어질 수 있어요.</p></div>
        </Section>
        <Section id="result" eyebrow="견적과 근거" title="금액보다 먼저 계산 범위를 확인하세요">
          <ul className="help-checklist"><li><strong>물량과 조건</strong> 질문에 적은 수량·단위·장비와 실제 적용 조건이 맞는지 확인해요.</li><li><strong>산정·제외·미산정 항목</strong> 계산하지 못한 항목은 무료이거나 비용이 없다는 뜻이 아니에요.</li><li><strong>적용 단가와 가정</strong> 기본값이나 가정이 현장에 맞는지 살펴보세요. 조건을 바꾸면 결과도 달라질 수 있어요.</li><li><strong>품셈 근거와 원문</strong> 근거 상자를 펼쳐 부문·절 번호·쪽수와 적용 조건을 확인해요. 원문 보기 기능이 있는 경우 해당 자료도 열어 보세요.</li></ul>
          <p>품셈 상담도 답변 문장과 근거를 함께 읽어야 해요. 확인이 필요하다는 안내가 있거나 관련 원문을 찾지 못한 경우에는 그 한계를 고려해 주세요.</p>
          <a className="help-text-link" href="/examples#estimate-result">저장된 견적 결과 예시 살펴보기</a>
        </Section>
        <Section id="usage" eyebrow="이용 안내" title="무료 횟수, 대화 저장, Excel 다운로드">
          <div className="help-two-up"><div className="help-info-card"><h3>로그인 없이</h3><p className="help-quota">하루 <strong>5회</strong></p><p>대화는 임시로 유지됩니다. 24시간 경과나 서버 재시작 등으로 만료되면 이전 조건으로 이어갈 수 없어요.</p></div><div className="help-info-card"><h3>Google 로그인</h3><p className="help-quota">하루 <strong>20회</strong></p><p>대화를 계정에 저장하고 지난 대화를 이어서 볼 수 있어요.</p></div></div>
          <p>이용 횟수는 한국 시간 매일 자정에 초기화돼요. 서비스 전체의 하루 한도에 도달하면 개인 횟수가 남아 있어도 이용이 제한될 수 있어요. 베타 기간에는 기능과 한도가 변경될 수 있습니다.</p>
          <h3>어떤 요청이 차감되나요?</h3><ul className="help-checklist"><li>직접 입력한 질문, 작업 범위·대상 선택 확정, 다음 작업 진행, 새 견적 시작, 조건 재계산은 차감 대상입니다.</li><li>현재 확인 카드의 일반 조건 답변은 대화당 30회까지 무료이며, 이후에는 확정 요청마다 1회가 차감돼요. 이전 카드의 답을 다시 보내는 등 현재 확인 요청과 맞지 않는 경우도 무료 대상이 아닐 수 있어요.</li><li>예시를 입력창에 채우거나 다음 질문을 작성하는 것만으로는 차감되지 않아요.</li></ul>
          <h3>Excel은 로그인 없이도 받을 수 있어요</h3><p>계산이 완료된 견적에 다운로드 버튼이 제공됩니다. 추가 확인 중이거나 최신 계산 결과가 없으면 내려받을 수 없어요. 비회원은 임시 대화가 만료되기 전에 저장해 주세요.</p><p>미산정 항목이 있는 견적은 Excel에도 그 한계가 남습니다. 파일을 사용하기 전에 산출근거와 누락 비용을 확인하세요.</p>
        </Section>
        <Section id="faq" eyebrow="도움이 필요할 때" title="자주 묻는 질문">
          <details><summary>모르는 조건은 어떻게 입력하나요?</summary><p>확인되지 않은 값을 임의로 선택하지 마세요. 판정표와 원문을 살펴보고, 무엇을 모르는지 구체적으로 질문해 주세요. 정보가 부족하면 견적을 확정하지 못할 수 있어요.</p></details>
          <details><summary>질문을 보냈는데 시간이 오래 걸려요.</summary><p>답변을 기다리는 동안 다음 질문을 작성할 수 있어요. 현재 응답이 완료되면 전송하세요. 실패 안내가 나오면 원인을 확인하고 해당 질문의 ‘다시 시도’를 이용해 주세요.</p></details>
          <details><summary>작업이 잘못 나뉘었거나 답이 의도와 달라요.</summary><p>질문 편집 기능으로 작업과 물량을 더 명확하게 적어 다시 보내세요. 수정해서 다시 보내는 요청은 이용 횟수가 차감돼요. 작업마다 줄을 나누는 것도 도움이 됩니다.</p></details>
          <details><summary>‘임시 대화가 만료되었다’고 나와요.</summary><p>화면의 ‘새 대화로 이어서 질문하기’를 사용할 수 있어요. 이전 조건과 견적이 서버에 복원되는 것은 아니므로, 필요한 작업 조건을 다시 확인해 주세요.</p></details>
          <details><summary>결과를 그대로 실제 견적에 써도 되나요?</summary><p>건셈의 견적은 참고용 초안이에요. 실제 현장 조건, 적용 품셈·단가·시점과 미산정 항목을 검토한 뒤 사용해 주세요.</p></details>
        </Section>
        <div className="help-bottom-cta"><h2>이제 내 작업으로 시작해 보세요</h2><p>예시를 고르고 물량과 조건을 바꿔 질문할 수 있어요.</p><div className="help-actions"><a className="lp-button" href="/examples">질문 예시 고르기</a><a className="help-text-link" href="/chat">직접 질문하기</a></div></div>
      </div>
    </div>
  </>;
}

function Examples() {
  const [filter, setFilter] = useState('전체');
  const examples = QUESTION_EXAMPLES.filter(example => filter === '전체' || example.kind === filter);
  return <>
    <div className="lp-container help-hero"><p className="help-eyebrow">견적·품셈 상담 질문 예시</p><h1>어떻게 물어볼지<br />예시에서 시작하세요.</h1><p className="help-lead">질문을 골라 내 현장의 물량과 조건으로 바꿔 보세요.<br className="help-desktop-break" /> 링크를 눌러도 자동 전송되지 않으며, 직접 보내기 전에는 이용 횟수가 차감되지 않아요.</p><a className="help-text-link" href="/guide">사용 순서가 궁금하다면 가이드 보기</a></div>
    <section className="lp-container help-example-section" aria-labelledby="example-list-title"><h2 id="example-list-title">내 질문에 가까운 예시 찾기</h2><div className="help-filters" role="group" aria-label="질문 종류">{['전체', '견적', '품셈 상담'].map(kind => <button key={kind} type="button" aria-pressed={filter === kind} onClick={() => setFilter(kind)}>{kind}</button>)}</div>
      <p className="help-small">아래는 질문 작성 예시입니다. 해당 조건의 계산 완료나 특정 금액을 보장하는 사례가 아닙니다.</p>
      <div className="help-example-grid">{examples.map(example => <article className="help-example-card" id={example.id} key={example.id}><span className="help-example-kind">{example.kind}</span><h3>{example.title}</h3><blockquote>{example.question}</blockquote><p>{example.note}</p><p className="help-example-facts"><strong>함께 적으면 좋아요</strong>{example.facts}</p><a href={chatExampleUrl(example.question)}>이 질문을 입력창에 넣기</a></article>)}</div>
    </section>
    <section className="lp-container help-saved-example" id="estimate-result" aria-labelledby="estimate-result-title"><p className="help-eyebrow">저장된 실제 응답</p><h2 id="estimate-result-title">견적 결과는 이렇게 확인해요</h2><p>아래는 홈페이지에도 제공되는 저장된 견적 예시입니다. 내 현장에 맞춰 새로 계산한 결과가 아니며, 미산정 항목이 포함돼 있어요.</p>
      <div className="lp-demo lp-report"><div className="lp-report-toolbar"><span>건셈 · 저장된 견적 예시</span><span>미산정 항목 포함</span></div><div className="lp-live-preview-grid"><div className="lp-question"><p className="lp-label">질문</p><p className="lp-question-text">{demo.question}</p><p className="help-small">금액뿐 아니라 원가계산서·일위대가·산출근거와 계산 범위를 함께 살펴보세요.</p></div><LandingPreview /></div></div>
      <div className="help-actions"><a className="lp-button" href={chatExampleUrl(demo.question)}>이 예시를 내 조건으로 바꾸기</a><a className="help-text-link" href="/guide#result">결과 읽는 법 보기</a></div>
    </section>
  </>;
}

export default function HelpPage({ page }: { page: PublicPage }) {
  return <HelpLayout page={page}>{page === 'guide' ? <Guide /> : <Examples />}</HelpLayout>;
}
