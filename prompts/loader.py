import yaml
from pathlib import Path

def load_prompt(prompt_path: str) -> dict:
    path = Path(prompt_path)
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)
