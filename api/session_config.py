import requests

def create_session_config(api_key: str, base_url: str = None) -> requests.Session:
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {api_key}"})
    if base_url:
        session.base_url = base_url
    return session
