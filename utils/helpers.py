def read_audio_blocking(stream, num_frames):
    data = b''
    while len(data) < num_frames:
        data += stream.read(num_frames - len(data))
    return data
