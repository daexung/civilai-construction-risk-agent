import math
CONFIG = {'rule_version': 'chunk-v1', 'rule_target_est_tokens': 800, 'table_target_est_tokens': 1600,
          'safety_cap_est_tokens': 6000, 'overlap': 0,
          'token_method': 'estimate: ceil(글자 수 / 1.5). 외부 API 없음. 실제 모델 토큰 수 아님',
          'cap_note': '6,000은 추정 토큰 기준의 안전 상한(실제 모델 한도 확인은 임베딩 단계)'}

def est(text):
    return math.ceil(len(text)/1.5)
