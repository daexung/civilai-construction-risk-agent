import React, { useState } from 'react';
import { BillRow, ConditionField, RateRow, StatementRow } from '../types';
import { exportUrl } from '../api';

const HEADED = ['재료비', '노무비', '경비'];

function amount(value: number | string | null | undefined): string {
  if (value == null || value === '') return '—';
  const [whole, fraction] = String(value).split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}

function scaleText(value: string): string {
  if (value === '이 견적만') return '이 견적만';
  const eok = Number(value) / 100_000_000;
  return `전체 ${Number.isInteger(eok) ? eok.toLocaleString() : eok}억원`;
}

function byName(conditions: ConditionField[]): Record<string, ConditionField> {
  return Object.fromEntries(conditions.map((field) => [field.name, field]));
}

// 첫 화면에 보이는 현재 조건 한 줄: "토목 · 1~6개월 · 종합건설업 · 단독 공사"
export function conditionSummary(conditions: ConditionField[]): string {
  const c = byName(conditions);
  if (!c.work_category) return '';
  const scale = c.project_scale.value === '이 견적만' ? '단독 공사' : scaleText(c.project_scale.value);
  return [c.work_category.group ?? c.work_category.value, c.duration.value, c.contractor_type.value, scale].join(' · ');
}

export function ConditionsBar({ threadId, conditions, disabled, onApply }: {
  threadId: string;
  conditions: ConditionField[];
  disabled: boolean;
  onApply: (conditions: Record<string, string>) => void;
}) {
  const c = byName(conditions);
  const [open, setOpen] = useState(false);
  const [group, setGroup] = useState(c.work_category?.group ?? '토목');
  const [detail, setDetail] = useState(c.work_category?.value ?? '');
  const [duration, setDuration] = useState(c.duration?.value ?? '');
  const [contractor, setContractor] = useState(c.contractor_type?.value ?? '');
  const [scale, setScale] = useState(c.project_scale?.value === '이 견적만' ? '' : String(Number(c.project_scale?.value) / 100_000_000));
  if (!c.work_category) return null;

  const isDefault = conditions.every((field) => field.source === '기본값');
  const groups = c.work_category.groups ?? {};
  const scaleValue = scale.trim() === '' ? '이 견적만' : String(Math.round(Number(scale) * 100_000_000));
  const scaleInvalid = scale.trim() !== '' && !(Number(scale) > 0);
  const pickGroup = (next: string) => {
    setGroup(next);
    if (!groups[next]?.includes(detail)) setDetail(next === '건축' ? '주택 외 건축' : '기타 토목공사');
  };

  return (
    <div className="conditions-bar">
      <div className="conditions-line">
        <span className="conditions-current">
          {isDefault && <em className="default-tag">기본 조건</em>}
          기준: {conditionSummary(conditions)}
        </span>
        <button type="button" className="ghost-btn" disabled={disabled} onClick={() => setOpen((v) => !v)}>
          조건 바꾸기
        </button>
        <a className="ghost-btn export-link" href={exportUrl(threadId)}>엑셀로 받기</a>
      </div>
      {open && (
        <div className="conditions-panel">
          <div className="cond-row">
            <span className="cond-label">공사 종류</span>
            <div className="cond-options">
              {Object.keys(groups).map((name) => (
                <button key={name} type="button" className={`choice-btn${group === name ? ' selected' : ''}`}
                  onClick={() => pickGroup(name)}>{name}</button>
              ))}
            </div>
          </div>
          <details className="cond-detail">
            <summary>세부 종류(선택) · {detail}</summary>
            <div className="cond-options">
              {(groups[group] ?? []).map((name) => (
                <button key={name} type="button" className={`choice-btn${detail === name ? ' selected' : ''}`}
                  title={c.work_category.help[name]} onClick={() => setDetail(name)}>{name}</button>
              ))}
            </div>
            <small>{c.work_category.help[detail]}</small>
          </details>
          <div className="cond-row">
            <span className="cond-label">공사 기간</span>
            <div className="cond-options">
              {c.duration.choices.map((name) => (
                <button key={name} type="button" className={`choice-btn${duration === name ? ' selected' : ''}`}
                  title={c.duration.help[name]} onClick={() => setDuration(name)}>{name}</button>
              ))}
            </div>
            <small>{c.duration.help[duration]}</small>
          </div>
          <div className="cond-row">
            <span className="cond-label">시공사 업종</span>
            <div className="cond-options">
              {c.contractor_type.choices.map((name) => (
                <button key={name} type="button" className={`choice-btn${contractor === name ? ' selected' : ''}`}
                  title={c.contractor_type.help[name]} onClick={() => setContractor(name)}>{name}</button>
              ))}
            </div>
            <small>{c.contractor_type.help[contractor]}</small>
          </div>
          <div className="cond-row">
            <span className="cond-label">전체 공사 규모</span>
            <div className="cond-options">
              <input className="scale-input" inputMode="decimal" placeholder="이 견적만" value={scale}
                onChange={(event) => setScale(event.target.value)} aria-label="전체 공사 규모(억원)" />
              <span>억원</span>
            </div>
            <small>{scale.trim() === '' ? c.project_scale.help['이 견적만'] : '이 견적이 포함된 전체 공사 금액(제비율 구간 선택에 사용)'}</small>
          </div>
          <button type="button" className="submit-answers-btn" disabled={disabled || scaleInvalid}
            onClick={() => {
              onApply({ work_category: detail, duration, contractor_type: contractor, project_scale: scaleValue });
              setOpen(false);
            }}>적용</button>
        </div>
      )}
    </div>
  );
}

export function StatementTable({ rows, notes }: { rows: StatementRow[]; notes: string[] }) {
  let lastGroup = '';
  const body: React.ReactNode[] = [];
  rows.forEach((row, index) => {
    const group = HEADED.includes(row.category ?? '') ? row.category! : (row.category ? '' : '그 외 미산정');
    if (group && group !== lastGroup) {
      body.push(<tr className="stmt-group" key={`g-${group}`}><th colSpan={4}>{group}</th></tr>);
    }
    lastGroup = group || lastGroup;
    const dim = row.status !== '산정';
    body.push(
      <tr key={`${row.name}-${index}`} title={row.reason ?? row.note ?? undefined}
        className={[row.kind, dim ? 'dim' : '', row.final ? 'final' : ''].join(' ').trim()}>
        <td>{row.name}</td>
        <td className="basis">{row.basis || '—'}</td>
        <td className="num">{row.status === '미산정' ? '—' : amount(row.amount)}</td>
        <td>{dim ? row.status : ''}</td>
      </tr>,
    );
  });
  return (
    <div className="stmt-wrap">
      <div className="table-scroll">
        <table className="inputs-table stmt-table">
          <thead><tr><th>비목</th><th>산출 기준(기준액 × 요율)</th><th>금액(원)</th><th>상태</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
      {notes.map((note) => <div className="unit-note" key={note}>{note}</div>)}
    </div>
  );
}

export function BillTable({ bill }: { bill: BillRow | null }) {
  if (!bill) return <div className="unit-note">내역서로 만들 금액이 없습니다.</div>;
  return (
    <div className="table-scroll">
      <table className="inputs-table bill-table">
        <thead>
          <tr><th rowSpan={2}>공종</th><th rowSpan={2}>규격</th><th rowSpan={2}>단위</th><th rowSpan={2}>수량</th>
            <th colSpan={3}>단가(원)</th><th colSpan={3}>금액(원)</th><th rowSpan={2}>합계(원)</th></tr>
          <tr><th>재료비</th><th>노무비</th><th>경비</th><th>재료비</th><th>노무비</th><th>경비</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>{bill.name}</td><td>{bill.spec}</td><td>{bill.unit}</td><td className="num">{amount(bill.quantity)}</td>
            {(['재료비', '노무비', '경비'] as const).map((k) => <td className="num" key={`u${k}`}>{amount(bill.unit_price[k])}</td>)}
            {(['재료비', '노무비', '경비'] as const).map((k) => <td className="num" key={`a${k}`}>{amount(bill.amount[k])}</td>)}
            <td className="num"><strong>{amount(bill.total)}</strong></td>
          </tr>
        </tbody>
      </table>
      {bill.partial && <div className="unit-note">미산정 항목을 뺀 부분 합계입니다.</div>}
    </div>
  );
}

export function RateTable({ rows }: { rows: RateRow[] }) {
  return (
    <div className="table-scroll">
      <table className="inputs-table rate-table">
        <thead><tr><th>구분</th><th>품명</th><th>단위</th><th>단가</th><th>출처</th></tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.name}-${index}`} className={row.price == null ? 'dim' : undefined}>
              <td>{row.kind}</td><td>{row.name}</td><td>{row.unit}</td>
              <td className="num">{amount(row.price)}</td><td className="basis">{row.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
