#!/usr/bin/env python3
"""Скачивает VPN-подписку и готовит config.yaml для mihomo на VPS."""

from __future__ import annotations

import argparse
import base64
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "clash-meta",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def decode_share_links(raw: bytes) -> list[str]:
    text = raw.decode("utf-8", "ignore").strip()
    compact = re.sub(rb"[^A-Za-z0-9+/=]", b"", raw)
    try:
        pad = b"=" * ((4 - len(compact) % 4) % 4)
        decoded = base64.b64decode(compact + pad).decode("utf-8", "ignore")
        if "://" in decoded:
            text = decoded
    except Exception:
        pass
    return [ln.strip() for ln in text.splitlines() if "://" in ln.strip()]


def q(params: dict[str, list[str]], *keys: str, default: str = "") -> str:
    for key in keys:
        if key in params and params[key]:
            return params[key][0]
    return default


def vless_to_proxy(uri: str, index: int) -> dict[str, object] | None:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme.lower() != "vless":
        return None
    host = parsed.hostname
    port = parsed.port
    uuid = urllib.parse.unquote(parsed.username or "")
    if not host or not port or not uuid:
        return None
    params = urllib.parse.parse_qs(parsed.query)
    name = urllib.parse.unquote(parsed.fragment) or f"vless-{index}"
    name = re.sub(r"[^\w\-.\[\] ]+", "_", name)[:64]
    network = q(params, "type", "network", default="tcp") or "tcp"
    security = q(params, "security", default="").lower()
    flow = q(params, "flow")
    sni = q(params, "sni", "servername")
    fp = q(params, "fp", "fingerprint", default="chrome") or "chrome"
    pbk = q(params, "pbk", "publicKey", "public-key")
    sid = q(params, "sid", "shortId", "short-id")
    path = q(params, "path", default="/") or "/"
    host_header = q(params, "host")
    service_name = q(params, "serviceName", "service-name")

    proxy: dict[str, object] = {
        "name": name,
        "type": "vless",
        "server": host,
        "port": int(port),
        "uuid": uuid,
        "network": network,
        "udp": True,
        "tls": security in {"reality", "tls"},
        "client-fingerprint": fp,
    }
    if flow:
        proxy["flow"] = flow
    if sni:
        proxy["servername"] = sni
    if security == "reality":
        reality: dict[str, str] = {}
        if pbk:
            reality["public-key"] = pbk
        if sid:
            reality["short-id"] = sid
        proxy["reality-opts"] = reality
    if network == "ws":
        ws: dict[str, object] = {"path": path}
        if host_header:
            ws["headers"] = {"Host": host_header}
        proxy["ws-opts"] = ws
    if network == "grpc" and service_name:
        proxy["grpc-opts"] = {"grpc-service-name": service_name}
    return proxy


def dump_from_proxies(proxies: list[dict[str, object]]) -> str:
    lines: list[str] = [
        "mixed-port: 7890",
        "allow-lan: true",
        'bind-address: "*"',
        "mode: rule",
        "log-level: info",
        "ipv6: false",
        "",
        "proxies:",
    ]
    for p in proxies:
        lines.append(f"  - name: \"{p['name']}\"")
        for key, value in p.items():
            if key == "name":
                continue
            if isinstance(value, bool):
                lines.append(f"    {key}: {'true' if value else 'false'}")
            elif isinstance(value, dict):
                lines.append(f"    {key}:")
                for sk, sv in value.items():
                    if isinstance(sv, dict):
                        lines.append(f"      {sk}:")
                        for ssk, ssv in sv.items():
                            lines.append(f"        {ssk}: \"{ssv}\"")
                    else:
                        lines.append(f"      {sk}: \"{sv}\"")
            elif isinstance(value, str):
                lines.append(f"    {key}: \"{value}\"")
            else:
                lines.append(f"    {key}: {value}")
    names = [str(p["name"]) for p in proxies]
    lines += [
        "",
        "proxy-groups:",
        "  - name: PROXY",
        "    type: url-test",
        "    proxies:",
        *[f"      - \"{n}\"" for n in names],
        "    url: https://www.gstatic.com/generate_204",
        "    interval: 300",
        "    tolerance: 150",
        "",
        "rules:",
        "  - MATCH,PROXY",
        "",
    ]
    return "\n".join(lines)


def adapt_ready_clash_yaml(text: str) -> str:
    """Подписка уже отдала Clash YAML — принудительно слушаем 7890 для docker."""
    text = re.sub(r"(?m)^mixed-port:\s*.*$", "mixed-port: 7890", text)
    text = re.sub(r"(?m)^port:\s*.*$", "mixed-port: 7890", text)
    if re.search(r"(?m)^allow-lan:\s*", text):
        text = re.sub(r"(?m)^allow-lan:\s*.*$", "allow-lan: true", text)
    else:
        text = "allow-lan: true\n" + text
    if re.search(r"(?m)^bind-address:\s*", text):
        text = re.sub(r"(?m)^bind-address:\s*.*$", 'bind-address: "*"', text)
    else:
        text = 'bind-address: "*"\n' + text
    if not text.endswith("\n"):
        text += "\n"
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    raw = fetch(args.url)
    text = raw.decode("utf-8", "ignore")

    if "proxies:" in text or "proxy-groups:" in text:
        out = adapt_ready_clash_yaml(text)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out, encoding="utf-8")
        print(f"OK: ready Clash YAML -> {args.out} ({len(out)} bytes)")
        return 0

    uris = decode_share_links(raw)
    proxies: list[dict[str, object]] = []
    seen: set[str] = set()
    for i, uri in enumerate(uris, start=1):
        proxy = vless_to_proxy(uri, i)
        if not proxy:
            continue
        name = str(proxy["name"])
        if name in seen:
            proxy["name"] = f"{name}-{i}"
        seen.add(str(proxy["name"]))
        proxies.append(proxy)

    if not proxies:
        print("Подписка не похожа ни на Clash YAML, ни на vless:// список", file=sys.stderr)
        print(text[:200], file=sys.stderr)
        return 1

    out = dump_from_proxies(proxies)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(out, encoding="utf-8")
    print(f"OK: {len(proxies)} proxies -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
