"""One fixed transport correction after sandbox DNS denied every request."""
import hashlib,json
from pathlib import Path
import paradex_public_preflight as p
R=Path(__file__).resolve().parents[1];P=R/'reports/experiment-storage/paradex-public-transport-allocation-v1.json'
plan=json.loads(P.read_bytes());assert hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest()==plan['original_source_sha256']
p.OUT_UNUSED=None
p.O=R/'reports/paradex-public-transport';p.P=P
# The original function validates __file__; retain its original source hash in plan.
p.main()
