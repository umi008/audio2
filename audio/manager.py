import pyaudio
from .constants import FORMAT, CHANNELS, RATE, CHUNK

class AudioManager:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.stream = None

    def open_stream(self, input=True, output=False):
        self.stream = self.p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=input,
            output=output,
            frames_per_buffer=CHUNK
        )
        return self.stream

    def close_stream(self):
        if self.stream is not None:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

    def terminate(self):
        self.close_stream()
        self.p.terminate()
