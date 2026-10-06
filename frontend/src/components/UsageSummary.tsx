import React from 'react';
import { UsageStatus } from '../types';

export default function UsageSummary({ usage }: { usage?: UsageStatus | null }) {
  return <div className="account-usage" role="status">
    <div><span>남은 사용량</span><strong>{usage ? `${usage.remaining} / ${usage.limit}회` : '확인 중…'}</strong></div>
    <p>{usage?.service_remaining === 0 ? '오늘 서비스 전체 한도에 도달했어요.'
      : usage?.remaining === 0 ? '오늘 사용량을 모두 사용했어요.' : '추가 조건 답변 포함'}<br />한국 시간 매일 자정 초기화</p>
  </div>;
}
