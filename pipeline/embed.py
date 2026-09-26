# 청크(chunks.jsonl)를 Gemini 임베딩으로 바꿔 Parquet에 저장하는 단계
#
# 실행: python -m pipeline.embed --limit 5     # 먼저 5개로 호출·한도 확인
#       python -m pipeline.embed               # 나머지 전부 (중단되면 다시 실행하면 이어서 한다)
#
# 기준: https://ai.google.dev/gemini-api/docs/embeddings?hl=ko
#   - 모델 gemini-embedding-2는 task_type을 받지 않는다. 문서는 'title: … | text: …' 형식으로 넣는다
#   - 여러 입력을 contents에 그대로 넣으면 하나의 벡터로 합쳐진다. 청크마다 types.Content를 따로 만들어
#     batchEmbedContents의 개별 요청으로 보내고, 돌아온 벡터 수가 입력 수와 같은지 확인한다
#
# 성공한 벡터는 배치마다 캐시(embeddings.cache.jsonl)에 바로 덧붙인다. 다시 실행하면
# (청크 ID, 입력 해시, 모델, 차원)이 같은 것은 건너뛴다. 최종 결과는 embeddings.parquet이다.
# API 키는 .env의 GEMINI_API_KEY에서 읽고 출력하지 않는다.

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from shared.embedding import MODEL, DIM, client, document_input, query_input, embed_texts, sha256
def rate_limited(exc: Exception) -> bool:
    text = str(exc)
    return getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in text or "429" in text


def load_cache(path: Path) -> dict:
    cache = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                cache[(row["chunk_id"], row["text_sha256"], row["model"], row["dim"])] = row
    return cache


def write_parquet(chunks: list[dict], cache: dict, out: Path) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = []
    for c in chunks:
        row = cache.get((c["chunk_id"], sha256(document_input(c)), MODEL, DIM))
        if row:
            src = c["source"]
            rows.append({"chunk_id": c["chunk_id"], "section_no": c["section_no"], "pdf": src["pdf"],
                         "page": src["page"], "table_id": src["table_id"], "bbox": src["bbox"],
                         "text_sha256": row["text_sha256"], "model": MODEL, "dim": DIM, "vector": row["vector"]})
    schema = pa.schema([("chunk_id", pa.string()), ("section_no", pa.string()), ("pdf", pa.string()),
                        ("page", pa.int32()), ("table_id", pa.string()), ("bbox", pa.list_(pa.float64())),
                        ("text_sha256", pa.string()), ("model", pa.string()), ("dim", pa.int32()),
                        ("vector", pa.list_(pa.float32()))])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), out)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", default=str(ROOT / "data/processed/chunks.jsonl"))
    parser.add_argument("--cache", default=str(ROOT / "data/processed/embeddings.cache.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "data/processed/embeddings.parquet"))
    parser.add_argument("--limit", type=int, help="이번 실행에서 새로 임베딩할 최대 청크 수")
    parser.add_argument("--batch", type=int, default=10, help="한 번의 API 호출에 넣을 청크 수")
    parser.add_argument("--pause", type=float, default=2.0, help="호출 사이 대기(초)")
    args = parser.parse_args()

    chunks = [json.loads(line) for line in Path(args.chunks).read_text(encoding="utf-8").splitlines() if line.strip()]
    cache_path = Path(args.cache)
    cache = load_cache(cache_path)
    missing = [c for c in chunks if (c["chunk_id"], sha256(document_input(c)), MODEL, DIM) not in cache]
    todo = missing[:args.limit] if args.limit is not None else missing
    print(f"청크 {len(chunks)}개 중 이미 임베딩 {len(chunks) - len(missing)}개, 이번 대상 {len(todo)}개")

    cli = client() if todo else None
    calls, done, started, stop_reason = 0, 0, time.perf_counter(), None
    for start in range(0, len(todo), args.batch):
        batch = todo[start:start + args.batch]
        texts = [document_input(c) for c in batch]
        for attempt in range(3):
            try:
                calls += 1
                vectors = embed_texts(cli, texts)
                break
            except Exception as exc:  # noqa: BLE001 - SDK 예외 종류가 여러 가지다
                if rate_limited(exc) and attempt < 2:
                    wait = 30 * (attempt + 1)
                    print(f"  호출 한도(429). {wait}초 뒤 다시 시도")
                    time.sleep(wait)
                    continue
                stop_reason = f"{type(exc).__name__}: {str(exc)[:300]}"
                vectors = None
                break
        if vectors is None:
            break
        with open(cache_path, "a", encoding="utf-8") as f:
            for c, text, vec in zip(batch, texts, vectors):
                row = {"chunk_id": c["chunk_id"], "text_sha256": sha256(text), "model": MODEL, "dim": DIM,
                       "vector": vec}
                cache[(row["chunk_id"], row["text_sha256"], MODEL, DIM)] = row
                f.write(json.dumps(row) + "\n")
        done += len(batch)
        print(f"  {done}/{len(todo)} 완료 (호출 {calls}회)")
        if start + args.batch < len(todo):
            time.sleep(args.pause)

    n = write_parquet(chunks, cache, Path(args.out))
    print(f"이번 실행: 새 벡터 {done}개, API 호출 {calls}회, {time.perf_counter() - started:.1f}초")
    print(f"Parquet {n}/{len(chunks)}개 청크 -> {args.out}")
    if stop_reason:
        raise SystemExit(f"중단: {stop_reason}\n성공한 벡터는 캐시에 남았다. 다시 실행하면 이어서 한다")


if __name__ == "__main__":
    main()
