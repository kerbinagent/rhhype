FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl microsocks \
    && curl -fsSL https://repo.nordvpn.com/gpg/nordvpn_public.asc \
        -o /usr/share/keyrings/nordvpn_public.asc \
    && printf '%s\n' \
        'deb [signed-by=/usr/share/keyrings/nordvpn_public.asc] https://repo.nordvpn.com/deb/nordvpn/debian stable main' \
        > /etc/apt/sources.list.d/nordvpn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nordvpn \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/nordvpn-jp-proxy
RUN chmod 755 /usr/local/bin/nordvpn-jp-proxy

EXPOSE 1080/tcp
ENTRYPOINT ["/usr/local/bin/nordvpn-jp-proxy"]
