const phraseEnglish = document.getElementById("phrase-english");
const wordBoard = document.getElementById("word-board");
const statusLine = document.getElementById("fill-status");
const giveUpButton = document.getElementById("btn-give-up");
const levelButton = document.getElementById("btn-level");
const nextButton = document.getElementById("btn-next");

const levels = ["a1", "a2"];
let currentLevelIndex = 0;
let currentPhraseIndex = -1;
let currentPhrases = [];
let answerInputs = [];
let solved = false;

function normalizeWord(text) {
  return String(text)
    .trim()
    .toLowerCase()
    .replace(/[.,!?;:]/g, "")
    .replace(/\s+/g, " ");
}

function setStatus(text) {
  statusLine.textContent = text;
}

function setLevelButtonText() {
  const level = levels[currentLevelIndex].toUpperCase();
  levelButton.textContent = `Level: ${level}`;
}

function isPhraseSolved() {
  if (!answerInputs.length) return false;
  return answerInputs.every(({ letterInputs, expected }) => {
    const builtWord = letterInputs.map((input) => input.value).join("");
    return normalizeWord(builtWord) === normalizeWord(expected);
  });
}

function onInputChanged() {
  answerInputs.forEach(({ card, letterInputs, expected }) => {
    const builtWord = letterInputs.map((input) => input.value).join("");
    const correct = normalizeWord(builtWord) === normalizeWord(expected);
    card.classList.toggle("word-card-correct", correct);
    letterInputs.forEach((input) => {
      input.classList.toggle("correct", correct);
    });
  });

  if (!solved && isPhraseSolved()) {
    solved = true;
    setStatus("Great! Phrase completed. Press Next for another one.");
  }
}

function moveFocusToNext(letterInputs, index) {
  if (index < letterInputs.length - 1) {
    letterInputs[index + 1].focus();
    return;
  }

  for (const entry of answerInputs) {
    const empty = entry.letterInputs.find((input) => !input.value.trim());
    if (empty) {
      empty.focus();
      return;
    }
  }
}

function sanitizeTypedCharacter(rawValue) {
  const value = String(rawValue || "").trim();
  if (!value) return "";
  const chars = Array.from(value);
  return chars[chars.length - 1] || "";
}

function buildWordCard(pair, index) {
  const card = document.createElement("div");
  card.className = "word-card";

  const hint = document.createElement("div");
  hint.className = "word-hint";
  hint.textContent = `${index + 1}. ${pair.en}`;

  const expected = normalizeWord(pair.de);
  const letters = Array.from(expected);

  const meta = document.createElement("div");
  meta.className = "word-meta";
  meta.textContent = `${letters.length} letters`;

  const letterGrid = document.createElement("div");
  letterGrid.className = "letter-grid";

  const letterInputs = letters.map((_, letterIndex) => {
    const input = document.createElement("input");
    input.className = "letter-box";
    input.type = "text";
    input.maxLength = 1;
    input.autocomplete = "off";
    input.spellcheck = false;
    input.inputMode = "text";
    input.setAttribute("aria-label", `Letter ${letterIndex + 1} for German word ${pair.en}`);

    input.addEventListener("input", () => {
      input.value = sanitizeTypedCharacter(input.value);
      input.classList.remove("revealed");
      if (input.value) {
        moveFocusToNext(letterInputs, letterIndex);
      }
      onInputChanged();
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Backspace" && !input.value && letterIndex > 0) {
        letterInputs[letterIndex - 1].focus();
      }
    });

    letterGrid.appendChild(input);
    return input;
  });

  card.appendChild(hint);
  card.appendChild(meta);
  card.appendChild(letterGrid);

  return { card, letterInputs, expected: pair.de };
}

function renderPhrase(phrase) {
  phraseEnglish.textContent = phrase.english;
  wordBoard.innerHTML = "";
  answerInputs = [];
  solved = false;

  phrase.pairs.forEach((pair, index) => {
    const built = buildWordCard(pair, index);
    answerInputs.push({ card: built.card, letterInputs: built.letterInputs, expected: built.expected });
    wordBoard.appendChild(built.card);
  });

  if (answerInputs.length && answerInputs[0].letterInputs.length) {
    answerInputs[0].letterInputs[0].focus();
  }

  setStatus(`Fill all German words letter by letter (${phrase.pairs.length} total).`);
}

function showNextPhrase() {
  if (!currentPhrases.length) {
    phraseEnglish.textContent = "No phrases available for this level.";
    wordBoard.innerHTML = "";
    answerInputs = [];
    setStatus("Add phrases to continue.");
    return;
  }

  currentPhraseIndex = (currentPhraseIndex + 1) % currentPhrases.length;
  renderPhrase(currentPhrases[currentPhraseIndex]);
}

async function loadLevel(level) {
  setStatus(`Loading ${level.toUpperCase()} phrases...`);
  phraseEnglish.textContent = "Loading...";
  wordBoard.innerHTML = "";

  try {
    const response = await fetch(`/api/fill-in/phrases?level=${encodeURIComponent(level)}`);
    if (!response.ok) {
      throw new Error("Could not load level phrases.");
    }

    const payload = await response.json();
    currentPhrases = Array.isArray(payload.phrases) ? payload.phrases : [];
    currentPhraseIndex = -1;
    showNextPhrase();
  } catch (err) {
    phraseEnglish.textContent = "Failed to load phrases.";
    setStatus(err instanceof Error ? err.message : "Unknown error.");
  }
}

function giveUp() {
  if (!answerInputs.length) return;

  answerInputs.forEach(({ card, letterInputs, expected }) => {
    const letters = Array.from(normalizeWord(expected));
    letterInputs.forEach((input, index) => {
      input.value = letters[index] || "";
      input.classList.remove("correct");
      input.classList.add("revealed");
      input.disabled = true;
    });
    card.classList.remove("word-card-correct");
  });

  solved = true;
  setStatus("Answer revealed. Press Next to continue.");
}

function nextLevel() {
  currentLevelIndex = (currentLevelIndex + 1) % levels.length;
  setLevelButtonText();
  loadLevel(levels[currentLevelIndex]);
}

function nextPhrase() {
  showNextPhrase();
}

giveUpButton.addEventListener("click", giveUp);
levelButton.addEventListener("click", nextLevel);
nextButton.addEventListener("click", nextPhrase);

setLevelButtonText();
loadLevel(levels[currentLevelIndex]);
