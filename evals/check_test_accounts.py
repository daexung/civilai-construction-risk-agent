"""테스트 계정(TEST_USER_IDS)은 개인 한도 없이 서비스 전체 한도만 받는다. DB 없이 실행."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api import usage_limits as limits

TESTER, MEMBER = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
os.environ["TEST_USER_IDS"] = f" {TESTER} ,"
current = limits.now()

assert limits.tier(None) is False and limits.tier(MEMBER) is True and limits.tier(TESTER) == "tester"
assert limits._summary(current, 0, 0, False)["limit"] == limits.GUEST_LIMIT
assert limits._summary(current, 0, 0, True)["limit"] == limits.MEMBER_LIMIT
# 회원 한도를 넘은 테스트 계정도 계속 쓸 수 있다.
over = limits._summary(current, limits.MEMBER_LIMIT, limits.MEMBER_LIMIT, "tester")
assert over["limit"] == limits.SERVICE_LIMIT and over["remaining"] > 0
# 서비스 전체 한도(비용 안전 상한)는 테스트 계정에도 그대로 걸린다.
assert limits._summary(current, 10, limits.SERVICE_LIMIT, "tester")["service_remaining"] == 0
os.environ["TEST_USER_IDS"] = ""
assert limits.tier(TESTER) is True
print("PASS 테스트 계정: 개인 한도 없음, 서비스 전체 한도 유지, 설정 없으면 일반 회원")
