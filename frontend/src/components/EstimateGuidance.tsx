import { ChatResponse, ComputedResult } from '../types';

export default function EstimateGuidance({ response }: { response: ChatResponse }) {
  if (response.status === 'MISSING_INFO') {
    const names = response.questions.map(question => question.name);
    const onlyWork = names.length === 1 && names[0] === 'work';
    const pumpConditions = names.some(name => ['pump_size', 'slump_band', 'facility_type', 'site_type'].includes(name));
    return <aside className="estimate-guidance" aria-label="추가 조건 안내">
      <strong>{onlyWork ? '먼저 계산할 공종을 골라 주세요' : '이 조건이 필요한 이유'}</strong>
      <p>{onlyWork ? '적용할 품셈을 선택하면 해당 공종에 필요한 조건을 확인할 수 있어요.'
        : pumpConditions ? '콘크리트 타설은 펌프차 규격·슬럼프·작업 여건에 따라 시공량과 비용이 달라져요. 아래에서 추가로 필요한 조건을 확인해 주세요.'
        : '공종마다 품셈을 적용하는 기준이 달라요. 아래 물량이나 규격·작업 조건을 확인하면 해당 조건으로 계산할 수 있어요.'}</p>
    </aside>;
  }
  if (!['OK', 'PARTIAL', 'COMPUTED'].includes(response.status) || !response.result) return null;
  const result = response.result as ComputedResult;
  const separate = result.not_calculated?.map(item => item.item).filter(Boolean) ?? [];
  return <aside className="estimate-guidance" aria-label="계산 범위 안내">
    <strong>{response.work?.title || '선택한 공종'}의 계산 범위</strong>
    <p>{result.daily_volume
      ? '입력한 물량과 작업 조건으로 시공량을 구하고, 그에 필요한 작업 품을 계산했어요.'
      : '표준품셈의 단위당 작업 품에 입력한 물량을 적용해 계산했어요.'}
      {' '}이 결과가 제품·자재 구입비와 연관 공사까지 모두 포함한 금액을 뜻하지는 않아요. 포함 여부는 아래 내역과 미산정 항목에서 확인해 주세요.</p>
    {separate.length > 0 && <p className="estimate-guidance-separate">이번 계산에 포함되지 않은 항목: {separate.join(' · ')}</p>}
  </aside>;
}
