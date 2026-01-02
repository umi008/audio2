class ConversationState:
    def __init__(self):
        self.history = []
        self.context = {}

    def add_message(self, role: str, content: str):
        self.history.append({"role": role, "content": content})

    def get_history(self):
        return self.history

    def set_context(self, key: str, value):
        self.context[key] = value

    def get_context(self, key: str, default=None):
        return self.context.get(key, default)
