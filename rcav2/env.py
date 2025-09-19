# Copyright © 2025 Red Hat
# SPDX-License-Identifier: Apache-2.0

import ssl
import httpx
import pathlib
import logging
from httpx_gssapi import HTTPSPNEGOAuth, OPTIONAL  # type: ignore
from rcav2.config import SF_DOMAIN


class Env:
    """The RCAv2 application environment"""

    def __init__(self, debug):
        lvl = logging.DEBUG if debug else logging.INFO
        logging.basicConfig(format="%(asctime)s %(levelname)9s %(message)s", level=lvl)
        self.cookie = None
        self.httpx = make_httpx_client()
        self.auth = HTTPSPNEGOAuth(mutual_authentication=OPTIONAL)
        self.log = logging.getLogger("rcav2")

    def close(self):
        if self.cookie:
            with open(".cookie", "w") as f:
                f.write(self.cookie)


def make_httpx_client() -> httpx.AsyncClient:
    """Setup the httpx client using local CA."""
    # Load local CA
    verify = True
    local_ca = "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem"
    if pathlib.Path(local_ca).exists():
        verify = ssl.create_default_context(cafile=local_ca)  # type: ignore

    # Restore cookies
    cookies = httpx.Cookies()
    try:
        cookie = open(".cookie").read()
        cookies.set("mod_auth_openidc_session", cookie, domain=SF_DOMAIN)
    except FileNotFoundError:
        pass

    # Create the client
    return httpx.AsyncClient(follow_redirects=True, verify=verify, cookies=cookies)
