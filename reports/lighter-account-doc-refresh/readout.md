# Account documentation refresh

Two bounded direct public requests to the Core and RH account-types Markdown
pages returned HTTP 403 on 1 October 2026. Both failures are retained; no
retry or account action followed. This does not establish either latency.

Separately, the web reader retrieved the current
[Core API account-types page](https://apidocs.lighter.xyz/docs/account-types),
which lists Standard maker processing at 0 ms and taker/cancel at 300 ms.
It could not retrieve the RH page. Core's schedule is not evidence of RH's
current schedule, and a published processing delay is not an observed
network-to-private-ack latency. The completed LIT study retains its frozen
400 ms assumption. No lower RH latency or below-minimum closing exemption
has been verified by this refresh.
