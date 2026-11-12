"""Bounded, SSRF-resistant retrieval of untrusted TON NFT metadata."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import ssl
from collections.abc import Sequence
from contextlib import suppress
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

DEFAULT_IPFS_GATEWAY_URL = "https://ipfs.io/ipfs"
MAX_METADATA_URL_LENGTH = 2048
MAX_METADATA_RESPONSE_BYTES = 256 * 1024
MAX_METADATA_HEADER_BYTES = 16 * 1024
MAX_METADATA_REDIRECTS = 3
METADATA_TIMEOUT_SECONDS = 4.0

_CID_V0_RE = re.compile(r"^Qm[1-9A-HJ-NP-Za-km-z]{44}$")
_CID_V1_RE = re.compile(r"^b[a-z2-7]{20,}$")
_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class UnsafeMetadataURI(ValueError):
    """A metadata URI or one of its resolved destinations is not safe."""


def _public_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address if address.is_global else None


def _select_public_ip(addresses: Sequence[str]) -> str | None:
    """Fail closed if DNS returns no addresses or mixes public and non-public IPs."""
    if not addresses:
        return None
    parsed = [_public_ip(value) for value in addresses]
    if any(address is None for address in parsed):
        return None
    first = parsed[0]
    return first.compressed if first is not None else None


def _normalize_http_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_METADATA_URL_LENGTH:
        return None
    if any(ord(character) < 32 or character.isspace() or character == "\\" for character in value):
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        return None
    if (
        parts.scheme.lower() not in {"http", "https"}
        or not parts.netloc
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or "%" in hostname
    ):
        return None

    scheme = parts.scheme.lower()
    expected_port = 443 if scheme == "https" else 80
    if port not in (None, expected_port):
        return None

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            ascii_host = hostname.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError:
            return None
        if (
            not ascii_host
            or len(ascii_host) > 253
            or ascii_host in {"localhost"}
            or ascii_host.endswith((".localhost", ".local", ".internal", ".test"))
            or any(not _DNS_LABEL_RE.fullmatch(label) for label in ascii_host.split("."))
        ):
            return None
        host_for_url = ascii_host
    else:
        public = _public_ip(str(literal_ip))
        if public is None:
            return None
        host_for_url = f"[{public.compressed}]" if public.version == 6 else public.compressed

    path = parts.path or "/"
    netloc = host_for_url
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def validate_ipfs_gateway_url(value: str) -> str:
    normalized = _normalize_http_url(value)
    if normalized is None:
        raise ValueError("IPFS gateway must be a safe absolute HTTP(S) URL")
    parts = urlsplit(normalized)
    if parts.scheme != "https" or parts.query or parts.path in {"", "/"}:
        raise ValueError("IPFS gateway must be HTTPS and include its gateway path")
    return normalized.rstrip("/")


def normalize_metadata_uri(
    value: object,
    *,
    ipfs_gateway_url: str = DEFAULT_IPFS_GATEWAY_URL,
) -> str | None:
    """Normalize HTTP(S) or IPFS URIs to a safe absolute HTTP(S) URL."""
    if not isinstance(value, str) or not value or len(value) > MAX_METADATA_URL_LENGTH:
        return None
    if value.lower().startswith("ipfs://"):
        try:
            parts = urlsplit(value)
            if parts.scheme.lower() != "ipfs" or parts.query and any(
                ord(character) < 32 for character in parts.query
            ):
                return None
            if parts.username is not None or parts.password is not None or parts.fragment:
                return None
            raw_cid = parts.netloc
            path = parts.path.lstrip("/")
            if raw_cid.lower() == "ipfs":
                segments = path.split("/")
                raw_cid = segments.pop(0) if segments else ""
                path = "/".join(segments)
            cid = raw_cid if _CID_V0_RE.fullmatch(raw_cid) else raw_cid.lower()
            if not (_CID_V0_RE.fullmatch(cid) or _CID_V1_RE.fullmatch(cid)):
                return None
            encoded_segments: list[str] = []
            if path:
                for segment in path.split("/"):
                    decoded = unquote(segment)
                    if (
                        not decoded
                        or decoded in {".", ".."}
                        or "/" in decoded
                        or "\\" in decoded
                        or any(ord(character) < 32 for character in decoded)
                    ):
                        return None
                    encoded_segments.append(
                        quote(decoded, safe="-._~!$&'()*+,;=:@")
                    )
            gateway = validate_ipfs_gateway_url(ipfs_gateway_url)
            gateway_parts = urlsplit(gateway)
            gateway_path = gateway_parts.path.rstrip("/")
            suffix = "/".join([quote(cid, safe=""), *encoded_segments])
            mapped = urlunsplit(
                (
                    gateway_parts.scheme,
                    gateway_parts.netloc,
                    f"{gateway_path}/{suffix}",
                    parts.query,
                    "",
                )
            )
            return _normalize_http_url(mapped)
        except (ValueError, UnicodeError):
            return None
    return _normalize_http_url(value)


def normalize_media_uri(
    value: object,
    *,
    ipfs_gateway_url: str = DEFAULT_IPFS_GATEWAY_URL,
) -> str | None:
    """Normalize a display media URI without fetching it server-side."""
    return normalize_metadata_uri(value, ipfs_gateway_url=ipfs_gateway_url)


async def _resolve_public_ip(hostname: str, port: int) -> str:
    """Resolve once and return a public address that the transport will connect to."""
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            loop = asyncio.get_running_loop()
            records = await loop.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except (OSError, UnicodeError) as exc:
            raise UnsafeMetadataURI("Metadata hostname did not resolve") from exc
        addresses = [record[4][0] for record in records]
    else:
        addresses = [str(literal)]

    selected = _select_public_ip(addresses)
    if selected is None:
        raise UnsafeMetadataURI("Metadata hostname resolved to a non-public address")
    return selected


async def _read_headers(
    reader: asyncio.StreamReader,
) -> tuple[int, dict[str, str]]:
    status_line = await reader.readline()
    if len(status_line) > 8192 or not status_line.endswith(b"\r\n"):
        raise ValueError("Invalid metadata HTTP status line")
    try:
        protocol, status_text, _reason = status_line.decode("ascii").rstrip("\r\n").split(" ", 2)
        status = int(status_text)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Invalid metadata HTTP status line") from exc
    if protocol not in {"HTTP/1.0", "HTTP/1.1"} or not 100 <= status <= 599:
        raise ValueError("Unsupported metadata HTTP response")

    headers: dict[str, str] = {}
    total = len(status_line)
    while True:
        line = await reader.readline()
        total += len(line)
        if total > MAX_METADATA_HEADER_BYTES or not line.endswith(b"\r\n"):
            raise ValueError("Metadata HTTP headers are too large or malformed")
        if line == b"\r\n":
            break
        if line[:1] in {b" ", b"\t"} or b":" not in line:
            raise ValueError("Malformed metadata HTTP header")
        name, raw_value = line[:-2].split(b":", 1)
        try:
            key = name.decode("ascii").strip().lower()
            value = raw_value.decode("latin-1").strip()
        except UnicodeError as exc:
            raise ValueError("Malformed metadata HTTP header") from exc
        if not key or not re.fullmatch(r"[a-z0-9!#$%&'*+.^_|~-]+", key):
            raise ValueError("Malformed metadata HTTP header name")
        if key in headers:
            raise ValueError("Duplicate metadata HTTP header")
        headers[key] = value
    return status, headers


async def _read_chunked_body(reader: asyncio.StreamReader) -> bytes:
    body = bytearray()
    while True:
        size_line = await reader.readline()
        if len(size_line) > 128 or not size_line.endswith(b"\r\n"):
            raise ValueError("Malformed chunked metadata response")
        size_text = size_line[:-2].split(b";", 1)[0].strip()
        if not size_text or not re.fullmatch(rb"[0-9a-fA-F]+", size_text):
            raise ValueError("Malformed chunk size")
        chunk_size = int(size_text, 16)
        if chunk_size == 0:
            trailer_bytes = 0
            while True:
                trailer = await reader.readline()
                trailer_bytes += len(trailer)
                if trailer_bytes > 4096 or not trailer.endswith(b"\r\n"):
                    raise ValueError("Malformed metadata response trailers")
                if trailer == b"\r\n":
                    return bytes(body)
        if len(body) + chunk_size > MAX_METADATA_RESPONSE_BYTES:
            raise ValueError("Metadata response exceeds the allowed size")
        chunk = await reader.readexactly(chunk_size)
        if await reader.readexactly(2) != b"\r\n":
            raise ValueError("Malformed chunk terminator")
        body.extend(chunk)


async def _read_response_body(
    reader: asyncio.StreamReader,
    headers: dict[str, str],
) -> bytes:
    content_encoding = headers.get("content-encoding", "identity").lower()
    if content_encoding not in {"", "identity"}:
        raise ValueError("Compressed metadata responses are not supported")

    transfer_encoding = headers.get("transfer-encoding", "").lower()
    if transfer_encoding:
        if transfer_encoding != "chunked":
            raise ValueError("Unsupported metadata transfer encoding")
        return await _read_chunked_body(reader)

    content_length = headers.get("content-length")
    if content_length is not None:
        if not re.fullmatch(r"[0-9]+", content_length):
            raise ValueError("Invalid metadata Content-Length")
        length = int(content_length)
        if length > MAX_METADATA_RESPONSE_BYTES:
            raise ValueError("Metadata response exceeds the allowed size")
        return await reader.readexactly(length)

    body = bytearray()
    while len(body) <= MAX_METADATA_RESPONSE_BYTES:
        chunk = await reader.read(
            min(8192, MAX_METADATA_RESPONSE_BYTES + 1 - len(body))
        )
        if not chunk:
            break
        body.extend(chunk)
    if len(body) > MAX_METADATA_RESPONSE_BYTES:
        raise ValueError("Metadata response exceeds the allowed size")
    return bytes(body)


async def _request_pinned(url: str) -> tuple[int, dict[str, str], bytes]:
    """Issue one HTTP request while connecting only to the previously checked IP."""
    parts = urlsplit(url)
    hostname = parts.hostname
    if hostname is None:
        raise UnsafeMetadataURI("Metadata URL has no hostname")
    port = 443 if parts.scheme == "https" else 80
    pinned_ip = await _resolve_public_ip(hostname, port)
    tls_context = ssl.create_default_context() if parts.scheme == "https" else None

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    reader, writer = await asyncio.open_connection(
        host=pinned_ip,
        port=port,
        ssl=tls_context,
        server_hostname=hostname if tls_context is not None else None,
        limit=MAX_METADATA_HEADER_BYTES + 1,
    )
    try:
        host_header = f"[{hostname}]" if ":" in hostname else hostname
        if parts.port is not None:
            host_header = f"{host_header}:{parts.port}"
        target = parts.path or "/"
        if parts.query:
            target = f"{target}?{parts.query}"
        request = (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "User-Agent: Vstore-TON-Metadata/1.0\r\n"
            "Accept: application/json, application/*+json\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        status, headers = await _read_headers(reader)
        if status in _REDIRECT_STATUSES:
            return status, headers, b""
        if status != 200:
            return status, headers, b""
        body = await _read_response_body(reader, headers)
        return status, headers, body
    finally:
        writer.close()
        with suppress(OSError, RuntimeError):
            await writer.wait_closed()


def _is_json_content_type(value: str | None) -> bool:
    if not value:
        return False
    media_type = value.split(";", 1)[0].strip().lower()
    if media_type in {"application/json", "application/ld+json"}:
        return True
    return media_type.startswith("application/") and media_type.endswith("+json")


async def fetch_metadata_json(
    value: object,
    *,
    ipfs_gateway_url: str = DEFAULT_IPFS_GATEWAY_URL,
    timeout_seconds: float = METADATA_TIMEOUT_SECONDS,
) -> dict[str, object] | None:
    """Fetch a small JSON object without DNS rebinding, redirect, or size blind spots.

    Metadata is display-only: all expected network, parsing, and policy failures return
    None so they can never invalidate an otherwise successful ownership verification.
    """
    current = normalize_metadata_uri(value, ipfs_gateway_url=ipfs_gateway_url)
    if current is None or timeout_seconds <= 0:
        return None

    try:
        async with asyncio.timeout(timeout_seconds):
            for redirect_count in range(MAX_METADATA_REDIRECTS + 1):
                status, headers, body = await _request_pinned(current)
                if status in _REDIRECT_STATUSES:
                    location = headers.get("location")
                    if not location or redirect_count >= MAX_METADATA_REDIRECTS:
                        return None
                    redirected = normalize_metadata_uri(
                        urljoin(current, location),
                        ipfs_gateway_url=ipfs_gateway_url,
                    )
                    if redirected is None:
                        return None
                    current = redirected
                    continue
                if status != 200 or not _is_json_content_type(headers.get("content-type")):
                    return None
                document = json.loads(body.decode("utf-8-sig"))
                if not isinstance(document, dict):
                    return None
                nested = document.get("metadata")
                return nested if isinstance(nested, dict) else document
    except Exception:
        # A metadata endpoint is untrusted optional display data, never an ownership
        # dependency. Do not let it leak network/parser errors into the verifier.
        return None
    return None
