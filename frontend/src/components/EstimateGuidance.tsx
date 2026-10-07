import { ChatResponse, ComputedResult } from '../types';

export default function EstimateGuidance({ response }: { response: ChatResponse }) {
  if (response.status === 'MISSING_INFO') {
    const names = response.questions.map(question => question.name);
    const splitKind = (name: string) => name.startsWith('attach_') ? 'attach' : name === 'named' ? 'named' : name.startsWith('split_') ? 'split' : '';
    const kinds = new Set(names.map(splitKind));
    if (names.length && !kinds.has('')) {
      const [title, body] = kinds.size === 1 && kinds.has('attach')
        ? ['조건이 어느 공종에 해당하는지 확인이 필요해요', '장비·시공 조건이 어느 공종의 것인지 문장만으로는 알 수 없어요. 고른 공종에만 그 조건을 적용해요.']
        : kinds.size === 1 && kinds.has('named')
          ? ['여러 공종인지 확인이 필요해요', '물량 없이 공종 이름만 이어져 있어요. 따로 견적하면 공종마다 필요한 물량을 이어서 물어볼게요.']
          : ['여러 공종으로 나눌지 확인이 필요해요', '물량이 없는 문장은 별도 공종인지 앞 공종의 조건인지 확실하지 않아요. 별도 공종이면 그 공종의 물량을 이어서 확인할게요.'];
      return <aside className="estimate-guidance" aria-label="공종 나누기 확인">
        <strong>{title}</strong>
        <p>{body}</p>
      </aside>;
    }
    const onlyWork = names.length === 1 && names[0] === 'work';
    const pumpConditions = names.some(name => ['pump_size', 'slump_band', 'facility_type', 'site_type'].includes(name));
    return <aside className="estimate-guidance" aria-label="추가 조건 안내">
      <strong>{onlyWork ? '먼저 계산할 공종을 골라 주세요' : '이 조건이 필요한 이유'}</strong>
      <p>{onlyWork ? '적용할 품셈을 선택하면 해당 공종에 필요한 조건을 확인할 수 있어요.'
        : pumpConditions ? '콘크리트 타설은 펌프차 규격·슬럼프·작업 여건에 따라 시공량과 비용이 달라져요. 아래에서 추가로 필요한 조건을 확인해 주세요.'
        : '공종마다 품셈을 적용하는 기준이 달라요. 아래 물량이나 규격·작업 조건을 확인하면 해당 조건으로 계산할 수 있어요.'}</p>
    </aside>;
  }
  if (['OK', 'PARTIAL'].includes(response.status) && response.items?.length) {
    return <aside className="estimate-guidance" aria-label="계산 범위 안내">
      <strong>묶음 견적의 계산 범위</strong>
      <p>계산한 공종별 품셈 직접비(일위대가 × 물량)를 더한 뒤, 간접노무비·보험료·일반관리비·이윤·부가세는 합친 금액으로 한 번만 계산했어요.
        {' '}제품·자재 구입비, 연관 공사, 계산하지 못한 공종까지 포함한 전체 공사비는 아니에요. 공종별 포함·제외·미산정 항목은 아래 공종 이름을 눌러 확인해 주세요.</p>
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
