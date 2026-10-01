# WBETH historical rate: unresolved

The public Ethereum probe resolved adjacent block pairs around both fixed
boundaries: 31 August and 29 September 2026, 00:00 UTC. It verified chain ID 1
and the documented token address. The original attempt stopped because the
on-chain symbol is `wBETH`, while its strict check expected `WBETH`.

A separately frozen correction reused those blocks and accepted the exact
returned symbol. Chain ID and token decimals were read successfully. The
first historical `exchangeRate()` request returned **HTTP 403**. The second
rate was not requested. No rate growth, APR, staking income or trade P&L was
calculated. The response does not establish whether archive access, request
filtering or another provider restriction caused the rejection.

Both attempts are retained. There were 40 read requests in the original and
three in the correction. No transaction or account request was sent, and no
alternate provider was tried. Block records explicitly retain identity/time
fields and response hashes, rather than unrelated transaction hashes.

The Aster funding budget therefore remains a required-yield calculation.
WBETH income is not credited toward it. Even a successful Ethereum rate
measurement would still require BNB Chain consistency, acquisition and exit
prices, margin and hedge accounting before assessing the proposed route.

[Original attempt](../wbeth-historical-rate-probe/terminal.json) ·
[Correction result](terminal.json) ·
[Aster funding budget](../aster-collateral-clock-correction/readout.md)
