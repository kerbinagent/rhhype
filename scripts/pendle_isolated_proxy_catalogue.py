"""Explicit isolated SOCKS client correction; preserve the direct-run failures."""
import hashlib, io, json, subprocess
from pathlib import Path
import pendle_low_gas_market_preflight as original

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/pendle-isolated-proxy-catalogue-allocation-v1.json'

class Response(io.BytesIO):
    status=200

def proxy_get(url, timeout=30):
    result=subprocess.run(['curl','--silent','--show-error','--fail-with-body','--max-time',str(timeout),'--max-filesize','2000000','--proxy','socks5h://127.0.0.1:1080','--noproxy','',url],capture_output=True)
    if result.returncode:
        raise RuntimeError(f'curl exit {result.returncode}: '+result.stderr.decode(errors='replace')[:256]+'; body '+result.stdout.decode(errors='replace')[:512])
    return Response(result.stdout)

def main():
    plan=json.loads(PLAN.read_bytes())
    for pin in plan['input_pins']:
        assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest()==pin['sha256']
    original.PLAN=PLAN
    original.OUT=ROOT/'reports/pendle-isolated-proxy-catalogue'
    original.urllib.request.urlopen=proxy_get
    original.main()
    (original.OUT/'correction.json').write_text(json.dumps({'wrapper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'route':'isolated Japan SOCKS5 TCP, remote DNS; direct route unchanged','source_hash_in_terminal_is_original':True},indent=2)+'\n')

if __name__=='__main__':
    main()
