"""Use forwarding headers only from an explicitly trusted immediate peer.

Uvicorn must run with --no-proxy-headers so request.client is the socket peer.
Configured proxies must strip/overwrite client-supplied CF/X-Real-IP headers
and append/clean X-Forwarded-For. No implicit trust of loopback/private ranges.
"""

from ipaddress import ip_address, ip_network
from app.config import settings


def _address(value):
    try:
        value = (value or "").strip()
        if "%" in value:
            return None
        return ip_address(value)
    except ValueError:
        return None


def client_ip(request):
    peer = _address(request.client.host if request.client else None)
    fallback = str(peer) if peer else None
    networks = []
    for value in settings.TRUSTED_PROXY_CIDRS.split(","):
        try:
            networks.append(ip_network(value.strip()))
        except ValueError:
            pass  # invalid configuration grants no trust

    def trusted(address):
        return address is not None and any(address in n for n in networks)

    if not trusted(peer):
        return fallback
    for header in ("cf-connecting-ip", "x-real-ip"):
        address = _address(request.headers.get(header))
        if address is not None:
            return str(address)
    raw = request.headers.get("x-forwarded-for")
    if raw:
        chain = [_address(part) for part in raw.split(",")]
        if all(a is not None for a in chain):
            # Walk from the socket toward the client; stop at first untrusted hop.
            # Never accept an arbitrary leftmost client-supplied prefix.
            for address in reversed(chain):
                if not trusted(address):
                    return str(address)
            return str(chain[0])
    return fallback
