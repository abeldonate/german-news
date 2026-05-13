const cardButton = document.getElementById("deck-card");
const cardFront = document.getElementById("card-front");
const cardBack = document.getElementById("card-back");
const statusLine = document.getElementById("deck-status");
const feedbackButtons = Array.from(document.querySelectorAll(".fb"));

let currentWord = "";
let translationVisible = false;
let translationCached = "";

function setStatus(text) {
  statusLine.textContent = text;
}

function setFeedbackEnabled(enabled) {
  feedbackButtons.forEach((btn) => {
    btn.disabled = !enabled;
  });
}

async function loadNextCard(preloadedCard = null) {
  setFeedbackEnabled(false);
  setStatus("Loading card...");

  try {
    const card = preloadedCard || await fetch("/api/cards/next").then(async (resp) => {
      if (!resp.ok) {
        throw new Error("Could not load the next card.");
      }
      return resp.json();
    });

    currentWord = card.word || "";
    translationVisible = false;
    translationCached = "";
    cardFront.textContent = currentWord || "No word available";
    cardBack.hidden = true;
    cardBack.textContent = "";
    cardButton.classList.remove("revealed");

    if (!currentWord) {
      setStatus("No A2 words found.");
      return;
    }

    const box = Number(card.box || 1);
    setStatus(`Box ${box} / 5 · ${currentWord}`);
    setFeedbackEnabled(true);
  } catch (err) {
    setStatus(err instanceof Error ? err.message : "Unknown error.");
  }
}

async function revealTranslation() {
  if (!currentWord || translationVisible) {
    return;
  }

  cardButton.classList.add("loading");

  try {
    let translated = translationCached;

    if (!translated) {
      const response = await fetch(`/api/cards/translate?word=${encodeURIComponent(currentWord)}`);
      if (!response.ok) {
        throw new Error("Translation unavailable");
      }
      const payload = await response.json();
      translated = String(payload.translation || "").trim() || "Translation unavailable";
      translationCached = translated;
    }

    cardBack.textContent = translated;
    cardBack.hidden = false;
    cardButton.classList.add("revealed");
    translationVisible = true;
    setStatus(`Translation (${window.CARDS_CONFIG.targetLang}): ${translated}`);
  } catch {
    cardBack.textContent = "Translation unavailable";
    cardBack.hidden = false;
    cardButton.classList.add("revealed");
    translationVisible = true;
    setStatus("Translation unavailable.");
  } finally {
    cardButton.classList.remove("loading");
  }
}

async function submitFeedback(rating) {
  if (!currentWord) {
    return;
  }

  setFeedbackEnabled(false);
  setStatus(`Saving feedback: ${rating}...`);

  try {
    const response = await fetch("/api/cards/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: currentWord, rating })
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "Could not save feedback.");
    }

    const payload = await response.json();
    await loadNextCard(payload.next || null);
  } catch (err) {
    setStatus(err instanceof Error ? err.message : "Unknown error.");
    setFeedbackEnabled(true);
  }
}

cardButton.addEventListener("click", revealTranslation);
cardButton.addEventListener("touchstart", revealTranslation, { passive: true });

feedbackButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const rating = button.dataset.rating || "";
    if (rating) {
      submitFeedback(rating);
    }
  });
});

window.addEventListener("keydown", (event) => {
  const key = event.key.toLowerCase();

  if (event.key === " ") {
    event.preventDefault();
    revealTranslation();
  }
  if (key === "j") submitFeedback("hard");
  if (key === "k") submitFeedback("easy");
});

loadNextCard();
