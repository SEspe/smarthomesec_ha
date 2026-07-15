"""Find the LAN device sending SSDP packets with duplicate SERVER headers.

HA's async_upnp_client hands SSDP packets to aiohttp's strict header parser,
which raises BadHttpMessage("Duplicate 'SERVER' header found") and spams the
log. The exception carries no source address, so we catch the packets ourselves.

Phase 1 (--msearch): active. Send M-SEARCH from every local interface and
inspect the unicast replies. Seconds, not minutes.
Phase 2 (--listen N): passive. Join the multicast group and watch for the
NOTIFY ssdp:alive bursts (observed every ~10 min).

Read-only: sends one standard discovery request, never writes to any device.

Runs anywhere on HA's LAN with stdlib Python 3.7+. To run inside HA itself,
drop it in /config and add to configuration.yaml:

    shell_command:
      ssdp_probe: "python3 /config/ssdp_probe.py --msearch --out /config/ssdp_report.txt"

then call shell_command.ssdp_probe from Developer Tools > Actions with
"return response variable" ticked. shell_command kills the process at 60s, so
for the passive mode background it instead:

    shell_command:
      ssdp_probe_listen: "nohup python3 /config/ssdp_probe.py --listen 700 --out /config/ssdp_report.txt >/dev/null 2>&1 &"

and read /config/ssdp_report.txt afterwards (File Editor add-on, or a
command_line sensor). --out is written progressively, so a background run can
be inspected while it is still going.
"""

import argparse
import socket
import struct
import subprocess
import sys
import time
from collections import Counter

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

_OUT = None


def emit(line=""):
    """print(), but also to --out, flushed so a background run stays readable."""
    print(line, flush=True)
    if _OUT:
        _OUT.write(line + "\n")
        _OUT.flush()

M_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: ssdp:all\r\n"
    "\r\n"
).encode()


def local_ips():
    ips = set()
    try:
        _, _, addrs = socket.gethostbyname_ex(socket.gethostname())
        ips.update(a for a in addrs if not a.startswith("127."))
    except OSError:
        pass
    # Fallback: the IP that would be used to reach the default gateway.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips)


def parse_headers(data):
    """Return (start_line, [(name_lower, value)]) without any strict validation."""
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return "", []
    lines = text.split("\r\n")
    if len(lines) == 1:
        lines = text.split("\n")
    start_line = lines[0].strip() if lines else ""
    headers = []
    for line in lines[1:]:
        if not line.strip():
            continue
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        headers.append((name.strip().lower(), value.strip()))
    return start_line, headers


def duplicates(headers):
    counts = Counter(name for name, _ in headers)
    return {name: n for name, n in counts.items() if n > 1}


def mac_for(ip):
    """Best-effort MAC lookup. Windows arp uses dashes, Linux colons, and the
    HA container may have no arp binary at all — hence the /proc fallback.
    """
    try:
        out = subprocess.run(
            ["arp", "-a", ip], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.splitlines():
            if ip in line:
                for token in line.split():
                    if len(token) == 17 and (
                        token.count("-") == 5 or token.count(":") == 5
                    ):
                        return token
    except Exception:
        pass
    try:
        with open("/proc/net/arp", encoding="utf-8") as fh:
            for line in fh.readlines()[1:]:
                fields = line.split()
                if len(fields) >= 4 and fields[0] == ip and fields[3] != "00:00:00:00:00:00":
                    return fields[3]
    except Exception:
        pass
    return "?"


def report(seen):
    emit("\n" + "=" * 72)
    if not seen:
        emit("No SSDP responders seen at all.")
        emit("If HA is on a different subnet/VLAN than this PC, the probe cannot")
        emit("see the same multicast traffic — it must run next to HA.")
        return
    bad = {ip: info for ip, info in seen.items() if info["dupes"]}
    emit(f"SSDP responders seen: {len(seen)}   with duplicate headers: {len(bad)}")
    emit("=" * 72)
    for ip, info in sorted(seen.items()):
        flag = "  <-- DUPLICATE HEADERS" if info["dupes"] else ""
        emit(f"\n{ip}   mac={mac_for(ip)}{flag}")
        if info["dupes"]:
            for name, n in info["dupes"].items():
                emit(f"    duplicate '{name.upper()}' x{n}")
        for key in ("server", "usn", "location", "nt", "st"):
            for name, value in info["headers"]:
                if name == key:
                    emit(f"    {name.upper()}: {value[:100]}")
    if bad:
        emit("\n" + "=" * 72)
        emit("CULPRIT(S): " + ", ".join(sorted(bad)))
        emit("=" * 72)


def msearch(seen, wait=6):
    for src in local_ips():
        emit(f"[msearch] sending from {src}")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(src))
            s.bind((src, 0))
            s.sendto(M_SEARCH, (SSDP_ADDR, SSDP_PORT))
            s.settimeout(1.0)
            deadline = time.time() + wait
            while time.time() < deadline:
                try:
                    data, addr = s.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    break
                record(seen, data, addr[0], "reply")
            s.close()
        except OSError as ex:
            emit(f"[msearch] {src}: {ex}")


def record(seen, data, ip, kind):
    start_line, headers = parse_headers(data)
    dupes = duplicates(headers)
    prev = seen.get(ip)
    # Keep the packet that shows the problem, if any.
    if prev is None or (dupes and not prev["dupes"]):
        seen[ip] = {"headers": headers, "dupes": dupes, "start": start_line}
    if dupes:
        emit(
            f"  !! {ip} {kind}: {start_line}  duplicates="
            + ",".join(f"{k.upper()}x{v}" for k, v in dupes.items())
        )


def listen(seen, seconds):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # HA already holds UDP 1900. On Linux SO_REUSEPORT lets us listen alongside
    # it instead of fighting over the bind; it does not exist on Windows.
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    try:
        s.bind(("", SSDP_PORT))
    except OSError as ex:
        emit(f"[listen] cannot bind UDP {SSDP_PORT}: {ex}")
        emit("[listen] something else holds the port without SO_REUSEPORT.")
        emit("[listen] --msearch does not need this port; try that instead.")
        return
    for src in local_ips():
        try:
            s.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_ADD_MEMBERSHIP,
                struct.pack("4s4s", socket.inet_aton(SSDP_ADDR), socket.inet_aton(src)),
            )
        except OSError:
            pass
    s.settimeout(2.0)
    emit(f"[listen] watching multicast for {seconds}s (alive bursts are ~10min apart)")
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            data, addr = s.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break
        record(seen, data, addr[0], "notify")
    s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=0, metavar="SECONDS")
    ap.add_argument("--msearch", action="store_true")
    ap.add_argument(
        "--out", metavar="PATH", help="also write the report here, as it happens"
    )
    args = ap.parse_args()
    if not args.msearch and not args.listen:
        args.msearch = True

    global _OUT
    if args.out:
        try:
            _OUT = open(args.out, "w", encoding="utf-8")
        except OSError as ex:
            print(f"cannot write {args.out}: {ex}", flush=True)

    try:
        emit(f"probe started {time.strftime('%Y-%m-%d %H:%M:%S')}")
        emit(f"local IPs: {', '.join(local_ips()) or 'none found'}")
        seen = {}
        if args.msearch:
            msearch(seen)
        if args.listen:
            listen(seen, args.listen)
        report(seen)
        emit(f"\nprobe finished {time.strftime('%Y-%m-%d %H:%M:%S')}")
    finally:
        if _OUT:
            _OUT.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
