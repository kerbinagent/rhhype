# Cash-only maker exit check — completed exploratory replay

Both independent portfolios used the same completed LIT capture and prior $100 maker quotes. Removing the 5 bp reserve from the take-profit decision produced exactly the prior execution traces: BUY 4,573 rows and SELL 4,567 rows after label normalization. No take-profit request occurred in either version.

BUY: 83 quotes, 81 without attributed flow, two paired closes, cash −$0.059399 and after capital plus stress −$0.11739961. SELL: 83 quotes, 81 without flow, two paired closes, cash −$0.086122 and stressed −$0.14424681. The only cash winner was the already observed approximately $16 partial fill (+$0.000830). All portfolios ended flat with no rescue or unknown episode.

The fill audit passed 12 taker walks and four maker flow matches (16 fills). The quote audit passed 166 quote and activation checks plus 12 depth depletions. Real take-profit checks were vacuous (zero triggers); synthetic tests on both sides demonstrate the corrected cash-only trigger. These are identical historical outcomes, not new independent observations. Public queue attribution and private order execution remain conditional.
