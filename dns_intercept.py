#!/usr/bin/env python3
"""DNS interceptor using a TUN interface.

Sets the TV's DNS to our TUN IP, captures all DNS queries,
logs them, and responds with real upstream answers (or spoofs).

Usage:
    python dns_intercept.py [--spoof domain=ip ...]
"""

import argparse
import fcntl
import os
import socket
import struct
import threading
from datetime import datetime

# TUN constants
TUNSETIFF = 0x400454ca
TUNSETOWNER = 0x400454cc
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000

TUN_IP = "10.99.99.1"
TUN_NETMASK = "255.255.255.0"
UPSTREAM_DNS = "8.8.8.8"
LOG_FILE = "/tmp/vizio-dns.log"


def create_tun(name="tun_vizio"):
    """Create a TUN interface and return the fd."""
    fd = os.open("/dev/net/tun", os.O_RDWR)
    ifr = struct.pack("16sH", name.encode(), IFF_TUN | IFF_NO_PI)
    fcntl.ioctl(fd, TUNSETIFF, ifr)
    fcntl.ioctl(fd, TUNSETOWNER, os.getuid())
    # Configure the interface
    os.system(f"ip addr add {TUN_IP}/24 dev {name}")
    os.system(f"ip link set {name} up")
    print(f"[*] TUN interface '{name}' created with IP {TUN_IP}")
    return fd, name


def parse_dns_name(data, offset):
    """Parse a DNS name from raw bytes."""
    labels = []
    seen = set()
    orig_offset = offset
    jumped = False
    while offset < len(data):
        if offset in seen:
            break
        seen.add(offset)
        length = data[offset]
        if length == 0:
            if not jumped:
                orig_offset = offset + 1
            break
        elif (length & 0xC0) == 0xC0:
            ptr = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            if not jumped:
                orig_offset = offset + 2
            jumped = True
            offset = ptr
            continue
        else:
            offset += 1
            labels.append(data[offset:offset + length].decode("ascii", errors="replace"))
            offset += length
            if not jumped:
                orig_offset = offset
    return ".".join(labels), orig_offset


def build_ip_header(src_ip, dst_ip, payload_len):
    """Build an IPv4 header."""
    version_ihl = 0x45
    tos = 0
    total_len = 20 + payload_len
    ident = os.getpid() & 0xFFFF
    flags_frag = 0x4000  # Don't fragment
    ttl = 64
    protocol = 17  # UDP
    checksum = 0
    src = socket.inet_aton(src_ip)
    dst = socket.inet_aton(dst_ip)

    header = struct.pack("!BBHHHBBH4s4s",
                         version_ihl, tos, total_len, ident,
                         flags_frag, ttl, protocol, checksum, src, dst)
    # Calculate checksum
    s = 0
    for i in range(0, len(header), 2):
        s += (header[i] << 8) + header[i + 1]
    s = (s >> 16) + (s & 0xFFFF)
    s = ~s & 0xFFFF
    header = header[:10] + struct.pack("!H", s) + header[12:]
    return header


def build_udp(src_port, dst_port, payload):
    """Build a UDP header + payload (no checksum for simplicity)."""
    length = 8 + len(payload)
    header = struct.pack("!HHH", src_port, dst_port, length) + b"\x00\x00"
    return header + payload


def build_dns_response(query_dns, answer_ip):
    """Build a DNS A record response."""
    header = bytearray(query_dns[:12])
    header[2] = 0x81  # QR=1, RD=1
    header[3] = 0x80  # RA=1
    header[6:8] = struct.pack("!H", 1)  # ANCOUNT=1

    # Find end of question
    off = 12
    while off < len(query_dns) and query_dns[off] != 0:
        off += query_dns[off] + 1
    off += 5  # null + QTYPE + QCLASS

    question = query_dns[12:off]
    answer = b"\xc0\x0c"  # pointer to name
    answer += struct.pack("!HHI", 1, 1, 300)  # A, IN, TTL
    answer += struct.pack("!H", 4)
    answer += socket.inet_aton(answer_ip)

    return bytes(header) + question + answer


def forward_dns(query_dns):
    """Forward DNS query to upstream and return response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    try:
        sock.sendto(query_dns, (UPSTREAM_DNS, 53))
        resp, _ = sock.recvfrom(4096)
        return resp
    except socket.timeout:
        return None
    finally:
        sock.close()


def handle_packet(fd, raw_packet, spoof_rules, log_fh):
    """Process a TUN packet — handle DNS queries."""
    if len(raw_packet) < 28:  # min IP + UDP header
        return

    # Parse IP header
    version_ihl = raw_packet[0]
    ihl = (version_ihl & 0x0F) * 4
    protocol = raw_packet[9]
    src_ip = socket.inet_ntoa(raw_packet[12:16])
    dst_ip = socket.inet_ntoa(raw_packet[16:20])

    if protocol != 17:  # Not UDP
        return

    # Parse UDP
    udp_start = ihl
    src_port = struct.unpack("!H", raw_packet[udp_start:udp_start + 2])[0]
    dst_port = struct.unpack("!H", raw_packet[udp_start + 2:udp_start + 4])[0]

    if dst_port != 53:
        return

    # DNS payload
    dns_data = raw_packet[udp_start + 8:]
    if len(dns_data) < 12:
        return

    qname, qend = parse_dns_name(dns_data, 12)
    qtype = struct.unpack("!H", dns_data[qend:qend + 2])[0] if qend + 2 <= len(dns_data) else 0
    type_str = {1: "A", 28: "AAAA", 5: "CNAME", 12: "PTR", 33: "SRV", 16: "TXT"}.get(qtype, str(qtype))

    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_line = f"[{ts}] {src_ip} -> {type_str} {qname}"

    # Check spoof rules
    dns_resp = None
    for domain, spoof_ip in spoof_rules.items():
        if qname == domain or qname.endswith("." + domain):
            dns_resp = build_dns_response(dns_data, spoof_ip)
            log_line += f" [SPOOFED -> {spoof_ip}]"
            break

    if dns_resp is None:
        dns_resp = forward_dns(dns_data)
        if dns_resp is None:
            log_line += " [TIMEOUT]"
            print(log_line)
            log_fh.write(log_line + "\n")
            log_fh.flush()
            return
        # Try to parse answer IP
        ancount = struct.unpack("!H", dns_resp[6:8])[0]
        if ancount > 0 and qtype == 1:
            off = qend + 4
            for _ in range(min(ancount, 5)):
                if off + 12 > len(dns_resp):
                    break
                if (dns_resp[off] & 0xC0) == 0xC0:
                    off += 2
                else:
                    while off < len(dns_resp) and dns_resp[off] != 0:
                        off += dns_resp[off] + 1
                    off += 1
                if off + 10 > len(dns_resp):
                    break
                rtype, _, _, rdlen = struct.unpack("!HHIH", dns_resp[off:off + 10])
                off += 10
                if rtype == 1 and rdlen == 4 and off + 4 <= len(dns_resp):
                    log_line += f" -> {socket.inet_ntoa(dns_resp[off:off + 4])}"
                    break
                off += rdlen

    print(log_line)
    log_fh.write(log_line + "\n")
    log_fh.flush()

    # Build response packet back through TUN
    udp_resp = build_udp(53, src_port, dns_resp)
    ip_resp = build_ip_header(dst_ip, src_ip, len(udp_resp))
    os.write(fd, ip_resp + udp_resp)


def main():
    parser = argparse.ArgumentParser(description="DNS interceptor via TUN")
    parser.add_argument("--spoof", action="append", metavar="DOMAIN=IP",
                        help="Spoof domain to IP")
    args = parser.parse_args()

    spoof_rules = {}
    if args.spoof:
        for rule in args.spoof:
            domain, ip = rule.split("=", 1)
            spoof_rules[domain] = ip

    fd, tun_name = create_tun()
    log_fh = open(LOG_FILE, "a")

    print(f"[*] Logging to {LOG_FILE}")
    print(f"[*] Upstream DNS: {UPSTREAM_DNS}")
    if spoof_rules:
        print(f"[*] Spoof rules:")
        for d, ip in spoof_rules.items():
            print(f"    {d} -> {ip}")
    print(f"\n[*] Now set the TV's DNS to {TUN_IP}")
    print(f"[*] Waiting for DNS queries...\n")

    try:
        while True:
            packet = os.read(fd, 4096)
            if packet:
                handle_packet(fd, packet, spoof_rules, log_fh)
    except KeyboardInterrupt:
        print("\n[*] Shutting down")
    finally:
        os.close(fd)
        os.system(f"ip link del {tun_name} 2>/dev/null")
        log_fh.close()


if __name__ == "__main__":
    main()
