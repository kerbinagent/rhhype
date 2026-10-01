# Core ETH collateral eligibility — 1 October 2026

One public assetDetails response at 02:33:23 UTC confirms ETH is enabled:
LTV 70%, liquidation threshold 85%, liquidation factor 95%, liquidation fee
2%, user cap 2,000 ETH, global cap 10,000 ETH, supplied 6,841.7953235055 ETH.
These are deployment settings, not a user account's enabled status or a
reservation of remaining capacity. The raw gzip and SHA provenance are saved.

The [official margin documentation](https://docs.lighter.xyz/trading/multi-asset-margin)
explicitly supports ETH collateral offsetting a short ETH perpetual. Risk
value discounts ETH by LTV; liquidation value uses the higher threshold.
Perpetual P&L enters the USDC portfolio balance. Unified account mode and
asset eligibility are required. Caps and changing parameters still matter.
The same page has a launch warning excluding spot purchases financed by
non-USDC collateral, despite a broader example later on. Research therefore
assumes cash-funded spot, never a leveraged spot purchase.

This is a distinct capital-efficiency hypothesis. The earlier 2x-capital
historical screen remains valid for its own assumption. A fixed-quantity
hedge, settlement cash, adverse oracle/mark moves and explicit unwind still
need evidence; no profit or safe leverage is established. No account was
read or changed, and no SDK was installed. Borrow/debit charges are not
assumed absent merely because this metadata has no interest field.

Request and storage limits were committed before the single request in
2c6d4f8. Source <=4 KiB, raw <=8 KiB, control <=2 KiB, this note <=2 KiB;
total reservation 16 KiB inside the existing allowance.
