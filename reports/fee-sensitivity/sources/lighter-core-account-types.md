---
updatedAt: 2026-09-26T09:46:35.000Z
agentTools:
  projectIndex: https://apidocs.lighter.xyz/llms.txt
---

# Account Types

Lighter API users can operate under a Standard or Premium account.

#### Premium Account (Opt-in) -- Suitable for HFT, the lowest latency on Lighter. Part of [volume quota program](https://apidocs.lighter.xyz/docs/volume-quota-program).

Latency for maker & cancel orders is 0ms. Fee credits also count as staked LIT for the parameters described in the table.

| Staked LIT | sendTx/sendTxBatch per minute | Maker/Taker Fee Discount | Maker Fee | Taker Fee | Taker Latency | Sub-accounts |
| :--------- | :---------------------------- | :----------------------- | :-------- | :-------- | :------------ | :----------- |
| 0          | 4000                          |                          | 0.0040%   | 0.0280%   | 140 ms        | 64           |
| 1,000      | 5000                          | 2.5%                     | 0.0039%   | 0.0273%   | 140 ms        | 64           |
| 3,000      | 6000                          | 5%                       | 0.0038%   | 0.0266%   | 140 ms        | 64           |
| 10,000     | 7000                          | 10%                      | 0.0036%   | 0.0252%   | 140 ms        | 64           |
| 30,000     | 8000                          | 15%                      | 0.0034%   | 0.0238%   | 140 ms        | 64           |
| 100,000    | 12000                         | 20%                      | 0.0032%   | 0.0224%   | 140 ms        | 64           |
| 300,000    | 24000                         | 25%                      | 0.0030%   | 0.0210%   | 140 ms        | 64           |
| 500,000    | 48000                         | 30%                      | 0.0028%   | 0.0196%   | 140 ms        | 64           |

#### Plus Account (Opt-in) -- Suitable for latency-insensitive users, looking to get increased rate limits.

Access via the [changeAccountTier](https://apidocs.lighter.xyz/reference/changeaccounttier) endpoint.&#x20;

| Maker/Taker Fee | Taker Latency | Maker/Cancel Latency | sendTx/sendTxBatch per minute | Read-only weighted requests per minute | Sub-accounts |
| :-------------- | :------------ | :------------------- | :---------------------------- | :------------------------------------- | ------------ |
| 0.005%          | 300 ms        | 200 ms               | 4000                          | 24000                                  | 16           |

#### Standard Account (Default) -- Suitable for retail and latency-insensitive traders.

| Maker Fee | Taker Fee | Taker Latency | Cancel/Modify Latency | Maker Latency | Sub-accounts |
| :-------- | :-------- | :------------ | :-------------------- | ------------- | ------------ |
| 0%        | 0%        | 300 ms        | 300 ms                | 0ms           | 4            |

#### Account Switch

You can change your Account Type (tied to your L1 address) using the [`/changeAccountTier`](https://apidocs.lighter.xyz/reference/changeaccounttier) endpoint.

You may call that endpoint if at least 24 hours have passed since the last call. To upgrade account type, there is no cooldown.

*Python snippet to switch tiers*:

```python Python: switch to premium
import asyncio
import logging
import lighter
import requests

logging.basicConfig(level=logging.DEBUG)

BASE_URL = "https://mainnet.zklighter.elliot.ai"

# You can get the values from the system_setup.py script
# API_KEY_PRIVATE_KEY =
# ACCOUNT_INDEX =
# API_KEY_INDEX =


async def main():
    client = lighter.SignerClient(
        url=BASE_URL,
        private_key=API_KEY_PRIVATE_KEY,
        account_index=ACCOUNT_INDEX,
        api_key_index=API_KEY_INDEX,
    )

    err = client.check_client()
    if err is not None:
        print(f"CheckClient error: {err}")
        return

    auth, err = client.create_auth_token_with_expiry(
        lighter.SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY
    )

    response = requests.post(
        f"{BASE_URL}/api/v1/changeAccountTier",
        data={"account_index": ACCOUNT_INDEX, "new_tier": "premium"},
        headers={"Authorization": auth},
    )
    if response.status_code != 200:
        print(f"Error: {response.text}")
        return
    print(response.json())


if __name__ == "__main__":
    asyncio.run(main())
```
```python Python: switch to standard
import asyncio
import logging
import lighter
import requests

logging.basicConfig(level=logging.DEBUG)

BASE_URL = "https://mainnet.zklighter.elliot.ai"

# You can get the values from the system_setup.py script
# API_KEY_PRIVATE_KEY =
# ACCOUNT_INDEX =
# API_KEY_INDEX =


async def main():
    client = lighter.SignerClient(
        url=BASE_URL,
        private_key=API_KEY_PRIVATE_KEY,
        account_index=ACCOUNT_INDEX,
        api_key_index=API_KEY_INDEX,
    )

    err = client.check_client()
    if err is not None:
        print(f"CheckClient error: {err}")
        return

    auth, err = client.create_auth_token_with_expiry(
        lighter.SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY
    )

    response = requests.post(
        f"{BASE_URL}/api/v1/changeAccountTier",
        data={"account_index": ACCOUNT_INDEX, "new_tier": "standard"},
        headers={"Authorization": auth},
    )
    if response.status_code != 200:
        print(f"Error: {response.text}")
        return
    print(response.json())


if __name__ == "__main__":
    asyncio.run(main())
```

#### How fees are collected:

In isolated margin, fees are taken from the isolated position itself, but if needed, we automatically transfer from cross margin to keep the position healthy. In cross margin, fees are always deducted directly from the available cross balance.

Sub-accounts share the same tier as the main L1 address on the account.