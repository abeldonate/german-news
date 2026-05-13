import os
import random
from threading import Lock
from typing import Any, Callable

import yaml

# Box weights: cards in lower boxes are shown more frequently.
# Box 1 is shown 16× more often than box 5.
# Default weights; can be overridden by config at runtime.
_DEFAULT_BOX_WEIGHTS = {0: 1, 1: 12, 2: 4, 3: 2, 4: 1, 5: 0}


class LeitnerDeck:
    """Leitner-box flashcard deck.

    Box 0 — new words not yet introduced.
    Boxes 1–5 — active study boxes; lower boxes are reviewed more often.

    Correct answer (easy)  → move to box + 1 (max 5).
    Wrong answer  (hard)   → move back to box 1.

    At most *box0_limit* words are active (boxes 1–5) at any time.
    Whenever active < box0_limit, words are introduced from box 0.
    """

    def __init__(
        self,
        words_file: str,
        state_file: str,
        box0_limit: int = 50,
        box_ratios: dict[str, int] | None = None,
    ) -> None:
        self.words_file = words_file
        self.state_file = state_file
        self.box0_limit = max(1, int(box0_limit))
        self._lock = Lock()
        self._box_weights = self._build_weights(box_ratios or {})
        self._state = self._load_state()

    # ------------------------------------------------------------------ helpers

    def _build_weights(self, box_ratios: dict[str, int]) -> dict[int, int]:
        """Normalize box ratios into integer weights for random.choices()."""
        weights = {}
        for box_num in range(6):
            key = f"box{box_num}"
            ratio = int(box_ratios.get(key, 0))
            weights[box_num] = max(0, ratio)
        # If all weights are 0, use defaults.
        if sum(weights.values()) == 0:
            weights = _DEFAULT_BOX_WEIGHTS.copy()
        return weights

    def _load_words(self) -> list[str]:
        words: list[str] = []
        if not os.path.exists(self.words_file):
            return words
        try:
            with open(self.words_file, "r", encoding="utf-8") as fh:
                for raw in fh:
                    candidate = raw.strip()
                    if not candidate or candidate.startswith("#"):
                        continue
                    words.append(candidate)
        except OSError:
            return []
        seen: set[str] = set()
        unique: list[str] = []
        for word in words:
            key = word.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(word)
        return unique

    def _load_state(self) -> dict[str, Any]:
        words = self._load_words()
        state: dict[str, Any] = {"cards": {}, "translations": {}}

        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as fh:
                    parsed = yaml.safe_load(fh) or {}
                    if isinstance(parsed, dict):
                        raw_cards = parsed.get("cards", {})
                        if isinstance(raw_cards, dict):
                            state["cards"] = raw_cards
                        raw_trans = parsed.get("translations", {})
                        if isinstance(raw_trans, dict):
                            state["translations"] = raw_trans
            except (OSError, yaml.YAMLError):
                pass

        cards = state["cards"]
        # Ensure every word in the source file has a card entry.
        for word in words:
            entry = cards.get(word)
            if not isinstance(entry, dict) or "box" not in entry:
                cards[word] = {"box": 0}
            else:
                # Clamp box to valid range in case of corrupted state.
                cards[word]["box"] = max(0, min(5, int(entry.get("box", 0))))

        # Remove entries for words no longer in the source file.
        valid = set(words)
        for word in list(cards.keys()):
            if word not in valid:
                del cards[word]

        self._save_state(state)
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
        payload = {
            "cards": state.get("cards", {}),
            "translations": state.get("translations", {}),
        }
        temp = f"{self.state_file}.tmp"
        with open(temp, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=True)
        os.replace(temp, self.state_file)

    def _active_count(self, cards: dict[str, Any]) -> int:
        return sum(1 for c in cards.values() if isinstance(c, dict) and c.get("box", 0) >= 1)

    def _introduce_new_words(self, cards: dict[str, Any]) -> None:
        """Move words from box 0 to box 1 until active count reaches box0_limit."""
        needed = self.box0_limit - self._active_count(cards)
        if needed <= 0:
            return
        box0 = [w for w, c in cards.items() if isinstance(c, dict) and c.get("box", 0) == 0]
        for word in box0[:needed]:
            cards[word]["box"] = 1

    def _card_payload(self, word: str, card: dict[str, Any]) -> dict[str, Any]:
        return {"word": word, "box": int(card.get("box", 1))}

    # ------------------------------------------------------------------ public

    def next_card(self) -> dict[str, Any] | None:
        with self._lock:
            cards = self._state.get("cards", {})
            self._introduce_new_words(cards)

            # Collect cards from all active boxes (0-5).
            active = [(w, c) for w, c in cards.items()
                      if isinstance(c, dict) and 0 <= c.get("box", 0) <= 5]
            if not active:
                return None

            # Weight each card by its box's ratio.
            weights = [self._box_weights.get(c.get("box", 1), 1) for _, c in active]
            # Skip selection if all weights are 0.
            if sum(weights) == 0:
                weights = [1] * len(active)
            
            (word, card), = random.choices(active, weights=weights, k=1)
            return self._card_payload(word, card)

    def translation_for(self, word: str, translate_fn: Callable[[str], str]) -> str:
        with self._lock:
            cards = self._state.get("cards", {})
            if word not in cards:
                raise ValueError("Unknown card word.")
            translations = self._state.setdefault("translations", {})
            cached = translations.get(word)
            if isinstance(cached, str) and cached.strip():
                return cached

        translated = str(translate_fn(word) or "").strip()
        if not translated:
            return ""

        with self._lock:
            self._state.setdefault("translations", {})[word] = translated
            self._save_state(self._state)
        return translated

    def apply_feedback(self, word: str, rating: str) -> dict[str, Any]:
        normalized = rating.strip().lower()
        if normalized not in {"hard", "easy"}:
            raise ValueError("Invalid rating. Use 'easy' or 'hard'.")

        with self._lock:
            cards = self._state.get("cards", {})
            card = cards.get(word)
            if not isinstance(card, dict):
                raise ValueError("Unknown card word.")

            box = int(card.get("box", 1))
            if normalized == "easy":
                card["box"] = min(box + 1, 5)
            else:
                card["box"] = 1

            self._save_state(self._state)
            return self._card_payload(word, card)
