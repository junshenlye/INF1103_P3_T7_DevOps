const dropZone = document.querySelector("#drop-zone");
const fileInput = document.querySelector("#source-files");
const fileList = document.querySelector("#file-list");
const form = document.querySelector("#assessment-form");
const progressPanel = document.querySelector("#extraction-progress");
const progressStage = document.querySelector("#progress-stage");
const progressElapsed = document.querySelector("#progress-elapsed");
const progressMessage = document.querySelector("#progress-message");
const apiBaseUrl = document.body.dataset.apiBase || "http://127.0.0.1:8000";

function apiUrl(path) {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${apiBaseUrl}${path}`;
}

function renderFiles(files) {
  if (!fileList) return;
  fileList.replaceChildren();
  Array.from(files).forEach((file) => {
    const item = document.createElement("div");
    item.className = "file-pill";
    item.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
    fileList.appendChild(item);
  });
}

if (dropZone && fileInput) {
  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("is-dragging");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("is-dragging");
    });
  });

  dropZone.addEventListener("drop", (event) => {
    if (!event.dataTransfer || !event.dataTransfer.files.length) return;
    fileInput.files = event.dataTransfer.files;
    renderFiles(fileInput.files);
  });

  fileInput.addEventListener("change", () => renderFiles(fileInput.files));
}

function resetSubmitButton() {
  if (!form) return;
  const button = form.querySelector("button[type='submit']");
  if (!button) return;
  button.disabled = false;
  button.querySelector("span:first-child").textContent = "Build schedule";
}

function showProgressError(message) {
  if (!progressPanel || !progressStage || !progressMessage) return;
  progressPanel.hidden = false;
  progressPanel.classList.add("is-failed");
  progressStage.textContent = "Extraction could not continue";
  progressMessage.textContent = message;
  resetSubmitButton();
}

if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type='submit']");
    if (!button || !progressPanel) return;
    button.disabled = true;
    button.querySelector("span:first-child").textContent = "Building schedule…";
    progressPanel.hidden = false;
    progressPanel.classList.remove("is-failed");
    if (progressStage) progressStage.textContent = "AI is building the schedule";
    if (progressMessage) progressMessage.textContent = "A backup model is used automatically if needed.";
    if (progressElapsed) progressElapsed.textContent = "0.0s";
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      if (progressElapsed) {
        progressElapsed.textContent = `${((Date.now() - startedAt) / 1000).toFixed(1)}s`;
      }
    }, 200);

    try {
      const response = await fetch(apiUrl("/api/extractions"), {
        method: "POST",
        body: new FormData(form),
      });
      const payload = await response.json();
      window.clearInterval(timer);
      if (!response.ok) {
        showProgressError(payload.errors?.[0] || "The schedule could not be created.");
        return;
      }
      window.location.assign("/");
    } catch (_error) {
      window.clearInterval(timer);
      showProgressError("The extraction request could not reach the local server.");
    }
  });
}
