# Paper monitor checkpoint interruption, 1 October 2026

The broad paper monitor exited at18:34:57UTC after its estimated checkpoint batch exceeded the32MiB WAL reservation inside the existing128MiB database budget. Its final shutdown checkpoint also failed. Host process checks confirmed the prior process had exited; the separate review loop and dated-carry sampler remained alive.

The last durable checkpoint was **18:34:54.802744UTC**. Its exact state, snapshot, configuration, review baseline and full available failure log were preserved before recovery. Three retained positions were awaiting funding; none had active entry/exit exposure. The uncheckpointed interval and downtime are a coverage gap, not zero outcomes.

At **18:41:35.899691UTC**, the same monitor was resumed with `--report-seconds 0.5`, reducing the previous2second checkpoint interval. Strategy parameters, source code, fees, database cap, ledger and epoch were unchanged. The standard monitor lock prevents a second writer. The launcher checked the exact durable state and config before starting.

The retained18:42:15 check found a0.835second-old snapshot, all four feeds connected,102pairs,54.34%of one CPU core and22.95ms p95 lag. Ledger, positions, strategy epochs, config file and review baseline matched the preserved state. Coverage was conservatively confirmed resumed at18:42:14.795516. Subsequent18:43 checks remained fresh. Continued health observation is needed; the lost in-memory batch cannot be reconstructed.

Resource accounting: an initial1MiB research reservation was exceeded by preserving the1,193,975-byte full failure log. That mistake is recorded in reservationv2; a further1MiB was transferred from existing research headroom before restart. No retained artifact was deleted and the overall836,777,216-byte reservation was unchanged. The routine-review5MiB allocation was not used.
