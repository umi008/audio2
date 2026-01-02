import websocket
import threading
import json

class OpenAIWebSocketClient:
    def __init__(self, url, on_message, on_error=None, on_close=None, headers=None):
        self.url = url
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.headers = headers
        self.ws = None
        self.thread = None

    def connect(self):
        self.ws = websocket.WebSocketApp(
            self.url,
            header=self.headers or [],
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        self.thread = threading.Thread(target=self.ws.run_forever)
        self.thread.daemon = True
        self.thread.start()

    def send(self, data):
        if isinstance(data, dict):
            data = json.dumps(data)
        self.ws.send(data)

    def close(self):
        if self.ws:
            self.ws.close()
        if self.thread:
            self.thread.join()
