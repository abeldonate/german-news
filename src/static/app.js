const articleText = document.getElementById("article-text");
const articleTitle = document.getElementById("article-title");
const articleUrl = document.getElementById("article-url");
const tooltip = document.getElementById("word-tooltip");
const tooltipSource = tooltip.querySelector(".word-tooltip-source");
const tooltipTranslation = tooltip.querySelector(".word-tooltip-translation");
const selectionActions = tooltip.querySelector(".selection-actions");
const selectionTranslateButton = document.getElementById("selection-translate");
const selectionListenButton = document.getElementById("selection-listen");
const listenAllButton = document.getElementById("listen-all");

let activeWord = null;
let currentArticleIndex = 0;
let selectedTextForActions = "";
let articleQueue = [];
let articleQueueIndex = 0;
let articleAudio = null;
let activeAudioUrl = null;
let isArticleLoading = false;

function browserFallbackSpeak(text) {
  if (!("speechSynthesis" in window)) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "de-DE";
  utterance.rate = 0.9;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

function setListenAllButtonState(isListening) {
  if (!listenAllButton) return;
  listenAllButton.textContent = isListening ? "■ Stop" : "🔊 Listen";
  listenAllButton.setAttribute("aria-pressed", isListening ? "true" : "false");
}

function clearSelectionActionState() {
  selectedTextForActions = "";
  selectionActions.hidden = true;
}

function stopArticleListening() {
  if (articleAudio) {
    articleAudio.pause();
    articleAudio.currentTime = 0;
    articleAudio = null;
  }
  if (activeAudioUrl) {
    URL.revokeObjectURL(activeAudioUrl);
    activeAudioUrl = null;
  }
  isArticleLoading = false;
  articleQueue = [];
  articleQueueIndex = 0;
  setListenAllButtonState(false);
}

function normalizeSpeechText(text) {
  return String(text)
    .replace(/\s+/g, " ")
    .replace(/\s([,.;:!?])/g, "$1")
    .trim();
}

function splitIntoSpeechChunks(text) {
  const normalized = normalizeSpeechText(text);
  if (!normalized) return [];

  const sentences = normalized.match(/[^.!?]+[.!?]?/g) || [normalized];
  const chunks = [];
  for (const sentence of sentences) {
    const s = sentence.trim();
    if (!s) continue;

    if (s.length <= 220) {
      chunks.push(s);
      continue;
    }

    // Break very long sentences on commas/semicolons to keep TTS intelligible.
    const clauses = s.split(/(?<=[,;:])\s+/);
    for (const clause of clauses) {
      const c = clause.trim();
      if (c) chunks.push(c);
    }
  }

  return chunks;
}

async function fetchTtsAudioBlob(text) {
  let lastError = null;

  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      const response = await fetch("/api/text-to-speech", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });

      if (!response.ok) {
        let message = `TTS request failed (${response.status}).`;
        try {
          const data = await response.json();
          if (data && typeof data.error === "string" && data.error.trim()) {
            message = data.error;
          }
        } catch {
          // Ignore JSON parse failure and keep default message.
        }
        throw new Error(message);
      }

      return response.blob();
    } catch (err) {
      lastError = err;
      if (attempt === 2) break;
    }
  }

  throw lastError || new Error("TTS unavailable right now.");
}

async function playNextArticleChunk() {
  if (articleQueueIndex >= articleQueue.length) {
    if (activeAudioUrl) {
      URL.revokeObjectURL(activeAudioUrl);
      activeAudioUrl = null;
    }
    articleQueue = [];
    articleQueueIndex = 0;
    isArticleLoading = false;
    setListenAllButtonState(false);
    return;
  }

  const text = articleQueue[articleQueueIndex];
  isArticleLoading = true;

  try {
    const blob = await fetchTtsAudioBlob(text);
    if (!articleQueue.length) return;

    if (activeAudioUrl) {
      URL.revokeObjectURL(activeAudioUrl);
    }
    activeAudioUrl = URL.createObjectURL(blob);
    articleAudio = new Audio(activeAudioUrl);
    articleAudio.onended = () => {
      articleAudio = null;
    articleQueueIndex += 1;
      playNextArticleChunk();
    };
    articleAudio.onerror = () => {
      stopArticleListening();
      alert("Audio playback failed.");
    };
    isArticleLoading = false;
    try {
      await articleAudio.play();
    } catch (err) {
      stopArticleListening();
      if (err && err.name === "NotAllowedError") {
        alert("Playback was blocked by the browser. Click Listen again to allow audio.");
      } else {
        alert("Audio playback failed.");
      }
    }
  } catch (err) {
    stopArticleListening();
    const msg = err instanceof Error ? err.message : "TTS unavailable right now.";
    browserFallbackSpeak(text);
    alert(`${msg} Falling back to browser voice.`);
  }
}

function positionTooltip(targetEl) {
  const rect = targetEl.getBoundingClientRect();
  positionTooltipForRect(rect);
}

function positionTooltipForRect(rect) {
  const scrollY = window.scrollY;
  const scrollX = window.scrollX;

  // Place above the word, centred horizontally
  tooltip.style.left = "0";
  tooltip.style.top = "0";
  tooltip.hidden = false;

  const tw = tooltip.offsetWidth;
  let left = rect.left + scrollX + rect.width / 2 - tw / 2;
  // Clamp so it never escapes the viewport horizontally
  left = Math.max(8, Math.min(left, document.documentElement.clientWidth - tw - 8));

  const top = rect.top + scrollY - tooltip.offsetHeight - 10;
  tooltip.style.left = left + "px";
  tooltip.style.top = top + "px";
}

function showTooltip(wordEl, source, translation) {
  clearSelectionActionState();
  tooltipSource.textContent = source;
  tooltipTranslation.textContent = translation;
  tooltip.hidden = false;
  positionTooltip(wordEl);
}

function showSelectionContextBox(text, rect) {
  selectedTextForActions = text;
  selectionActions.hidden = false;
  tooltipSource.textContent = text.length > 80 ? text.slice(0, 80) + "..." : text;
  tooltipTranslation.textContent = "";
  tooltip.hidden = false;
  positionTooltipForRect(rect);
}

function hideTooltip() {
  tooltip.hidden = true;
  clearSelectionActionState();
  if (activeWord) {
    activeWord.classList.remove("word--active");
    activeWord = null;
  }
}

// Close on outside click
document.addEventListener("click", (e) => {
  if (!tooltip.contains(e.target) && !e.target.classList.contains("word")) {
    hideTooltip();
  }
});

async function fetchWordTranslation(word) {
  const response = await fetch(`/api/word-translate?word=${encodeURIComponent(word)}`);
  if (!response.ok) {
    throw new Error("Word translation failed.");
  }
  return response.json();
}

async function fetchTextTranslation(text) {
  const response = await fetch("/api/text-translate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text })
  });
  if (!response.ok) {
    throw new Error("Text translation failed.");
  }
  return response.json();
}

function getSelectedText() {
  const selected = window.getSelection();
  if (!selected) return "";
  return selected.toString().trim();
}

function speakText(text) {
  const normalized = normalizeSpeechText(text);
  if (!normalized) {
    alert("Please select some text first.");
    return;
  }

  stopArticleListening();
  fetchTtsAudioBlob(normalized)
    .then((blob) => {
      const oneShotUrl = URL.createObjectURL(blob);
      const oneShotAudio = new Audio(oneShotUrl);
      oneShotAudio.onended = () => URL.revokeObjectURL(oneShotUrl);
      oneShotAudio.onerror = () => {
        URL.revokeObjectURL(oneShotUrl);
        alert("Audio playback failed.");
      };
      return oneShotAudio.play();
    })
    .catch((err) => {
      const msg = err instanceof Error ? err.message : "TTS unavailable right now.";
      browserFallbackSpeak(normalized);
      alert(`${msg} Falling back to browser voice.`);
    });
}

function updateArticleDisplay(article) {
  articleTitle.textContent = article.title;
  articleText.innerHTML = article.annotated_html;
  if (articleUrl && article.url) {
    articleUrl.href = article.url;
  }
  stopArticleListening();
  window.getSelection()?.removeAllRanges();
  hideTooltip();
  window.scrollTo(0, 0);
}

// Article selection
document.querySelectorAll(".article-item").forEach((item, index) => {
  item.addEventListener("click", () => {
    const allItems = document.querySelectorAll(".article-item");
    allItems.forEach(it => it.classList.remove("article-item--active"));
    item.classList.add("article-item--active");
    currentArticleIndex = index;
    const article = window.APP_CONFIG.articles[index];
    if (article) {
      updateArticleDisplay(article);
    }
  });
});

articleText.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (!target.classList.contains("word")) return;

  // Toggle off if same word clicked again
  if (activeWord === target) {
    hideTooltip();
    return;
  }

  if (activeWord) activeWord.classList.remove("word--active");
  activeWord = target;
  target.classList.add("word--active");

  const word = target.dataset.word || target.textContent || "";
  if (!word) return;

  tooltipSource.textContent = word;
  tooltipTranslation.textContent = "…";
  tooltip.hidden = false;
  positionTooltip(target);

  try {
    const result = await fetchWordTranslation(word);
    showTooltip(target, result.source, result.translation);
  } catch {
    showTooltip(target, word, "Translation unavailable");
  }
});

function maybeShowSelectionContext() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
    if (!activeWord) hideTooltip();
    return;
  }

  const range = sel.getRangeAt(0);
  if (!articleText.contains(range.commonAncestorContainer)) {
    return;
  }

  const text = sel.toString().trim();
  if (!text) return;

  const rect = range.getBoundingClientRect();
  if (!rect || rect.width === 0) return;

  if (activeWord) {
    activeWord.classList.remove("word--active");
    activeWord = null;
  }

  showSelectionContextBox(text, rect);
}

articleText.addEventListener("mouseup", () => {
  setTimeout(maybeShowSelectionContext, 0);
});

articleText.addEventListener("keyup", (event) => {
  if (event.key && event.key.startsWith("Arrow")) return;
  setTimeout(maybeShowSelectionContext, 0);
});

selectionTranslateButton.addEventListener("click", async (event) => {
  event.stopPropagation();
  const text = selectedTextForActions || getSelectedText();
  if (!text) {
    alert("Select a sentence first.");
    return;
  }

  tooltipTranslation.textContent = "...";
  try {
    const result = await fetchTextTranslation(text);
    tooltipTranslation.textContent = result.translation || "Translation unavailable";
  } catch {
    tooltipTranslation.textContent = "Translation unavailable";
  }
});

selectionListenButton.addEventListener("click", (event) => {
  event.stopPropagation();
  const text = selectedTextForActions || getSelectedText();
  speakText(text);
});

listenAllButton.addEventListener("click", () => {
  if (articleAudio || isArticleLoading || articleQueue.length > 0) {
    stopArticleListening();
    return;
  }

  const text = normalizeSpeechText(articleText.textContent || "");
  if (!text) {
    alert("There is no article text to read.");
    return;
  }

  articleQueue = splitIntoSpeechChunks(text);
  articleQueueIndex = 0;
  if (!articleQueue.length) {
    alert("There is no article text to read.");
    return;
  }

  isArticleLoading = true;
  setListenAllButtonState(true);
  playNextArticleChunk();
});
