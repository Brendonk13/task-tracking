"""Middleware that keeps this single-user app reachable from this machine only."""

from ipaddress import IPv6Address, ip_address

from django.http import HttpResponseForbidden

# Every address the loopback interface can present: 127.0.0.0/8 for IPv4, ::1 for
# IPv6, and ::ffff:127.0.0.1 for an IPv4 client on an IPv6 socket.
LOOPBACK_MESSAGE = "This server only accepts requests from localhost."


def is_loopback(address: str) -> bool:
    try:
        parsed = ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return parsed.is_loopback


class LocalhostOnlyMiddleware:
    """Reject any request whose peer is not on the loopback interface.

    The servers already bind to 127.0.0.1 (see the Makefile), so this is a second
    lock on the same door: it also covers someone starting `runserver 0.0.0.0:8000`
    or putting the app behind a proxy. REMOTE_ADDR is the real peer address as seen
    by the socket, so no forwarded header can spoof it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not is_loopback(request.META.get("REMOTE_ADDR", "")):
            return HttpResponseForbidden(LOOPBACK_MESSAGE)
        return self.get_response(request)
