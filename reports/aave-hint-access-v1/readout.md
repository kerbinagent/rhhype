# Historical hint access remains unavailable

The fixed two-request study stopped at its second response-body cap. The
history endpoint returned HTTP200 with chunked transfer encoding, but its
decoded body exceeded 262,144 bytes. The collector retained exactly one extra
sentinel byte and published an unavailable terminal, with no projection.
No partial history rows were parsed into matches or economic evidence.

The preceding info response was complete: 121 bytes, reported maxLimit500,
and reported block coverage included the preselected range26103136–26103141.
That establishes endpoint/metadata access, not availability of the selected
transaction before inclusion. The attempted history query used limit100 and
offset0. It was not retried, paginated or narrowed after the failure.

The run used two requests and550ms. Retained bodies total262,266 bytes;
eight raw files total263,581 bytes. Independent review verified all9 frozen
pins, request identities, headers, body hashes, lengths, failure receipt and
terminal. All7 offline tests passed, including premature EOF of otherwise
valid JSON. The result is unavailable, not a no-match finding.

[Plan](plan.json), [terminal](run-v1/terminal.json),
[failure audit](root-review.json). The [preceding health crossing](../aave-state-transition-v1/readout.md)
remains admitted independently of this access failure.
