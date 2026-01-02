import logging
from pathlib import Path

class ConversationLogger:
    def __init__(self, log_path: str = "logs/conversation.log"):
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("conversation")
        self.logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_path, encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        fh.setFormatter(formatter)
        if not self.logger.hasHandlers():
            self.logger.addHandler(fh)
        self.fh = fh

    def log(self, message: str):
        self.logger.info(message)

    def close(self):
        self.fh.close()
        self.logger.removeHandler(self.fh)
