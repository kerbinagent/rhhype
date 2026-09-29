# Japan-only NordVPN proxy

The `nordvpn-jp-proxy` Docker container runs NordVPN in its own network namespace and publishes a TCP SOCKS5 proxy on WSL localhost port 1080. The container reads the Nord access token from `../.env` as a read-only file. Keep that file private; it is not copied into the Docker image.

To stop or restart the container:

```sh
docker stop nordvpn-jp-proxy
docker start nordvpn-jp-proxy
docker logs --tail 30 nordvpn-jp-proxy
```

To route a single agent's supported network clients through Japan, load `proxy.env` in the shell that launches that agent:

```sh
set -a
. ./nordvpn-jp-proxy/proxy.env
set +a
# Start the agent here.
```

The agent or its HTTP client must support SOCKS proxy environment variables. `socks5h` requests DNS resolution through the proxy. MicroSocks in Ubuntu 24.04 supports TCP connections, not UDP. A tool that ignores these variables will use its normal network route.

To check the exit country from WSL:

```sh
curl --proxy socks5h://127.0.0.1:1080 --noproxy '' https://ipinfo.io/country
curl --noproxy '*' https://ipinfo.io/country
```

The first command should return `JP`; the second should show the normal direct connection's country.
