#!/bin/sh
set -eu

if [ ! -s /run/secrets/nord_token ]; then
    echo 'NordVPN token file is missing or empty' >&2
    exit 1
fi

# Docker preserves /run in a stopped container, but not its daemon processes.
# Remove only the NordVPN runtime files left by a previous container start.
rm -f /run/nordvpn/nordvpn.pid /run/nordvpn/nordvpnd.pid \
    /run/nordvpn/nordvpnd.sock /tmp/0-norduserd.sock
/etc/init.d/nordvpn start
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if nordvpn status >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# A saved login can reconnect even when the kill switch blocks account lookups.
if reconnect_result=$(nordvpn connect JP 2>&1); then
    printf '%s\n' "$reconnect_result"
else
    if nordvpn settings | grep -q '^Kill Switch: enabled$'; then
        nordvpn set killswitch off >/dev/null
    fi
    if ! nordvpn account >/dev/null 2>&1; then
        token_line=$(tr -d '\r\n' < /run/secrets/nord_token)
        case "$token_line" in
            'export NORD_TOKEN='*|NORD_TOKEN=*) nord_token=${token_line#*=} ;;
            *) nord_token=$token_line ;;
        esac
        unset token_line
        if [ -z "$nord_token" ]; then
            echo 'NordVPN token file contains no token' >&2
            exit 1
        fi
        if ! login_result=$(nordvpn login --token "$nord_token" 2>&1); then
            unset nord_token
            case "$login_result" in
                *'access token is not valid'*) echo 'NordVPN rejected the access token as invalid' >&2 ;;
                *'System Daemon'*) echo 'NordVPN system daemon is unavailable' >&2 ;;
                *) echo 'NordVPN token login failed' >&2 ;;
            esac
            exit 1
        fi
        unset nord_token
    fi
    nordvpn set technology nordlynx >/dev/null
    nordvpn set killswitch on >/dev/null
    nordvpn connect JP
fi

if ! nordvpn settings | grep -q '^Kill Switch: enabled$'; then
    nordvpn set killswitch on >/dev/null
fi

docker_gateway=$(ip -4 route show default dev eth0 | awk '$1 == "default" && $2 == "via" { print $3; exit }')
if [ -z "$docker_gateway" ]; then
    echo 'Could not determine the Docker gateway address' >&2
    exit 1
fi
if ! allowlist_result=$(nordvpn allowlist add subnet "$docker_gateway/32" 2>&1); then
    case "$allowlist_result" in
        *'is already on the allowlist.'*) ;;
        *) printf '%s\n' "$allowlist_result" >&2; exit 1 ;;
    esac
fi

vpn_status=$(nordvpn status)
printf '%s\n' "$vpn_status"
if ! printf '%s\n' "$vpn_status" | grep -q '^Status: Connected$'; then
    echo 'NordVPN did not report a connected state' >&2
    exit 1
fi
if ! printf '%s\n' "$vpn_status" | grep -q '^Country: Japan$'; then
    echo 'NordVPN did not report Japan as the exit country' >&2
    exit 1
fi

echo 'SOCKS5 proxy listening on port 1080 inside the container'
exec microsocks -i 0.0.0.0 -p 1080
