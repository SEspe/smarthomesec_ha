# -*- coding: utf-8 -*-

import json
import logging
import re
import threading
import ssl
import certifi
import time

import websocket

from custom_components.smarthomesec.const import API_BASEHOST

LOG = logging.getLogger(__name__)

# Demp støy fra websocket-biblioteket
logging.getLogger("websocket").setLevel(logging.CRITICAL)

# Engine.IO heartbeat – to serverdialekter med motsatt forventning.
#
# portal.vestasecurity.eu (Vesta, tenant-en den nye appen bruker) er en streng
# Engine.IO v4-server: SERVEREN sender PING ("2") hvert pingInterval, og
# klienten må svare PONG ("3"). Målt med tools/ws_probe: server-PING på
# 25.0/50.1/75.1s, linja lever i det uendelige, klienten sender ingenting. En
# klient-PING her er et protokollbrudd og serveren dropper socketen ~40ms etter
# (dette var 20s-reconnect-loopen etter 0.1.6).
#
# smartalarm.alarm24.no (gammel tenant) er motsatt: den sender aldri "2" og
# venter at KLIENTEN pinger – v3-stil – og lukker etter pingInterval+pingTimeout
# (25s+5s) hvis klienten er stille.
#
# Strategi (host-uavhengig): ved handshake pinger vi IKKE. Vi venter på å se om
# serveren pinger oss først. Gjør den det (v4/Vesta) svarer vi bare PONG. Gjør
# den det ikke innen en v3-server ville droppet oss, faller vi tilbake til
# klient-drevet PING (v3/alarm24). _on_message svarer PONG på server-PING uansett.
#
# Fallback hvis handshake ikke oppgir tidene.
DEFAULT_PING_INTERVAL = 25.0
DEFAULT_PING_TIMEOUT = 5.0
# Klient-PING sendes på 80 % av intervallet (kun i v3-fallbacken).
PING_MARGIN = 0.8
# Hvor lenge etter forventet server-PING vi venter før vi konkluderer med at det
# er en v3-server og pinger selv – må ligge mellom server-PING (pingInterval) og
# en v3-servers lukking (pingInterval + pingTimeout).
SERVER_PING_GRACE = 2.0


class WSClient(threading.Thread):
    """WebSocket client for SmartHomeSec (Socket.IO EIO=4)."""

    global_wsc = None
    global_stop = False

    def __init__(self, client, token):
        LOG.debug("WSClient initializing...")

        self.client = client
        self.token = token

        self.wsc = None
        self.stop = False
        # Siste endring
        self.last_activity = time.time()
        self.connected_at = None

        # Track siste event og connect-tid for watchdog
        self._last_connect = time.time()
        self._last_event = time.time()

        # Heartbeat – settes opp på nytt for hver tilkobling.
        self._hb_stop: threading.Event | None = None
        # Fallback-timer + flagg for v3/v4-avgjørelsen (se toppen av fila).
        self._hb_fallback: threading.Timer | None = None
        self._server_drives_hb = False

        super().__init__(daemon=True)

    # ----------------------------------------------------------------------
    # HEARTBEAT
    # ----------------------------------------------------------------------

    def _start_heartbeat(self, ws, interval: float) -> None:
        """Send Engine.IO PING ("2") hvert `interval` sekund til denne ws-en."""
        self._stop_heartbeat()

        stop = threading.Event()
        self._hb_stop = stop

        def _beat():
            while not stop.wait(interval):
                try:
                    ws.send("2")
                    LOG.debug("Sent Engine.IO PING (2)")
                except Exception as ex:
                    # Forbindelsen er borte – run_forever håndterer reconnect.
                    LOG.debug("Heartbeat stopped: %s", ex)
                    return

        threading.Thread(target=_beat, daemon=True, name="shs-ws-heartbeat").start()

    def _stop_heartbeat(self) -> None:
        if self._hb_fallback is not None:
            self._hb_fallback.cancel()
            self._hb_fallback = None
        if self._hb_stop is not None:
            self._hb_stop.set()
            self._hb_stop = None

    def _handle_handshake(self, ws, content: str) -> None:
        """Avgjør heartbeat-stil ut fra Engine.IO-handshaken.

        Vi pinger ikke ennå. Pinger serveren oss først (v4) er vi stille og
        svarer bare PONG; ellers faller vi litt senere tilbake til klient-PING
        (v3). Se dialekt-forklaringen øverst i fila.
        """
        interval = DEFAULT_PING_INTERVAL
        ping_timeout = DEFAULT_PING_TIMEOUT
        try:
            hs = json.loads(content)
            if hs.get("pingInterval"):
                interval = hs["pingInterval"] / 1000.0
            if hs.get("pingTimeout"):
                ping_timeout = hs["pingTimeout"] / 1000.0
        except Exception as ex:
            LOG.debug("Could not parse handshake (%s) – using defaults", ex)

        self._stop_heartbeat()
        self._server_drives_hb = False
        beat = interval * PING_MARGIN

        # Fyr etter at serverens egen PING ville kommet (pingInterval), men før
        # en v3-server ville lukket oss (pingInterval + pingTimeout).
        grace = min(SERVER_PING_GRACE, max(ping_timeout - 1.0, 0.5))
        fallback_delay = interval + grace

        LOG.debug(
            "Handshake pingInterval=%.1fs pingTimeout=%.1fs – waiting %.1fs for a "
            "server PING before falling back to client PING",
            interval,
            ping_timeout,
            fallback_delay,
        )
        timer = threading.Timer(fallback_delay, self._maybe_start_client_ping, args=(ws, beat))
        timer.daemon = True
        self._hb_fallback = timer
        timer.start()

    def _maybe_start_client_ping(self, ws, beat: float) -> None:
        """Fallback: ingen server-PING kom, så vi driver heartbeaten selv (v3)."""
        if self.stop or self._server_drives_hb:
            if self._server_drives_hb:
                LOG.debug("Server drives the heartbeat (Engine.IO v4) – no client PING")
            return
        LOG.debug("No server PING seen – falling back to client-driven PING (v3)")
        try:
            # Første PING nå – den periodiske beateren sender først etter `beat`,
            # som ellers ville vært for sent mot v3-serverens frist.
            ws.send("2")
            LOG.debug("Sent Engine.IO PING (2)")
        except Exception as ex:
            LOG.debug("Fallback first PING failed: %s", ex)
            return
        self._start_heartbeat(ws, beat)

    # ----------------------------------------------------------------------
    # PUBLIC API
    # ----------------------------------------------------------------------

    def start(self):
        LOG.debug("WSClient thread starting")
        super().start()

    def stop_client(self):
        LOG.debug("WSClient stopping...")

        self.stop = True
        self.global_stop = True
        self._stop_heartbeat()

        if self.wsc is not None:
            try:
                self.wsc.close()
            except Exception:
                pass

        self.global_wsc = None

    # ----------------------------------------------------------------------
    # INTERNAL
    # ----------------------------------------------------------------------

    def run(self):
        """WebSocket loop with adaptive reconnect (single owner)."""

        base = API_BASEHOST.rstrip("/")
        wsc_url = (
            f"wss://{base}/ws/socket.io/"
            f"?token={self.token}&transport=websocket&EIO=4"
        )

        LOG.debug("WebSocket URL: %r", wsc_url)

        # Close previous global WS if any
        if self.global_wsc is not None:
            try:
                self.global_wsc.close()
            except Exception:
                pass

        reconnect_delay = 2
        forced_login = False

        while not self.stop:

            LOG.debug("WebSocket: run_forever() starting")

            self.wsc = websocket.WebSocketApp(
                wsc_url,
                on_message=self._on_message,
                on_error=self._on_error,
                on_ping=self._on_ping,
                on_pong=self._on_pong,
                on_open=self._on_open,
            )

            self.global_wsc = self.wsc

            # ✅ Run connection (blocking)
            self.wsc.run_forever(
                ping_interval=20,
                ping_timeout=10,
                sslopt={"ca_certs": certifi.where()},
            )

            LOG.debug("WebSocket: run_forever() exited")

            # Heartbeat hører til forbindelsen som nettopp døde.
            self._stop_heartbeat()

            if self.stop:
                break

            now = time.time()
            lived = now - getattr(self, "_last_connect", now)
            LOG.debug("WebSocket lived %s", lived)

            # --------------------------------------------------
            # 🔥 Watchdog (beholdt)
            # --------------------------------------------------
            if hasattr(self, "_last_event"):
                silent_for = time.time() - self._last_event
                since_connect = time.time() - getattr(self, "_last_connect", self._last_event)

                if silent_for > 21600 and since_connect > 300:
                    LOG.warning(
                        "WS silent too long (%.0fs, since connect %.0fs) → forcing full login()",
                        silent_for,
                        since_connect,
                    )
                    forced_login = True
                    self.client.callback("ForceLogin", None)
                    break

            # --------------------------------------------------
            # 🔥 Adaptive reconnect (behold)
            # --------------------------------------------------
            if lived > 10:
                reconnect_delay = 2
            else:
                reconnect_delay = min(reconnect_delay * 2, 30)

            LOG.debug("WebSocket reconnect in %s seconds...", reconnect_delay)

            # ✅ VIKTIG: pause før reconnect
            for _ in range(reconnect_delay):
                if self.stop:
                    break
                time.sleep(1)

        LOG.debug("WebSocket stopped")

        # ✅ Kun signal – IKKE start WS her
        if not forced_login:
            LOG.debug("WS stopped normally (no callback restart)")

    # ----------------------------------------------------------------------
    # EVENT HANDLERS
    # ----------------------------------------------------------------------

    def _on_open(self, ws):
        # Ny connect → nullstill "stillhet"
        self._last_connect = time.time()
        self._last_event = self._last_connect

        LOG.debug("WebSocket connected")
        self.connected_at = self._last_connect
        self.last_activity = self.connected_at

        # Socket.IO CONNECT frame
        try:
            ws.send("40")
            LOG.debug("Sent Socket.IO CONNECT (40)")
        except Exception as e:
            LOG.error("Failed to send CONNECT: %s", e)

        # Ingen AUTH – SmartHomeSec bruker token i URL
        self.client.callback("WebSocketConnect", None)

    def _on_error(self, ws, error):
        # opcode=8 er NORMAL disconnect fra SmartHomeSec
        if "opcode=8" in str(error):
            LOG.debug("WebSocket closed normally: %s", error)
            return

        LOG.warning("WebSocket error: %s", error)
        self.client.callback("WebSocketError", error)

    def _on_ping(self, ws, message):
        LOG.debug("WebSocket ping received")

    def _on_pong(self, ws, message):
        LOG.debug("WebSocket pong received")

    def _on_message(self, ws, message):
        """
        SmartHomeSec bruker Socket.IO framing:
        - "42" prefix = event
        - "3" = ping/pong
        - "0" = connect
        """
        self.last_activity = time.time()
        match = re.search(r"^(\d+)(.*)$", message)
        if not match:
            LOG.debug("WS: unparsed message: %s", message)
            return

        code = match.group(1)
        content = match.group(2)

        if code == "0":
            # Engine.IO OPEN – serveren oppgir sine pingInterval/pingTimeout.
            self._handle_handshake(ws, content)

        elif code == "2":
            # Server-PING (Engine.IO v4, f.eks. Vesta): merk at serveren driver
            # heartbeaten – da skal vi aldri klient-pinge denne forbindelsen –
            # og svar PONG.
            self._server_drives_hb = True
            try:
                ws.send("3")
                LOG.debug("Answered server PING with PONG (3)")
            except Exception as ex:
                LOG.debug("Failed to send PONG: %s", ex)

        if code == "42":
            # 42 = faktisk event (dør, PIR, mode change osv.)
            # Brukes av watchdog til å vite at linja lever.
            self._last_event = time.time()

        LOG.debug("WS received: code=%s content=%s", code, content)

        # Send videre til coordinator
        self.client.callback(code, content)
