"""Reading public web pages safely (the `web.read` tool).

Only http(s) to public internet addresses: every host (including each
redirect) is resolved and refused if it points at this machine, the local
network, link-local or other reserved ranges, so a planted link can't make
ULTRON probe your router, Core itself or other private services.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
USER_AGENT = "ULTRON/0.1 (personal assistant; reads pages on the owner's request)"


class WebError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


def _public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_global and not addr.is_multicast


async def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebError("Only http and https web addresses can be read.")
    if parts.username or parts.password:
        raise WebError("Addresses with a user name or password aren't allowed.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            parts.hostname,
            parts.port or (443 if parts.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        raise WebError(f"Couldn't find {parts.hostname}.", retryable=True) from None
    if not infos or not all(_public(info[4][0]) for info in infos):
        raise WebError("That address is on a private or local network, so it can't be read.")


class _Text(HTMLParser):
    SKIP = frozenset({"script", "style", "noscript", "svg", "head", "nav", "footer", "form"})
    BLOCK = frozenset(
        {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    parser = _Text()
    parser.feed(html)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line)
    return " ".join(parser.title.split()), text


async def read(url: str, client: httpx.AsyncClient, *, max_chars: int = 60_000) -> dict[str, str]:
    for _ in range(MAX_REDIRECTS + 1):
        await check_url(url)
        try:
            async with client.stream(
                "GET",
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=15.0,
                follow_redirects=False,
            ) as resp:
                if resp.is_redirect:
                    url = urljoin(url, resp.headers.get("location", ""))
                    continue
                if resp.status_code >= 400:
                    raise WebError(
                        f"The page answered with HTTP {resp.status_code}.",
                        retryable=resp.status_code >= 500,
                    )
                kind = resp.headers.get("content-type", "")
                if not any(t in kind for t in ("text/html", "text/plain", "application/xhtml")):
                    raise WebError(f"That address isn't a web page ({kind or 'unknown type'}).")
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                text = body.decode(resp.encoding or "utf-8", errors="replace")
        except httpx.HTTPError as exc:
            raise WebError(
                f"Couldn't load the page ({type(exc).__name__}).", retryable=True
            ) from None
        title, content = html_to_text(text) if "html" in kind else ("", text)
        return {"url": url, "title": title, "text": content[:max_chars]}
    raise WebError("Too many redirects.")
