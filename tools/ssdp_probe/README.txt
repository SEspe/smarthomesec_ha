================================================================================
ssdp_probe.py - find the LAN device that spams the HA log
================================================================================

THE PROBLEM
-----------
The HA log fills up with this, in pairs, roughly every 10 minutes:

    ERROR (MainThread) [homeassistant] Error doing job:
    Exception in callback _SelectorDatagramTransport._read_ready()
    ...
    File ".../async_upnp_client/ssdp.py", line 302, in datagram_received
    ...
    aiohttp.http_exceptions.BadHttpMessage: 400, message:
      Duplicate 'SERVER' header found.

This has nothing to do with the smarthomesec integration.

HA's SSDP/UPnP discovery listens on UDP multicast 239.255.255.250:1900. Some
device on the LAN broadcasts a malformed SSDP packet containing two "SERVER:"
headers. aiohttp's strict parser rejects duplicate headers outright, the
exception escapes datagram_received, and HA logs it as an unhandled callback
error. It is cosmetic - discovery of other devices still works - but noisy.

The pairs-every-10-minutes rhythm is a classic SSDP "NOTIFY ssdp:alive"
re-advertisement cycle. Two errors per burst = two of that device's
announcements carry the bad header.

HA cannot tell you WHICH device: the exception fires before anything logs the
source address, so the IP is never recorded. That is what this probe is for.

Requirements: Python 3.7+, standard library only. Nothing to install.

IMPORTANT: SSDP is link-local multicast. It does not cross subnets, VLANs or
VPNs. The probe MUST run on the same network segment as HA. Running it from a
remote machine will find nothing, no matter how healthy it looks.


--------------------------------------------------------------------------------
OPTION 1 - FROM INSIDE HOME ASSISTANT (no SSH, no docker)
--------------------------------------------------------------------------------
HA's shell_command runs inside the HA container, so it sees exactly the same
multicast traffic HA sees. This is the most reliable option: it is by
definition on the right network.

1. Copy ssdp_probe.py into /config - the same folder as configuration.yaml.
   Use the File Editor add-on, the VS Code add-on, or a Samba share.

2. Add to configuration.yaml:

     shell_command:
       ssdp_probe: "python3 /config/ssdp_probe.py --msearch --out /config/ssdp_report.txt"
       ssdp_probe_listen: "nohup python3 /config/ssdp_probe.py --listen 700 --out /config/ssdp_report.txt >/dev/null 2>&1 &"

3. Restart Home Assistant. (A YAML reload is enough on some versions, but
   shell_command often needs a full restart.)

4. Developer Tools -> Actions -> shell_command.ssdp_probe
   -> tick "return response variable" -> Perform action.

   The report appears in the UI in ~10 seconds, and is also written to
   /config/ssdp_report.txt.

5. If that finds nothing (see "IF M-SEARCH FINDS NOTHING" below), run
   shell_command.ssdp_probe_listen instead, wait ~12 minutes, then read
   /config/ssdp_report.txt with the File Editor add-on.

WHY THE nohup ... & ON THE SECOND COMMAND:
shell_command hard-kills any process at 60 seconds. The passive listen needs
~12 minutes, so it has to be backgrounded. The action returns immediately and
the process keeps running. --out is flushed on every line, so the report file
can be read while the probe is still working.


--------------------------------------------------------------------------------
OPTION 2 - FROM ANY MACHINE ON HA's LAN
--------------------------------------------------------------------------------
A laptop, desktop, NAS or Raspberry Pi - anything with Python on the same
network segment as HA. Simpler, but you must be on the right network: a laptop
at home is fine, the same laptop over VPN is not.

    python3 ssdp_probe.py --msearch              # Linux / macOS
    py ssdp_probe.py --msearch                   # Windows

Windows may prompt to allow the UDP bind through the firewall - allow it, at
least on the private network.


--------------------------------------------------------------------------------
THE TWO MODES
--------------------------------------------------------------------------------
--msearch       ACTIVE, ~6 seconds. Sends one standard M-SEARCH discovery
                request and inspects the unicast replies. Try this first.

--listen 700    PASSIVE, ~12 minutes. Joins the multicast group and watches for
                the NOTIFY ssdp:alive bursts. 700s covers one full 10-minute
                cycle with margin.

--out PATH      Also write the report to PATH, flushed as it happens. Required
                for backgrounded runs.

They can be combined:

    python3 ssdp_probe.py --msearch --listen 700 --out ssdp_report.txt

The probe is read-only. It sends one standard discovery request and listens.
It never writes to any device.

IF M-SEARCH FINDS NOTHING:
A clean --msearch is NOT an all-clear. M-SEARCH only catches devices that
answer queries, but the log errors come from unsolicited NOTIFY broadcasts.
It is probably the same device doing both, but not guaranteed - so if
--msearch comes back with 0 duplicates, run --listen 700 before concluding
anything.


--------------------------------------------------------------------------------
READING THE OUTPUT
--------------------------------------------------------------------------------
Offenders are printed live, prefixed with "!!", and summarised at the end:

    ========================================================================
    SSDP responders seen: 7   with duplicate headers: 1
    ========================================================================

    192.168.1.44   mac=00-22-61-ad-3e-ba  <-- DUPLICATE HEADERS
        duplicate 'SERVER' x2
        SERVER: POSIX, UPnP/1.0, SomeVendor SomeModel/1.0
        USN: uuid:3dcc7100-...::upnp:rootdevice
        LOCATION: http://192.168.1.44:80/dd.xml

    ========================================================================
    CULPRIT(S): 192.168.1.44
    ========================================================================

The SERVER string usually names the device outright. The MAC's first three
octets identify the vendor (look up the OUI online). LOCATION can be opened in
a browser for the full device description.

If mac= shows "?", the lookup failed - arp may not exist in the HA container,
and the /proc/net/arp fallback only sees recently contacted hosts. The IP is
what matters; find it in your router's DHCP client list.

If it reports "No SSDP responders seen at all", the probe is on the wrong
network segment. See the note at the top.


--------------------------------------------------------------------------------
ONCE YOU KNOW WHICH DEVICE
--------------------------------------------------------------------------------
- Update its firmware. A malformed UPnP header is a device-side bug and is
  often fixed in a later release.
- Or mute the noise in HA's configuration.yaml:

      logger:
        default: info
        logs:
          async_upnp_client.ssdp: critical

  This silences the symptom, not the cause, and may hide other genuine SSDP
  problems. Prefer identifying the device first.
- If the device has no legitimate need to be discovered by HA, disabling UPnP
  on it stops the broadcasts entirely.


--------------------------------------------------------------------------------
STATUS
--------------------------------------------------------------------------------
Written 2026-07-15. Verified end-to-end on Windows (Python 3.12): M-SEARCH,
passive listen, --out and the ARP lookup all work; it correctly identified a
UPnP device on the local network.

NOT yet run on HA's own network - the machine it was developed on is not on
that segment, which is the whole reason the probe exists. Option 1 above is
therefore written from the shell_command documentation rather than from a
live run. The MAC lookup inside the HA container and the shared bind on UDP
1900 (SO_REUSEPORT, since HA already holds that port) are both handled
defensively and report clearly if they fail, but neither has been exercised
there yet.
