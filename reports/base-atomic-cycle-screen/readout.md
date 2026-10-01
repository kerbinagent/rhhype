# Base atomic cycle screen: transport failure

Frozen at a17cce1 before public reads. The public Base RPC returned HTTP 429 on request 12 during pool identity validation. No cycle quotes were requested, so profitability is unknown. All received contract responses, projected block identity, request hashes, and the failed request are preserved in trace.json.gz. This is not an economic rejection.

A separate explicit transport correction uses a five-second minimum request interval and retains the same pool universe, sizes, and three-round quote screen. No transactions or signatures are involved.
