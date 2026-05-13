import html
import os
import re
from typing import Any

import requests
from markupsafe import Markup

_TAG_PATTERN = re.compile(r"<[^>]+>")


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


def fetch_json(url: str, timeout_seconds: int, user_agent: str) -> dict[str, Any] | None:
    headers = {"User-Agent": user_agent}
    try:
        response = requests.get(url, headers=headers, timeout=timeout_seconds)
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


def extract_text_from_content_blocks(content: list[Any], content_block_types: set[str]) -> str:
    paragraphs: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        if block_type not in content_block_types:
            continue
        value = block.get("value", "")
        if not isinstance(value, str):
            continue
        text = strip_html_tags(value)
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def pick_article_text(
    article: dict[str, Any],
    content_block_types: set[str],
    timeout_seconds: int,
    user_agent: str,
) -> str:
    # Prefer the dedicated details JSON endpoint for full content
    details_url = article.get("details", "")
    if details_url and isinstance(details_url, str) and details_url.startswith("http"):
        details_data = fetch_json(details_url, timeout_seconds, user_agent)
        if details_data:
            blocks = details_data.get("content", [])
            if isinstance(blocks, list):
                text = extract_text_from_content_blocks(blocks, content_block_types)
                if text:
                    return text

    # Fall back to content blocks already embedded in the homepage article node
    blocks = article.get("content", [])
    if isinstance(blocks, list):
        text = extract_text_from_content_blocks(blocks, content_block_types)
        if text:
            return text

    # Last resort: use the short teaser fields only
    teaser_parts = [
        article.get("firstSentence", ""),
        article.get("teasertext", ""),
    ]
    return "\n\n".join(p for p in teaser_parts if p)


def cefr_level_for_word(word: str, cefr_levels: dict[str, set[str]]) -> str | None:
    normalized = word.lower()
    for level, words in cefr_levels.items():
        if normalized in words:
            return level
    return None


def annotate_text_with_levels(text: str, cefr_levels: dict[str, set[str]]) -> Markup:
    token_pattern = re.compile(r"[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)*|\s+|[^\w\s]", re.UNICODE)
    parts: list[str] = []

    for token in token_pattern.findall(text):
        if token.isspace():
            parts.append(token)
        elif re.fullmatch(r"[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)*", token):
            level = cefr_level_for_word(token, cefr_levels)
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


def build_articles_payload(
    homepage_api: str,
    max_count: int,
    content_block_types: set[str],
    cefr_levels: dict[str, set[str]],
    timeout_seconds: int,
    user_agent: str,
) -> list[dict[str, Any]]:
    """Fetch and parse multiple articles from the API."""
    homepage_data = fetch_json(homepage_api, timeout_seconds, user_agent)
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
        text = pick_article_text(article, content_block_types, timeout_seconds, user_agent).strip()
        if not text:
            text = "Dieser Artikel enthaelt in der API nur kurze Metadaten."

        payloads.append({
            "title": title,
            "url": url,
            "text": text,
            "annotated_html": annotate_text_with_levels(text, cefr_levels),
        })

    return payloads