#!/usr/bin/env python3
"""DNS proxy that logs all queries and optionally spoofs responses.

Usage:
    python dns_proxy.py [--spoof domain=ip ...] [--bind IP] [--port PORT]

Listens on UDP port 5353 (unprivileged) by default.
Forwards all queries to upstream DNS (8.8.8.8) and logs them.
Spoof rules override specific domains to return a chosen IP.
"""

import argparse
import socket
import struct
import threading
import time
from datetime import datetime

UPSTREAM_DNS = "8.8.8.8"
UPSTREAM_PORT = 53


def parse_dns_name(data, offset):
    """Parse a DNS name from packet data, handling compression pointers."""
    labels = []
    seen = set()
    while offset < len(data):
        if offset in seen:
            break
        seen.add(offset)
        length = data[offset]
        if length == 0:
            offset += 1
            break
        elif (length & 0xC0) == 0xC0:
            # Compression pointer
            ptr = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            offset += 2
            suffix, _ = parse_dns_name(data, ptr)
            labels.append(suffix)
            return ".".join(labels), offset
        else:
            offset += 1
            labels.append(data[offset:offset + length].decode("ascii", errors="replace"))
            offset += length
    return ".".join(labels), offset


def build_response(query, spoof_ip):
    """Build a DNS response spoofing an A record."""
    # Copy header, flip QR bit, set response codes
    header = bytearray(query[:12])
    header[2] = 0x81  # QR=1, RD=1
    header[3] = 0x80  # RA=1
    header[6:8] = struct.pack("!H", 1)  # ANCOUNT = 1

    # Parse question section to include it in response
    qname_end = 12
    while qname_end < len(query) and query[qname_end] != 0:
        qname_end += query[qname_end] + 1
    qname_end += 1  # null terminator
    qname_end += 4  # QTYPE + QCLASS

    question = query[12:qname_end]

    # Answer: pointer to name in question + A record
    answer = b"\xc0\x0c"  # pointer to name at offset 12
    answer += struct.pack("!HHI", 1, 1, 300)  # TYPE A, CLASS IN, TTL 300
    answer += struct.pack("!H", 4)  # RDLENGTH
    answer += socket.inet_aton(spoof_ip)

    return bytes(header) + question + answer


def dns_proxy(bind_ip, port, spoof_rules, log_file):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind_ip, port))
    print(f"[*] DNS proxy listening on {bind_ip}:{port}")
    print(f"[*] Upstream: {UPSTREAM_DNS}:{UPSTREAM_PORT}")
    if spoof_rules:
        print(f"[*] Spoof rules:")
        for domain, ip in spoof_rules.items():
            print(f"    {domain} -> {ip}")
    print(f"[*] Logging to {log_file}")
    print()

    fh = open(log_file, "a")

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            if len(data) < 12:
                continue

            # Parse query name
            qname, qname_end = parse_dns_name(data, 12)
            qtype = struct.unpack("!H", data[qname_end:qname_end + 2])[0] if qname_end + 2 <= len(data) else 0
            type_str = {1: "A", 28: "AAAA", 5: "CNAME", 12: "PTR", 33: "SRV", 16: "TXT", 15: "MX", 6: "SOA", 255: "ANY"}.get(qtype, str(qtype))

            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            log_line = f"[{ts}] {addr[0]}:{addr[1]} -> {type_str} {qname}"

            # Check spoof rules
            spoofed = False
            for domain, spoof_ip in spoof_rules.items():
                if qname == domain or qname.endswith("." + domain):
                    response = build_response(data, spoof_ip)
                    sock.sendto(response, addr)
                    log_line += f" [SPOOFED -> {spoof_ip}]"
                    spoofed = True
                    break

            if not spoofed:
                # Forward to upstream
                upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                upstream.settimeout(3)
                try:
                    upstream.sendto(data, (UPSTREAM_DNS, UPSTREAM_PORT))
                    response, _ = upstream.recvfrom(4096)
                    sock.sendto(response, addr)

                    # Parse answer IPs for logging
                    ancount = struct.unpack("!H", response[6:8])[0]
                    if ancount > 0 and qtype == 1:
                        # Quick parse: find first A record answer
                        off = qname_end + 4  # skip question
                        for _ in range(ancount):
                            if off + 12 > len(response):
                                break
                            # Skip name (could be pointer)
                            if (response[off] & 0xC0) == 0xC0:
                                off += 2
                            else:
                                while off < len(response) and response[off] != 0:
                                    off += response[off] + 1
                                off += 1
                            rtype, rclass, rttl, rdlen = struct.unpack("!HHIH", response[off:off + 10])
                            off += 10
                            if rtype == 1 and rdlen == 4:
                                ip = socket.inet_ntoa(response[off:off + 4])
                                log_line += f" -> {ip}"
                                break
                            off += rdlen
                except socket.timeout:
                    log_line += " [TIMEOUT]"
                finally:
                    upstream.close()

            print(log_line)
            fh.write(log_line + "\n")
            fh.flush()

        except Exception as e:
            print(f"[!] Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="DNS logging proxy")
    parser.add_argument("--bind", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=5353, help="Listen port (default 5353)")
    parser.add_argument("--spoof", action="append", metavar="DOMAIN=IP",
                        help="Spoof domain to IP (can repeat)")
    parser.add_argument("--log", default="/tmp/vizio-dns.log", help="Log file path")
    args = parser.parse_args()

    spoof_rules = {}
    if args.spoof:
        for rule in args.spoof:
            domain, ip = rule.split("=", 1)
            spoof_rules[domain] = ip

    dns_proxy(args.bind, args.port, spoof_rules, args.log)


if __name__ == "__main__":
    main()
