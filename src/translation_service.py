import requests


def remote_translate(text: str, target_lang: str, endpoint: str, timeout_seconds: int) -> str:
    params = {"q": text, "langpair": f"de|{target_lang}"}
    try:
        response = requests.get(endpoint, params=params, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        translated = payload.get("responseData", {}).get("translatedText", "")
        return str(translated).strip()
    except (requests.RequestException, ValueError):
        return ""