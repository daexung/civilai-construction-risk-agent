"""One bounded loopback reproduction using two exact cached evaluation questions."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8011/api/item-labor"
QUESTIONS = [
    "외벽에 방수모르타르를 15㎜ 두께로 바르려는데 ㎡당 미장공은 몇 인 들어?",
    "철판 두께 0.6㎜, 규격 400㎜짜리 스파이럴덕트를 해체하려면 m당 덕트공이 몇 인이야?",
]


def post(path: str, payload: dict, owner: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if owner:
        headers["X-Trial-Owner"] = owner
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    text = " 그리고 ".join(QUESTIONS)
    analyzed = post("/analyze", {"text": text})
    analysis = analyzed["analysis"]
    print("ANALYZE", json.dumps({
        "status": analyzed.get("status"),
        "scope_spans": [{"span_id": x["span_id"], "classification": x["classification"],
                         "text": x["text"]} for x in analysis.get("scope_spans", [])],
        "work_items": analysis.get("work_items", []),
    }, ensure_ascii=False))

    action_by_class = {
        "requested": "include_work",
        "background": "keep_background",
        "condition": "keep_condition",
        "excluded": "keep_excluded",
    }
    decisions = []
    for span in analysis.get("scope_spans", []):
        classification = span["classification"]
        action = action_by_class.get(classification)
        if action is None:
            print("STOP: analyzer returned a scope requiring a user choice", classification, span["span_id"])
            return 2
        decisions.append({"span_id": span["span_id"], "action": action})

    confirmed = post(f"/{analyzed['trial_id']}/confirm", {"decisions": decisions}, analyzed["owner_token"])
    items = confirmed.get("items", [])
    summarized = [{"item_id": x.get("item_id"), "request_text": x.get("request_text"),
                   "scope_status": x.get("scope_status"), "status": x.get("status"),
                   "pending_questions": x.get("pending_questions", [])} for x in items]
    print("CONFIRM", json.dumps({"status": confirmed.get("status"), "items": summarized}, ensure_ascii=False))

    if len(items) != 2:
        print("STOP: confirmation did not produce exactly two items; no search was attempted")
        return 3
    by_text = {q: next((x for x in items if x.get("request_text") == q), None) for q in QUESTIONS}
    if any(value is None for value in by_text.values()):
        print("STOP: request_text was not preserved exactly; no search was attempted")
        return 4

    results = []
    for question in QUESTIONS:
        item = by_text[question]
        found = post(f"/{analyzed['trial_id']}/items/{item['item_id']}/search", {}, analyzed["owner_token"])
        result_item = next(x for x in found.get("items", []) if x.get("item_id") == item["item_id"])
        results.append({"item_id": item["item_id"], "request_text": result_item.get("request_text"),
                        "search_status": result_item.get("search_status"),
                        "search_info": result_item.get("search_info"),
                        "status": result_item.get("status"),
                        "candidate_count": len(result_item.get("candidates", [])),
                        "pending_questions": result_item.get("pending_questions", []),
                        "result": result_item.get("result")})
    print("SEARCH", json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"HTTP reproduction failed: {exc}", file=sys.stderr)
        raise SystemExit(10)
