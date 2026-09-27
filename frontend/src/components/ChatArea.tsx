import React, { useEffect, useRef, useState, useCallback } from 'react';
import { AgentQuestion, BlockedResult, ChatResponse, ChatTurn, ChoiceValue, ComputedResult } from '../types';
import './ChatArea.css';

interface Props {
  turns: ChatTurn[];
  loading: boolean;
  onSendMessage: (text: string) => void;
  onSendAnswers: (answers: Record<string, ChoiceValue>, summary: string) => void;
  onNewChat: () => void;
}

const EXAMPLES = [
  '철근콘크리트 벽체 260㎥ 펌프차로 타설 비용',
  '합판거푸집 설치 인건비',
  '레미콘 타설 노무비 알려줘',
];

const STATUS_LABEL: Record<ChatResponse['status'], string> = {
  OUT_OF_SCOPE: '범위 밖',
  EVIDENCE_ONLY: '근거만 제공',
  MISSING_INFO: '확인이 필요합니다',
  COMPUTED: '계산 완료',
  BLOCKED: '계산 보류',
  ERROR: '오류',
};

const BLOCKED_HINTS: Record<string, string> = {
  reset_status: '재셋팅 여부를 "없음"으로 답하면 계산됩니다.',
};

function choiceLabel(value: ChoiceValue): string {
  if (typeof value === 'boolean') return value ? '예' : '아니오';
  return value;
}

// choices에 담긴 절 제목("6-1-4 콘크리트 펌프차 타설...")에서 앞의 절 번호만 뽑아 답으로 보낸다.
function sectionNoFromTitle(title: string): string {
  const match = title.match(/^\d+(?:-\d+){2}/);
  return match ? match[0] : title;
}

function DecisionTable({ table }: { table: NonNullable<AgentQuestion['decision_table']> }) {
  return (
    <details className="decision-table">
      <summary>판정표 보기</summary>
      <ul>
        {Object.entries(table).map(([value, row]) => (
          <li key={value}>
            <strong>{value}</strong>
            <span>{row.적용기준 ?? ''}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function QuestionCard({
  question, selectedLabel, onSelect, disabled,
}: {
  question: AgentQuestion;
  selectedLabel: string | undefined;
  onSelect: (value: ChoiceValue, label: string) => void;
  disabled: boolean;
}) {
  const isWork = question.name === 'work';
  return (
    <div className="question-card">
      <div className="question-ask">{question.ask}</div>
      {question.reason && <div className="question-reason">{question.reason}</div>}
      {question.hint && (
        <div className="question-hint">
          힌트: {question.hint.matched} → {question.hint.value}일 수 있습니다 (자동 선택 아님, 확인 필요)
        </div>
      )}
      {question.choices && (
        <div className="question-choices">
          {question.choices.map((choice) => {
            const label = choiceLabel(choice);
            const value: ChoiceValue = isWork && typeof choice === 'string' ? sectionNoFromTitle(choice) : choice;
            const isDefault = isWork && question.default === value;
            const isSelected = selectedLabel === label;
            return (
              <button
                key={label}
                type="button"
                className={`choice-btn${isSelected ? ' selected' : ''}${isDefault && !selectedLabel ? ' is-default' : ''}`}
                disabled={disabled}
                onClick={() => onSelect(value, label)}
              >
                {label}
                {isDefault && <span className="choice-default-tag">기본값</span>}
              </button>
            );
          })}
        </div>
      )}
      {question.decision_table && <DecisionTable table={question.decision_table} />}
    </div>
  );
}

function EvidenceList({ items }: { items: ChatResponse['evidence'] }) {
  if (items.length === 0) return null;
  return (
    <div className="evidence-list">
      {items.map((item, i) => (
        <div className="evidence-row" key={i}>
          <div className="evidence-head">
            <strong>{item.section}</strong>
            <span>PDF {item.page}쪽{item.table_id ? ` · ${item.table_id}` : ''}</span>
          </div>
          <p>{item.snippet}</p>
        </div>
      ))}
    </div>
  );
}

function ComputedCard({ work, result }: { work: ChatResponse['work']; result: ComputedResult }) {
  const notReviewed = result.review_status !== '완료';
  return (
    <div className="computed-card">
      <div className="computed-title-row">
        {work && <strong>{work.title}</strong>}
        {notReviewed && <span className="review-badge">검토 전 명세 · 참고용</span>}
      </div>

      <div className="formula-row">
        <span className="formula-label">하루 시공량</span>
        <strong>{result.daily_volume.value} {result.daily_volume.unit}</strong>
        <span className="formula-text">{result.daily_volume.formula}</span>
      </div>
      <div className="formula-row">
        <span className="formula-label">작업일수</span>
        <strong>{result.work_days.value}</strong>
        <span className="formula-text">{result.work_days.formula}</span>
      </div>

      <table className="inputs-table lines-table">
        <thead>
          <tr><th>구분</th><th>항목</th><th>값</th><th>단위</th><th>인원</th><th>적용 규칙</th></tr>
        </thead>
        <tbody>
          {result.lines.map((line) => (
            <tr key={line.name}>
              <td>{line.kind === 'labor' ? '인력' : '장비'}</td>
              <td>{line.name}</td>
              <td>{line.value}</td>
              <td>{line.unit}</td>
              <td>{line.crew ?? '-'}</td>
              <td>{line.rules.length > 0 ? line.rules.join('; ') : '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="source-list">
        {result.daily_volume.sources.map((source, i) => <div key={`d${i}`}>{source}</div>)}
        {result.lines.map((line) => <div key={line.name}>{line.name}: {line.source}</div>)}
      </div>

      <div className="not-calculated">
        <h4>계산하지 않은 항목</h4>
        <ul>
          {result.not_calculated.map((item, i) => <li key={i}>{item.item}</li>)}
        </ul>
      </div>
    </div>
  );
}

function BlockedCard({ result }: { result: BlockedResult }) {
  return (
    <div className="blocked-card">
      <p className="blocked-source">원문 출처: {result.source}</p>
      <p className="blocked-hint">{BLOCKED_HINTS[result.input] ?? `${result.input} 값을 바꾸면 계산될 수 있습니다.`}</p>
    </div>
  );
}

function WarningBanner({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="warning-banner">
      {warnings.map((warning, i) => <div key={i}>{warning}</div>)}
    </div>
  );
}

function AssistantCard({
  response, interactive, draft, onSelect, onSubmit, loading,
}: {
  response: ChatResponse;
  interactive: boolean;
  draft: Record<string, { value: ChoiceValue; label: string }>;
  onSelect: (name: string, value: ChoiceValue, label: string) => void;
  onSubmit: () => void;
  loading: boolean;
}) {
  return (
    <div className={`assistant-card status-${response.status.toLowerCase()}`}>
      <WarningBanner warnings={response.search.warnings} />
      <div className="assistant-card-header">
        <span className="status-badge">{STATUS_LABEL[response.status]}</span>
        {response.work && <span className="work-badge">{response.work.title}</span>}
      </div>
      <div className="assistant-text">{response.message}</div>

      {response.status === 'EVIDENCE_ONLY' && <EvidenceList items={response.evidence} />}

      {response.status === 'MISSING_INFO' && (
        <div className="question-list">
          {response.questions.map((question) => (
            <QuestionCard
              key={question.name}
              question={question}
              selectedLabel={draft[question.name]?.label}
              disabled={!interactive || loading}
              onSelect={(value, label) => onSelect(question.name, value, label)}
            />
          ))}
          {interactive && (
            <button
              type="button"
              className="submit-answers-btn"
              disabled={loading || Object.keys(draft).length === 0}
              onClick={onSubmit}
            >
              보내기
            </button>
          )}
        </div>
      )}

      {response.status === 'COMPUTED' && response.result && (
        <ComputedCard work={response.work} result={response.result as ComputedResult} />
      )}

      {response.status === 'BLOCKED' && response.result && (
        <BlockedCard result={response.result as BlockedResult} />
      )}
    </div>
  );
}

export default function ChatArea({ turns, loading, onSendMessage, onSendAnswers, onNewChat }: Props) {
  const [input, setInput] = useState('');
  const [draft, setDraft] = useState<Record<string, { value: ChoiceValue; label: string }>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const lastTurn = turns[turns.length - 1];
  const lastResponse = lastTurn?.role === 'assistant' ? lastTurn.response : undefined;

  useEffect(() => {
    if (lastResponse?.status === 'MISSING_INFO') {
      const initial: Record<string, { value: ChoiceValue; label: string }> = {};
      const workQuestion = lastResponse.questions.find((q) => q.name === 'work');
      if (workQuestion?.default && workQuestion.choices) {
        const defaultChoice = workQuestion.choices.find(
          (choice) => typeof choice === 'string' && sectionNoFromTitle(choice) === workQuestion.default,
        );
        if (typeof defaultChoice === 'string') {
          initial.work = { value: workQuestion.default, label: choiceLabel(defaultChoice) };
        }
      }
      setDraft(initial);
    } else {
      setDraft({});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastTurn?.id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns.length, loading]);

  const handleSelect = useCallback((name: string, value: ChoiceValue, label: string) => {
    setDraft((prev) => ({ ...prev, [name]: { value, label } }));
  }, []);

  const handleSubmitAnswers = useCallback(() => {
    const answers: Record<string, ChoiceValue> = {};
    const parts: string[] = [];
    for (const [name, entry] of Object.entries(draft)) {
      answers[name] = entry.value;
      parts.push(entry.label);
    }
    onSendAnswers(answers, parts.join(', ') || '답변을 보냈습니다');
  }, [draft, onSendAnswers]);

  const handleSubmitMessage = () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    onSendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmitMessage(); }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 160) + 'px'; }
  };

  const inputBox = (
    <div className="input-box">
      <textarea
        ref={textareaRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        placeholder="메시지를 입력하세요 (질문이 있으면 글자로 답해도 됩니다)"
        rows={1}
        disabled={loading}
      />
      <button className="send-btn" onClick={handleSubmitMessage} disabled={!input.trim() || loading}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
        </svg>
      </button>
    </div>
  );

  if (turns.length === 0) {
    return (
      <main className="chat-area">
        <div className="centered-welcome">
          <div className="welcome-header">
            <div className="welcome-logo">Civil<span>.AI</span></div>
            <h2>어떤 공사비를 계산할까요?</h2>
            <p className="welcome-subtitle">2026 건설공사 표준품셈을 기준으로 계산에 필요한 조건을 확인해드립니다</p>
          </div>
          <div className="example-prompts">
            {EXAMPLES.map((text) => (
              <button key={text} className="example-btn" onClick={() => onSendMessage(text)}>{text}</button>
            ))}
          </div>
          <div className="centered-input-area">{inputBox}</div>
        </div>
      </main>
    );
  }

  return (
    <main className="chat-area">
      <div className="messages-wrap">
        <div className="chat-toolbar">
          <button className="export-btn" onClick={onNewChat} title="새 대화">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            새 대화
          </button>
        </div>
        <div className="messages">
          {turns.map((turn, i) => (
            <div key={turn.id} className={`message ${turn.role}`}>
              {turn.role === 'user' ? (
                <div className="user-msg-wrap">
                  <div className="user-bubble">{turn.text}</div>
                </div>
              ) : (
                <div className="assistant-body">
                  {turn.response && (
                    <AssistantCard
                      response={turn.response}
                      interactive={i === turns.length - 1}
                      draft={draft}
                      onSelect={handleSelect}
                      onSubmit={handleSubmitAnswers}
                      loading={loading}
                    />
                  )}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="message assistant">
              <div className="loading-indicator">
                <svg width="26" height="20" viewBox="0 0 40 30" fill="none">
                  <rect className="brick b1" x="0" y="22" width="11" height="7" rx="1.5" fill="#3a7d44" />
                  <rect className="brick b2" x="13" y="22" width="11" height="7" rx="1.5" fill="#3a7d44" />
                  <rect className="brick b3" x="26" y="22" width="11" height="7" rx="1.5" fill="#3a7d44" />
                  <rect className="brick b4" x="6" y="14" width="11" height="7" rx="1.5" fill="#2e6436" />
                  <rect className="brick b5" x="20" y="14" width="11" height="7" rx="1.5" fill="#2e6436" />
                  <rect className="brick b6" x="13" y="6" width="11" height="7" rx="1.5" fill="#14532d" />
                </svg>
                <span className="think-label animate">생각 중...</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
      <div className="input-area">{inputBox}</div>
    </main>
  );
}
