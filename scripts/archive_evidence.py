#!/usr/bin/env python3
"""Archive only public research evidence, with per-file SHA-256 checksums.
Run after collectors finish; never includes workspace .env or credentials.
"""
import datetime,hashlib,json,pathlib,tarfile
ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    out=ROOT/'data/evidence';out.mkdir(parents=True,exist_ok=True);paths=sorted((ROOT/'data/raw').rglob('*'));rows=[]
    for p in paths:
        if not p.is_file() or p.is_symlink():continue
        b=p.read_bytes();rows.append({'path':str(p.relative_to(ROOT)),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
    archive=out/'public-market-evidence.tar.gz'
    with tarfile.open(archive,'w:gz',compresslevel=6) as tar:
        for r in rows:tar.add(ROOT/r['path'],arcname=r['path'],recursive=False)
    info={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'archive':archive.name,
          'archive_bytes':archive.stat().st_size,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
          'file_count':len(rows),'uncompressed_bytes':sum(r['bytes'] for r in rows),'files':rows}
    (out/'manifest.json').write_text(json.dumps(info,indent=2)+'\n')
    print({k:v for k,v in info.items() if k!='files'})
if __name__=='__main__':main()
