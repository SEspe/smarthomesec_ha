# -*- coding: utf-8 -*-

#################################################################################################

import json
import logging
import re
import threading
import ssl
import certifi

import websocket

from custom_components.smarthomesec.const import API_BASEHOST

##################################################################################################

LOG = logging.getLogger(__name__)

##################################################################################################


class WSClient(threading.Thread):
    global_wsc = None
    global_stop = False


    def run_once(self, duration=5):
        base = API_BASEHOST.rstrip("/")
        wsc_url = f"wss://{base}/ws/socket.io/?token={self.token}&transport=websocket&EIO=4"

        LOG.debug("Websocket (on-demand): %s", wsc_url)

        self.wsc = websocket.WebSocketApp(
            wsc_url,
            on_message=lambda ws, message: self.on_message(ws, message),
            on_error=lambda ws, error: self.on_error(ws, error),
            on_open=lambda ws: self.on_open(ws),
        )

        import threading, time

        def run_ws():
            self.wsc.run_forever(
                ping_interval=20,
                ping_timeout=10,
                sslopt={"ca_certs": certifi.where()}
            )

        t = threading.Thread(target=run_ws)
        t.start()

        # ✅ la den leve litt
        time.sleep(duration)

        # ✅ lukk pent
        LOG.debug("Closing websocket (on-demand)")
        self.wsc.close()

        # ✅ viktig: reset slik at ny kan opprettes senere
        self.client.wsc = None



    def __init__(self, client, token):
        LOG.debug("WSClient initializing...")

        self.client = client
        self.token = token

        self.keepalive = None
        self.wsc = None
        self.stop = False

        threading.Thread.__init__(self)

    def send(self, code, data=""):
        if self.wsc is None:
            raise ValueError("The websocket client is not started.")

        self.wsc.send(code + data)
# Test fix for feil i loggen
#
#  Legger til &EIo=4
#   ALt2:  Fjerne dobbel slash;  
#           base = API_BASEHOST.rstrip("/")
#           wsc_url = f"wss://{base}/socket.io/?token={self.token}&transport=websocket&EIO=4"
#   Alt3
#       Fjerne /ws/,  uten dette
#
#
#
    def run(self):
        base = API_BASEHOST.rstrip("/")
        wsc_url = f"wss://{base}/ws/socket.io/?token={self.token}&transport=websocket&EIO=4"

        LOG.debug("Websocket url: %s", wsc_url)

        self.wsc = websocket.WebSocketApp(
            wsc_url,
            on_message=lambda ws, message: self.on_message(ws, message),
            on_error=lambda ws, error: self.on_error(ws, error),
            on_ping=lambda ws, message: self.on_ping(ws, message),
            on_pong=lambda ws, message: self.on_pong(ws, message),
        )
        self.wsc.on_open = lambda ws: self.on_open(ws)

        if self.global_wsc is not None:
            self.global_wsc.close()
        self.global_wsc = self.wsc

        while not self.stop and not self.global_stop:
            LOG.debug("Websocket: run_forever() start")
            self.wsc.run_forever(
                ping_interval=20,
                ping_timeout=10,
                sslopt={"ca_certs": certifi.where()},
            )
            LOG.debug("Websocket: run_forever() exited")

            if self.stop or self.global_stop:
                break

            # liten backoff før reconnect
            import time
            time.sleep(5)

        LOG.debug("---<[ websocket stopped ]")
        self.client.callback("WebSocketDisconnect", None)


##        while not self.stop and not self.global_stop:
# Ping interval 10  øket til 20 
# La til ping_timeout=10,  manglet opprinnelig
##            self.wsc.run_forever(ping_interval=20,ping_timeout=10, sslopt={"ca_certs": certifi.where()})
##
#            if not self.stop:
#                break
#  Endret kode    
##            if not self.stop:
##                import time
##                time.sleep(5)
##       LOG.debug("---<[ websocket ]")
##        self.client.callback("WebSocketDisconnect", None)

    def on_error(self, ws, error):
        LOG.error(error)
        self.client.callback("WebSocketError", error)

    def on_open(self, ws):
        LOG.debug("--->[ websocket ]")
        self.client.callback("WebSocketConnect", None)

    def on_ping(self, ws, message):
        LOG.debug("--->[ websocket ] Got a ping! A pong reply has already been automatically sent.")

    def on_pong(self, ws, message):
        LOG.debug("--->[ websocket ] Got a pong!")
#        LOG.debug("--->[ websocket ] Got a pong! Sending keepalive")
## Tatt vekk SE 14.05.2026        self.send("2")

    def on_message(self, ws, message):
        re_split = re.search("^(\\d+)(.*)$", message)
        code = re_split.group(1)
        content = re_split.group(2)

        LOG.debug("Received: code: %s; message: %s", code, content)
        self.client.callback(code, content)

        return

        message = json.loads(message)

        data = message.get("Data", {})

        if message["MessageType"] == "ForceKeepAlive":
            self.send("KeepAlive")
            if self.keepalive is not None:
                self.keepalive.stop()
            self.keepalive = KeepAlive(data, self)
            self.keepalive.start()
            LOG.debug("ForceKeepAlive received from server.")
            return
        elif message["MessageType"] == "KeepAlive":
            LOG.debug("KeepAlive received from server.")
            return

        if data is None:
            data = {}
        elif not isinstance(data, dict):
            data = {"value": data}

        if not self.client.config.data["app.default"]:
            data["ServerId"] = self.client.auth.server_id

        self.client.callback(message["MessageType"], data)

    def stop_client(self):
        self.stop = True

        if self.keepalive is not None:
            self.keepalive.stop()

        if self.wsc is not None:
            self.wsc.close()

        self.global_stop = True
        self.global_wsc = None
