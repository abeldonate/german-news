import os
from typing import Any

import yaml
from cards_logic import LeitnerDeck
from flask import Flask, Response, jsonify, render_template, request
from article_processing import build_articles_payload, load_cefr_levels
from listening_service import build_tts_audio
from translation_service import remote_translate

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


CEFR_LEVELS = load_cefr_levels(FEATURE_SETTINGS.get("cefr_level_files", {}))
A2_CONTENT_BLOCK_TYPES = set(FEATURE_SETTINGS.get("content_block_types", ["text", "headline"]))
A2_WORDS_FILE = os.path.join(
    os.path.abspath("."),
    str(FEATURE_SETTINGS.get("cefr_level_files", {}).get("a2", "data/a2.txt")),
)
CARDS_STATE_FILE = os.path.join(
    os.path.abspath("."),
    str(FEATURE_SETTINGS.get("cards_state_file", "data/cards_a2_state.yml")),
)
LEITNER_BOX0_LIMIT = int(FEATURE_SETTINGS.get("leitner_box0_limit", 50))

CARDS_A2_DECK = LeitnerDeck(
    words_file=A2_WORDS_FILE,
    state_file=CARDS_STATE_FILE,
    box0_limit=LEITNER_BOX0_LIMIT,
)


@app.route("/")
def page_dashboard() -> str:
    return render_template("dashboard.html")


@app.route("/news")
def page_news() -> str:
    articles = build_articles_payload(
        TAGESSCHAU_HOMEPAGE_API,
        MAX_ARTICLES,
        A2_CONTENT_BLOCK_TYPES,
        CEFR_LEVELS,
        REQUEST_TIMEOUT_SECONDS,
        REQUEST_USER_AGENT,
    )
    if not articles:
        articles = [{
            "title": "API nicht erreichbar",
            "url": "",
            "text": "Die Tagesschau API konnte nicht geladen werden.",
            "annotated_html": "Die Tagesschau API konnte nicht geladen werden.",
        }]
    return render_template("index.html", articles=articles, target_lang=APP_TARGET_LANG)


@app.route("/cards")
def page_cards() -> str:
    return render_template("cards.html", target_lang=APP_TARGET_LANG)


@app.route("/api/word-translate")
def api_word_translate():
    word = request.args.get("word", "").strip()
    if not word:
        return jsonify({"error": "Missing word parameter."}), 400

    translated = remote_translate(word, APP_TARGET_LANG, TRANSLATE_ENDPOINT, REQUEST_TIMEOUT_SECONDS)
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

    translated = remote_translate(text, APP_TARGET_LANG, TRANSLATE_ENDPOINT, REQUEST_TIMEOUT_SECONDS)
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
        audio_bytes = build_tts_audio(text, TTS_LANG)

        return Response(
            audio_bytes,
            mimetype="audio/mpeg",
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        return jsonify({"error": "TTS unavailable right now."}), 502


@app.route("/api/article/<int:index>")
def api_get_article(index: int):
    articles = build_articles_payload(
        TAGESSCHAU_HOMEPAGE_API,
        MAX_ARTICLES,
        A2_CONTENT_BLOCK_TYPES,
        CEFR_LEVELS,
        REQUEST_TIMEOUT_SECONDS,
        REQUEST_USER_AGENT,
    )
    if not articles or index < 0 or index >= len(articles):
        return jsonify({"error": "Article not found"}), 404
    return jsonify(articles[index])


@app.route("/api/cards/next")
def api_cards_next():
    card = CARDS_A2_DECK.next_card()
    if not card:
        return jsonify({"error": "No cards available"}), 404
    return jsonify(card)


@app.route("/api/cards/translate")
def api_cards_translate():
    word = request.args.get("word", "").strip()
    if not word:
        return jsonify({"error": "Missing word parameter."}), 400

    translated = CARDS_A2_DECK.translation_for(
        word,
        lambda source_word: remote_translate(source_word, APP_TARGET_LANG, TRANSLATE_ENDPOINT, REQUEST_TIMEOUT_SECONDS),
    )
    if not translated:
        translated = "Translation unavailable"

    return jsonify({"source": word, "translation": translated, "target_lang": APP_TARGET_LANG})


@app.route("/api/cards/feedback", methods=["POST"])
def api_cards_feedback():
    payload = request.get_json(silent=True) or {}
    word = str(payload.get("word", "")).strip()
    rating = str(payload.get("rating", "")).strip().lower()

    if not word or not rating:
        return jsonify({"error": "Missing word or rating in request body."}), 400

    try:
        updated_card = CARDS_A2_DECK.apply_feedback(word, rating)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    next_card = CARDS_A2_DECK.next_card()
    return jsonify({"updated": updated_card, "next": next_card})


if __name__ == "__main__":
    app.run(port=APP_PORT, host=APP_HOST)
