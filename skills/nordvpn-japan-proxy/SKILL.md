---
name: nordvpn-japan-proxy
description: Use the workspace's isolated NordVPN Japan SOCKS5 proxy for selected WSL agents or programs, including starting, verifying, and troubleshooting it without changing host-wide routing or proxy settings.
---

# Opt-in NordVPN Japan proxy

Use this skill when a program in this workspace needs a Japan VPN exit but the rest of WSL must keep its normal route. Run the commands below from the workspace root. The implementation is in `nordvpn-jp-proxy/`; its `README.md`, `Dockerfile`, `entrypoint.sh`, and `proxy.env` are the source of truth.

## Safety and architecture

- The `nordvpn-jp-proxy` Docker container runs NordVPN in its own network namespace and exposes a TCP SOCKS5 listener on `127.0.0.1:1080` in WSL. Only clients configured to use this proxy are routed through Japan.
- Do not run `nordvpn connect` on the WSL host, change default routes, edit shell startup files, or set system-wide proxy variables.
- The workspace-root `.env` contains the Nord access token. Never print it, place it in logs or chat, copy it into the image, or include it in agent prompts. The container mounts it read-only at `/run/secrets/nord_token`.
- SOCKS5 here supports TCP, not arbitrary UDP. Applications that ignore proxy settings retain their direct route; do not claim they are protected.

## Start or recover

Check the exact container first:

```sh
docker ps -a --filter name=^/nordvpn-jp-proxy$ --format '{{.Names}} {{.Status}}'
```

If stopped, run `docker start nordvpn-jp-proxy`. If absent, ensure `.env` exists and is private, then build and create it:

```sh
docker build -t rhhype/nordvpn-jp-proxy:local ./nordvpn-jp-proxy
docker run -d --name nordvpn-jp-proxy --cap-add NET_ADMIN \
  -p 127.0.0.1:1080:1080 \
  --mount "type=bind,src=$PWD/.env,dst=/run/secrets/nord_token,readonly" \
  rhhype/nordvpn-jp-proxy:local
```

Inspect startup with `docker logs --tail 30 nordvpn-jp-proxy`; the entrypoint checks for `Country: Japan` before opening SOCKS. If startup fails, inspect logs and fix the specific issue. Do not paste the token into a command or log. Stop with `docker stop nordvpn-jp-proxy` when no longer needed.

## Use it for one program

Load proxy variables only in the child shell that launches the opted-in program:

```sh
( set -a; . ./nordvpn-jp-proxy/proxy.env; set +a; exec YOUR_PROGRAM )
```

Replace `YOUR_PROGRAM` with the actual command. The subshell prevents proxy variables from leaking into the calling shell. Alternatively, point an application's own SOCKS5 settings to `127.0.0.1:1080` and enable proxy-side DNS resolution (`socks5h` where supported). Test each application's proxy support; environment variables are not honored by every client.

Verify the proxy and unaffected direct route:

```sh
curl --silent --show-error --max-time 20 --proxy socks5h://127.0.0.1:1080 --noproxy '' https://ipinfo.io/country
curl --silent --show-error --max-time 20 --noproxy '*' https://ipinfo.io/country
```

The first response must be `JP`. The second should be the WSL host's normal exit country, which is not guaranteed to be a particular country. If the first is not `JP` or the proxy cannot be reached, do not silently fall back to a direct connection for an app that needs Japan.
