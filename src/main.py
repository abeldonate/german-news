import html
import os
import re
from io import BytesIO
from typing import Any

import requests
import yaml
from flask import Flask, Response, jsonify, render_template, request
from gtts import gTTS
from markupsafe import Markup

template_path = os.path.abspath("src/templates")
static_path = os.path.abspath("src/static")
config_path = os.path.abspath("config.yml")


def load_app_config(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            parsed = yaml.safe_load(fh) or {}
            if not isinstance(parsed, dict):
                raise ValueError("config.yml must be a YAML mapping")
            return parsed
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Failed to load {path}: {exc}") from exc


CONFIG = load_app_config(config_path)
APP_SETTINGS = CONFIG.get("app", {})
API_SETTINGS = CONFIG.get("api", {})
FEATURE_SETTINGS = CONFIG.get("features", {})

TAGESSCHAU_HOMEPAGE_API = str(API_SETTINGS.get("tagesschau_homepage_api"))
APP_TARGET_LANG = str(APP_SETTINGS.get("target_lang"))
TRANSLATE_ENDPOINT = str(API_SETTINGS.get("translate_endpoint"))
TTS_LANG = str(API_SETTINGS.get("tts_lang", "de"))
REQUEST_TIMEOUT_SECONDS = int(API_SETTINGS.get("request_timeout_seconds", 12))
REQUEST_USER_AGENT = str(API_SETTINGS.get("user_agent", "german-news-flask-app/1.0"))
APP_HOST = str(APP_SETTINGS.get("host", "0.0.0.0"))
APP_PORT = int(APP_SETTINGS.get("port", 5000))
MAX_ARTICLES = int(APP_SETTINGS.get("max_articles", 10))

app = Flask(
    __name__,
    template_folder=template_path,
    static_folder=static_path,
)


def load_word_file(path: str) -> set[str]:
    """Load a word-list text file; skip blank lines and comment lines starting with #."""
    words: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                word = line.strip()
                if word and not word.startswith("#"):
                    words.add(word.lower())
    except OSError:
        pass
    return words


def load_cefr_levels(level_files: dict[str, str]) -> dict[str, set[str]]:
    levels: dict[str, set[str]] = {}
    for level, rel_path in level_files.items():
        abs_path = os.path.join(os.path.abspath("."), rel_path)
        levels[str(level).lower()] = load_word_file(abs_path)
    return levels


CEFR_LEVELS = load_cefr_levels(FEATURE_SETTINGS.get("cefr_level_files", {}))
CONTENT_BLOCK_TYPES = set(FEATURE_SETTINGS.get("content_block_types", ["text", "headline"]))
_TAG_PATTERN = re.compile(r"<[^>]+>")


def fetch_json(url: str) -> dict[str, Any] | None:
    headers = {"User-Agent": REQUEST_USER_AGENT}
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return None


def maybe_article_node(node: dict[str, Any]) -> bool:
    if "title" not in node:
        return False
    return any(
        key in node
        for key in (
            "detailsweb",
            "details",
            "shareURL",
            "url",
            "teasertext",
            "firstSentence",
        )
    )


def collect_articles(obj: Any, bucket: list[dict[str, Any]]) -> None:
    if isinstance(obj, dict):
        if maybe_article_node(obj):
            bucket.append(obj)
        for value in obj.values():
            collect_articles(value, bucket)
    elif isinstance(obj, list):
        for item in obj:
            collect_articles(item, bucket)


def clean_article_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for article in candidates:
        key = (
            article.get("detailsweb")
            or article.get("shareURL")
            or article.get("url")
            or article.get("title")
        )
        if not key:
            continue
        unique[str(key)] = article
    return list(unique.values())


def strip_html_tags(value: str) -> str:
    return _TAG_PATTERN.sub("", value).strip()


def extract_text_from_content_blocks(content: list[Any]) -> str:
    paragraphs: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        if block_type not in CONTENT_BLOCK_TYPES:
            continue
        value = block.get("value", "")
        if not isinstance(value, str):
            continue
        text = strip_html_tags(value)
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def pick_article_text(article: dict[str, Any]) -> str:
    # Prefer the dedicated details JSON endpoint for full content
    details_url = article.get("details", "")
    if details_url and isinstance(details_url, str) and details_url.startswith("http"):
        details_data = fetch_json(details_url)
        if details_data:
            blocks = details_data.get("content", [])
            if isinstance(blocks, list):
                text = extract_text_from_content_blocks(blocks)
                if text:
                    return text

    # Fall back to content blocks already embedded in the homepage article node
    blocks = article.get("content", [])
    if isinstance(blocks, list):
        text = extract_text_from_content_blocks(blocks)
        if text:
            return text

    # Last resort: use the short teaser fields only
    teaser_parts = [
        article.get("firstSentence", ""),
        article.get("teasertext", ""),
    ]
    return "\n\n".join(p for p in teaser_parts if p)


def cefr_level_for_word(word: str) -> str | None:
    normalized = word.lower()
    for level, words in CEFR_LEVELS.items():
        if normalized in words:
            return level
    return None


def annotate_text_with_levels(text: str) -> Markup:
    token_pattern = re.compile(r"[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)*|\s+|[^\w\s]", re.UNICODE)
    parts: list[str] = []

    for token in token_pattern.findall(text):
        if token.isspace():
            parts.append(token)
        elif re.fullmatch(r"[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)*", token):
            level = cefr_level_for_word(token)
            classes = "word"
            if level:
                classes = f"word level-{level}"
            token_html = (
                f'<span class="{classes}" data-word="{html.escape(token)}">'
                f"{html.escape(token)}</span>"
            )
            parts.append(token_html)
        else:
            parts.append(html.escape(token))

    return Markup("".join(parts))


def build_articles_payload(max_count: int = 1) -> list[dict[str, Any]]:
    """Fetch and parse multiple articles from the API."""
    homepage_data = fetch_json(TAGESSCHAU_HOMEPAGE_API)
    if not homepage_data:
        return []

    candidates: list[dict[str, Any]] = []
    collect_articles(homepage_data, candidates)
    articles = clean_article_candidates(candidates)
    articles = articles[:max_count]

    if not articles:
        return []

    payloads: list[dict[str, Any]] = []
    for article in articles:
        title = str(article.get("title", "Ohne Titel"))
        url = str(article.get("detailsweb") or article.get("shareURL") or article.get("url") or "")
        text = pick_article_text(article).strip()
        if not text:
            text = "Dieser Artikel enthaelt in der API nur kurze Metadaten."

        payloads.append({
            "title": title,
            "url": url,
            "text": text,
            "annotated_html": annotate_text_with_levels(text),
        })
    
    return payloads


def remote_translate(text: str, target_lang: str) -> str:
    params = {"q": text, "langpair": f"de|{target_lang}"}
    try:
        response = requests.get(TRANSLATE_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        translated = payload.get("responseData", {}).get("translatedText", "")
        return str(translated).strip()
    except (requests.RequestException, ValueError):
        return ""


@app.route("/")
def page_index() -> str:
    articles = build_articles_payload(MAX_ARTICLES)
    if not articles:
        articles = [{
            "title": "API nicht erreichbar",
            "url": "",
            "text": "Die Tagesschau API konnte nicht geladen werden.",
            "annotated_html": "Die Tagesschau API konnte nicht geladen werden.",
        }]
    return render_template("index.html", articles=articles, target_lang=APP_TARGET_LANG)


@app.route("/api/word-translate")
def api_word_translate():
    word = request.args.get("word", "").strip()
    if not word:
        return jsonify({"error": "Missing word parameter."}), 400

    translated = remote_translate(word, APP_TARGET_LANG)
    if not translated:
        translated = "Translation unavailable"

    return jsonify(
        {
            "source": word,
            "translation": translated,
            "target_lang": APP_TARGET_LANG,
        }
    )


@app.route("/api/text-translate", methods=["POST"])
def api_text_translate():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"error": "Missing text in request body."}), 400

    translated = remote_translate(text, APP_TARGET_LANG)
    if not translated:
        translated = "Translation unavailable"

    return jsonify(
        {
            "source": text,
            "translation": translated,
            "target_lang": APP_TARGET_LANG,
        }
    )


@app.route("/api/text-to-speech", methods=["POST"])
def api_text_to_speech():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"error": "Missing text in request body."}), 400

    # Keep per-request payload bounded for responsive playback.
    if len(text) > 1200:
        return jsonify({"error": "Text too long for one TTS request."}), 400

    try:
        audio_buffer = BytesIO()
        tts = gTTS(text=text, lang=TTS_LANG, slow=False)
        tts.write_to_fp(audio_buffer)
        audio_buffer.seek(0)

        return Response(
            audio_buffer.read(),
            mimetype="audio/mpeg",
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        return jsonify({"error": "TTS unavailable right now."}), 502


@app.route("/api/article/<int:index>")
def api_get_article(index: int):
    articles = build_articles_payload(MAX_ARTICLES)
    if not articles or index < 0 or index >= len(articles):
        return jsonify({"error": "Article not found"}), 404
    return jsonify(articles[index])


if __name__ == "__main__":
    app.run(port=APP_PORT, host=APP_HOST)
