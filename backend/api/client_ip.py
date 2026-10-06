"""Trust the Vercel header only behind Cloud Run IAM restricted to our proxy."""
import os
from ipaddress import ip_address

from fastapi import HTTPException, Request


def client_ip(request: Request) -> str | None:
    if os.getenv('CLIENT_IP_SOURCE') != 'vercel':
        return request.client.host if request.client else None
    # Deployment prerequisite: IAM required, only our Vercel caller has run.invoker.
    # Generic X-Forwarded-For and browser-supplied headers are never used here.
    value = request.headers.get('x-poomsemi-client-ip', '')
    try:
        address = ip_address(value)
        if '%' in value:
            raise ValueError('Scoped IP is not a public client identifier')
        return str(address.ipv4_mapped or address) if address.version == 6 else str(address)
    except ValueError:
        raise HTTPException(503, '접속 정보를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.') from None
