# Incomplete exploratory replay

The first closing-basis maker replay stopped at its 81,920-byte audit cap,
before the end of the previously retained market capture. It made 35 quote
requests; only 34 complete admissions fit in the trace. There were no
completed flow episodes before failure. An unresolved quote remained, so
complete net P&L is undefined. This is not a completed strategy result.

The entire failed trace and summary are preserved. Its chunked gzip writer
repeated overlapping reference windows in many independent gzip members.
The repeat uses the identical frozen economic rules, source capture and
admission window, with continuous lossless gzip and a separately reserved
131,072-byte trace cap. No market data is collected again.
