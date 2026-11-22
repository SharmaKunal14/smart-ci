"""Fixed-host HTTPS, bounded responses and no retries, redirects or proxy routing."""

import http.client
import json
import os
import ssl
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes


class Transport(Protocol):
    def request(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> Reply: ...


class HTTPS:
    def __init__(
        self, host: Literal["api.openai.com", "api.github.com"], token: str
    ) -> None:
        if host not in {"api.openai.com", "api.github.com"}:
            raise ValueError("unsupported API host")
        if (
            not token
            or len(token) > 4096
            or any(ord(c) < 33 or ord(c) > 126 for c in token)
        ):
            raise ValueError("missing or invalid credential")
        self._host, self._token = host, token

    def request(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> Reply:
        # A separate isolated interpreter bounds DNS, TLS, headers and slow body
        # reads together. Credentials travel over stdin, never argv or logs.
        request = json.dumps(
            {
                "host": self._host,
                "token": self._token,
                "method": method,
                "path": path,
                "body": body,
            }
        ).encode()
        if len(request) > 270_336:
            raise ValueError("request exceeds limit")
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-m", "smartci.investigation.http"],
                input=request,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
                env={"PATH": os.defpath},
            )
            if result.returncode or len(result.stdout) > 1_048_600:
                raise OSError("API transport failed")
            status, separator, raw = result.stdout.partition(b"\n")
            if not separator or not status.isdigit():
                raise OSError("API transport failed")
            return Reply(int(status), raw)
        except (OSError, subprocess.SubprocessError):
            raise OSError("API transport failed") from None

    def _request(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> Reply:
        if (
            not path.startswith("/")
            or path.startswith("//")
            or any(ord(c) < 33 for c in path)
        ):
            raise ValueError("invalid API path")
        payload = (
            json.dumps(body, separators=(",", ":")).encode()
            if body is not None
            else None
        )
        if payload is not None and len(payload) > 262_144:
            raise ValueError("request exceeds limit")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "smartci-budgeted-investigation/1",
        }
        if self._host == "api.github.com":
            headers.update(
                {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
            )
        connection = http.client.HTTPSConnection(
            self._host, timeout=20, context=ssl.create_default_context()
        )
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("response exceeds limit")
            return Reply(response.status, raw)
        except (OSError, http.client.HTTPException):
            raise OSError("API transport failed") from None
        finally:
            connection.close()


if __name__ == "__main__":
    try:
        raw_request = sys.stdin.buffer.read(270_337)
        if len(raw_request) > 270_336:
            raise ValueError("request exceeds limit")
        request = json.loads(raw_request)
        if request["host"] not in {"api.openai.com", "api.github.com"}:
            raise ValueError("unsupported host")
        reply = HTTPS(request["host"], request["token"])._request(
            request["method"], request["path"], request["body"]
        )
        sys.stdout.buffer.write(str(reply.status).encode() + b"\n" + reply.body)
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit(2) from None
