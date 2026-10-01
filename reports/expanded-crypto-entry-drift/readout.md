# Entry-price movement explains this sample

Across all five normally paired $100 trades, the entry cash gap deteriorated by $0.328141 between the signal and delayed simulated execution. All five deteriorated. Their actual cash total was −$0.225703; the sixth, failed-hedge rescue lost another $0.005850.

Holding each observed exit fixed and substituting its decision-time entry prices gives +$0.102438 for the five paired trades. This is an arithmetic decomposition, not a feasible strategy or five new profitable trades: changing entry execution could change later decisions and exits.

The sample points to disappearing entry prices as the main problem. Five trades cannot calibrate a stable penalty. A further RH/Core study should change how it handles short-lived signals or use a different execution design, then test on fresh data; repeating the same one-shot threshold is weak use of the budget.
