"""Turn chunks into model-tagged Parquet embeddings with resumable caching.

Run: python -m pipeline.embed --chunks data/processed/chunks.jsonl
     python -m pipeline.embed --chunks data/processed/chunks.jsonl --limit 5
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from shared.embedding import (ROOT, client, document_fingerprint, document_input,
                              document_title, embed_texts, retryable_error, settings)


def load_cache(path: Path) -> dict:
    cache = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                cache[(row["chunk_id"], row["text_sha256"], row["model"], row["dim"])] = row
                cache[("text", row["text_sha256"], row["model"], row["dim"])] = row
    return cache


def cached_row(cache: dict, chunk: dict, config) -> dict | None:
    fingerprint = document_fingerprint(chunk, config)
    return (cache.get((chunk["chunk_id"], fingerprint, config.model, config.dim))
            or cache.get(("text", fingerprint, config.model, config.dim)))


def write_parquet(chunks: list[dict], cache: dict, out: Path, config) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = []
    for chunk in chunks:
        fingerprint = document_fingerprint(chunk, config)
        row = cached_row(cache, chunk, config)
        if row:
            src = chunk["source"]
            rows.append({"chunk_id": chunk["chunk_id"], "section_no": chunk["section_no"],
                         "pdf": src["pdf"], "page": src["page"], "table_id": src["table_id"],
                         "bbox": src["bbox"], "text_sha256": fingerprint, "model": config.model,
                         "dim": config.dim, "vector": row["vector"]})
    schema = pa.schema([("chunk_id", pa.string()), ("section_no", pa.string()), ("pdf", pa.string()),
                        ("page", pa.int32()), ("table_id", pa.string()), ("bbox", pa.list_(pa.float64())),
                        ("text_sha256", pa.string()), ("model", pa.string()), ("dim", pa.int32()),
                        ("vector", pa.list_(pa.float32()))])
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), out)
    return len(rows)


def main() -> None:
    config = settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", default=str(ROOT / "data/processed/chunks.jsonl"))
    parser.add_argument("--cache", default=str(ROOT / "data/processed/embeddings.cache.jsonl"))
    parser.add_argument("--out", default=str(ROOT / f"data/processed/embeddings.{config.model}.parquet"))
    parser.add_argument("--limit", type=int, help="Maximum new chunks in this run")
    parser.add_argument("--batch", type=int, default=10)
    parser.add_argument("--pause", type=float, default=2.0)
    args = parser.parse_args()

    chunks = [json.loads(line) for line in Path(args.chunks).read_text(encoding="utf-8").splitlines()
              if line.strip()]
    cache_path = Path(args.cache)
    cache = load_cache(cache_path)
    missing = [chunk for chunk in chunks if cached_row(cache, chunk, config) is None]
    todo = missing[:args.limit] if args.limit is not None else missing
    print(f"청크 {len(chunks)}개 중 이미 임베딩 {len(chunks) - len(missing)}개, 이번 대상 {len(todo)}개")

    cli = client(config) if todo else None
    calls, done, started, stop_reason = 0, 0, time.perf_counter(), None
    batch_size = 1 if config.provider == "vertex" else args.batch
    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        texts = [document_input(chunk, config) for chunk in batch]
        titles = [document_title(chunk) for chunk in batch]
        vectors = None
        for attempt in range(5):
            try:
                calls += 1
                vectors = embed_texts(cli, texts, config=config, task="document", titles=titles)
                break
            except Exception as exc:
                if retryable_error(exc) and attempt < 4:
                    wait = 2 ** attempt
                    print(f"  임시 호출 오류({type(exc).__name__}), {wait}초 뒤 재시도")
                    time.sleep(wait)
                    continue
                stop_reason = type(exc).__name__  # Never print a credential-bearing SDK message.
                break
        if vectors is None:
            break
        with cache_path.open("a", encoding="utf-8") as file:
            for chunk, vector in zip(batch, vectors):
                row = {"chunk_id": chunk["chunk_id"], "text_sha256": document_fingerprint(chunk, config),
                       "model": config.model, "dim": config.dim, "vector": vector}
                cache[(row["chunk_id"], row["text_sha256"], config.model, config.dim)] = row
                cache[("text", row["text_sha256"], config.model, config.dim)] = row
                file.write(json.dumps(row) + "\n")
        done += len(batch)
        print(f"  {done}/{len(todo)} 완료 (호출 {calls}회)")
        if start + batch_size < len(todo):
            time.sleep(args.pause)

    count = write_parquet(chunks, cache, Path(args.out), config)
    print(f"이번 실행: 새 벡터 {done}개, API 호출 {calls}회, {time.perf_counter() - started:.1f}초")
    print(f"Parquet {count}/{len(chunks)}개 청크 -> {args.out}")
    if stop_reason:
        raise SystemExit(f"중단: {stop_reason}. 성공한 벡터는 캐시에 남아 재실행 때 이어집니다")


if __name__ == "__main__":
    main()
