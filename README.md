## German News Learning App

Small Flask app to fetch one article from Tagesschau and render it for German learning.

### Features

- Loads one article from the Tagesschau API.
- Click a word to get a translation.
- Select a sentence and translate the full selection.
- Listen to selected text or the full article using browser text-to-speech (in progress).
- Highlights vocabulary with CEFR color tags (A2, B1, B2, C1).
- Includes an A2 spaced-repetition deck page at /cards.
- Tap a German word card to reveal translation, then rate with Again/Hard/Good/Easy.
- Includes a Fill-in phrase game at /fill-in with A1/A2 phrase packs.

### Setup

    $ make setup

### Run

    $ make run

The app starts at http://localhost:5000.

### Optional Environment Variables

- TAGESSCHAU_HOMEPAGE_API: Override Tagesschau endpoint.
- APP_TARGET_LANG: Translation target language (default: en).
- TRANSLATE_ENDPOINT: Override translation service endpoint.

### Configuration

All main app parameters are now in config.yml (API endpoints, request timeout, CEFR levels, and fallback translations/messages).

### Requirements

Python 3, pip, virtualenv and make.