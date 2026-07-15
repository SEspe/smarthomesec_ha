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

# Engine.IO heartbeat.
#
# Serveren venter at KLIENTEN sender PING ("2"); den svarer med PONG ("3").
# Dette er EIO v3-semantikk selv om URL-en sier EIO=4 – verifisert mot
# smartalarm.alarm24.no: uten heartbeat lukker serveren forbindelsen etter
# nøyaktig pingInterval + pingTimeout (25s + 5s = 30s), hver gang.
#
# Fallback hvis handshake ikke oppgir pingInterval.
DEFAULT_PING_INTERVAL = 25.0
# Send i god tid før serverens frist – 80 % av intervallet.
PING_MARGIN = 0.8


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
        if self._hb_stop is not None:
            self._hb_stop.set()
            self._hb_stop = None

    def _handle_handshake(self, ws, content: str) -> None:
        """Les pingInterval fra Engine.IO-handshake og start heartbeat."""
        interval = DEFAULT_PING_INTERVAL
        try:
            ping_ms = json.loads(content).get("pingInterval")
            if ping_ms:
                interval = ping_ms / 1000.0
        except Exception as ex:
            LOG.debug("Could not parse handshake (%s) – using default", ex)

        interval *= PING_MARGIN
        LOG.debug("Engine.IO handshake – sending PING every %.1fs", interval)
        self._start_heartbeat(ws, interval)

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
            # Serveren pinger oss (ikke observert mot alarm24, men billig å
            # støtte): PING skal alltid besvares med PONG.
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
