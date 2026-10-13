"""(2b단계, 한 번만 실행) 자료 폴더에 섞여 있던 과거 검사 기록을 실행 기록 폴더로 옮기고, 자료 폴더의 해시 목록을 다시 만든다.

과거 기록은 바이트 그대로 옮긴다(내용을 만들거나 고치지 않는다). 복구할 수 없는 기록은 복구 불가로 적는다.
"""
import json
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
import run_records as rr  # noqa: E402

REL = 'rk-complete-82c206c61e21-37f81b5cfb1b'
CS = 'cs-37f81b5cfb1b-46f4f035c0fa'
REL_DIR = WORK / 'out' / REL
CS_DIR = WORK / 'out/chunks' / CS
BASE = WORK / 'baseline/before-02b'


def past(target, run_id, tool, files, status, note, verified=None):
    d = rr.RUNS / target / run_id
    if d.exists():
        raise SystemExit(f'이미 있음: {d}')
    d.mkdir(parents=True)
    for name, src in files.items():
        shutil.copy2(src, d / name)
    rr.write_json(d / 'run_manifest.json', {
        'run_id': run_id, 'tool': tool, 'target_id': target, 'record_kind': 'preserved_past_run', 'status': status,
        'note': note, 'files_sha256': {n: rr.sha_file(d / n) for n in sorted(files)},
        'verified_data_files_sha256': verified,
        'archived_by': 'checks/archive_past_runs.py (2b단계). 파일은 바이트 그대로 옮김'})
    rr.update_index(rr.RUNS / target)


def main():
    old_rel_manifest = json.loads((BASE / 'release_out/manifest.json').read_text(encoding='utf-8'))
    old_cs_manifest = json.loads((BASE / 'chunk_out/manifest.json').read_text(encoding='utf-8'))
    v_post = json.loads((REL_DIR / 'verification.json').read_text(encoding='utf-8'))
    v_cs = json.loads((CS_DIR / 'verification.json').read_text(encoding='utf-8'))
    # 1) 1b 원문 검사(00:17:43): JSON은 덮어써져 없다. 표준 출력 기록만 남아 있다
    past(REL, '20261012T001743-verify_db', 'verify_db', {'stdout.txt': BASE / 'logs/verify_db_last_run.txt'},
         'passed_text_log_only',
         '1b 단계 검사(재적재·중단 검사 포함). 원래 verification.json·example_queries.json·manifest.json은 00:42:04 재실행으로 '
         '덮어써져 사본이 없다(복구 불가). 남은 것은 표준 출력 기록(검사 이름 51줄, 모두 PASS)뿐이며 상세 값은 없다.')
    # 2) 청킹 뒤 원문 검사 재실행(00:42:04, 재적재 없이): 자료 폴더에 있던 결과를 바이트 그대로 옮긴다
    past(REL, '20261012T004204-verify_db', 'verify_db',
         {'verification.json': REL_DIR / 'verification.json', 'example_queries.json': REL_DIR / 'example_queries.json',
          'stdout.txt': BASE / 'logs/verify_db_post_chunking_stdout.txt',
          'data_manifest_written_by_run.json': BASE / 'release_out/manifest.json'},
         'passed' if v_post['failed'] == 0 else 'failed',
         f"청킹 뒤 원문 보존 확인(재적재 없이). 통과 {v_post['passed']}, 실패 {v_post['failed']}. 이 실행이 1b 기록을 덮어썼다.",
         old_rel_manifest['files_sha256'])
    # 3) 청킹 검사(00:41:43, --reload): 자료 폴더의 verification.json을 옮긴다. 당시 manifest의 해시는 이 파일과 맞지 않았다
    past(CS, '20261012T004143-verify_chunks', 'verify_chunks',
         {'verification.json': CS_DIR / 'verification.json', 'stdout.txt': BASE / 'logs/verify_chunks_last_run.txt',
          'data_manifest_at_run_end.json': BASE / 'chunk_out/manifest.json'},
         'passed' if v_cs['failed'] == 0 else 'failed',
         f"2단계 청킹 검사(--reload 포함). 통과 {v_cs['passed']}, 실패 {v_cs['failed']}. 같은 단계의 첫 실행(실패 2개, 검사 가정 오류) 결과 파일은 "
         "이 실행이 덮어써 남아 있지 않다. 당시 manifest.json의 verification.json 해시는 재적재 중 이전 파일 기준이라 이 파일과 다르다.",
         {k: v for k, v in old_cs_manifest['files_sha256'].items() if k != 'verification.json'})
    # 자료 폴더에서 검사 결과를 빼고(옮긴 사본이 실행 기록에 있음) 해시 목록을 다시 만든다
    for p in (REL_DIR / 'verification.json', REL_DIR / 'example_queries.json', CS_DIR / 'verification.json'):
        p.unlink()
    rr.write_json(CS_DIR / 'manifest.json', {'chunk_set_id': CS, 'files_sha256': {
        p.name: rr.sha_file(p) for p in sorted(CS_DIR.iterdir()) if p.is_file() and p.name != 'manifest.json'}})
    rr.write_json(REL_DIR / 'manifest.json', {
        'release_id': REL, 'status': 'loaded_complete',
        'files_sha256': {p.name: rr.sha_file(p) for p in sorted(REL_DIR.iterdir()) if p.is_file() and p.name != 'manifest.json'},
        'note': '자료 파일 목록(검색 입력 search_records.jsonl 포함). 검사 결과는 out/verification_runs/<이 ID>/에 실행별로 있다.'})
    print('archived')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
