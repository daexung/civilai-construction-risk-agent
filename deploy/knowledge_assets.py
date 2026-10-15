"""Download immutable, digest-checked knowledge vectors. Never generate embeddings."""
import hashlib,json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    spec=json.loads((ROOT/'deploy/knowledge-assets.json').read_text())
    dest=ROOT/'data/knowledge';dest.mkdir(parents=True,exist_ok=True)
    for name,expected in spec['files'].items():
        assert name in ('manifest.json','vectors.parquet')
        target=dest/name
        if target.exists() and target.stat().st_size==expected['bytes'] and hashlib.sha256(target.read_bytes()).hexdigest()==expected['sha256']:
            continue
        temp=dest/(name+'.partial')
        url=f"https://github.com/{spec['repository']}/releases/download/{spec['tag']}/{name}"
        with urllib.request.urlopen(url,timeout=120) as source,temp.open('wb') as output:
            while block:=source.read(1024*1024):output.write(block)
        if temp.stat().st_size!=expected['bytes'] or hashlib.sha256(temp.read_bytes()).hexdigest()!=expected['sha256']:
            temp.unlink(missing_ok=True)
            raise ValueError('Knowledge asset checksum mismatch: '+name)
        temp.replace(target)
        print('Verified knowledge asset '+name,flush=True)
if __name__=='__main__':main()
