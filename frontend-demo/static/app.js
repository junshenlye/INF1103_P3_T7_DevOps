const dropZone = document.querySelector("#drop-zone");
const fileInput = document.querySelector("#source-files");
const fileList = document.querySelector("#file-list");
const form = document.querySelector("#assessment-form");
const progressPanel = document.querySelector("#extraction-progress");
const progressStage = document.querySelector("#progress-stage");
const progressElapsed = document.querySelector("#progress-elapsed");
const progressMessage = document.querySelector("#progress-message");
const progressEvents = document.querySelector("#progress-events");
const progressBar = document.querySelector("#progress-bar");
const apiBaseUrl = document.body.dataset.apiBase || "http://127.0.0.1:8000";

function apiUrl(path) {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${apiBaseUrl}${path}`;
}

const stageLabels = {
  queued: "Queued",
  starting: "Starting extraction",
  validating: "Validating evidence",
  ai_request: "Nemotron is reading the evidence",
  ai_validation: "Validating Nemotron response",
  retrying: "Retrying model extraction",
  ai_complete: "AI extraction validated",
  planning: "Building weekly plan",
  saving: "Saving module plan",
  complete: "Extraction complete",
  failed: "Extraction stopped",
};

const stageProgress = {
  queued: 5,
  starting: 10,
  validating: 16,
  ai_request: 42,
  retrying: 48,
  ai_validation: 62,
  ai_complete: 72,
  planning: 82,
  saving: 92,
  complete: 100,
  failed: 100,
};

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
  button.querySelector("span:first-child").textContent = "Extract assessment events";
}

function showProgressError(message) {
  if (!progressPanel || !progressStage || !progressMessage || !progressBar) return;
  progressPanel.hidden = false;
  progressPanel.classList.add("is-failed");
  progressStage.textContent = "Extraction could not continue";
  progressMessage.textContent = message;
  progressBar.style.width = "100%";
  resetSubmitButton();
}

function renderProgress(job) {
  if (
    !progressPanel ||
    !progressStage ||
    !progressElapsed ||
    !progressMessage ||
    !progressEvents ||
    !progressBar
  ) return;

  progressPanel.hidden = false;
  progressPanel.classList.toggle("is-failed", job.status === "failed");
  progressPanel.classList.toggle("is-complete", job.status === "complete");
  let label = stageLabels[job.stage] || job.stage.replaceAll("_", " ");
  if (job.attempt && job.max_attempts) {
    label += ` · attempt ${job.attempt}/${job.max_attempts}`;
  }
  progressStage.textContent = label;
  progressElapsed.textContent = `${job.elapsed_seconds.toFixed(1)}s`;
  progressMessage.textContent = job.message;
  progressBar.style.width = `${stageProgress[job.stage] || 12}%`;

  progressEvents.replaceChildren();
  job.events.forEach((progressEvent) => {
    const item = document.createElement("li");
    const timestamp = document.createElement("time");
    const message = document.createElement("span");
    timestamp.textContent = `${Number(progressEvent.elapsed_seconds).toFixed(1)}s`;
    message.textContent = progressEvent.message;
    item.append(timestamp, message);
    progressEvents.appendChild(item);
  });
  progressEvents.scrollTop = progressEvents.scrollHeight;
}

async function pollExtraction(statusUrl) {
  try {
    const response = await fetch(apiUrl(statusUrl), { cache: "no-store" });
    const job = await response.json();
    if (!response.ok) {
      showProgressError(job.errors?.[0] || "Progress status is unavailable.");
      return;
    }
    renderProgress(job);
    if (job.status === "complete") {
      window.setTimeout(() => window.location.assign("/"), 900);
      return;
    }
    if (job.status === "failed") {
      resetSubmitButton();
      return;
    }
    window.setTimeout(() => pollExtraction(statusUrl), 900);
  } catch (_error) {
    showProgressError("The progress connection was interrupted. Try again.");
  }
}

if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type='submit']");
    if (!button || !progressPanel) return;
    button.disabled = true;
    button.querySelector("span:first-child").textContent = "Starting extraction…";
    progressPanel.hidden = false;
    progressPanel.classList.remove("is-failed", "is-complete");
    if (progressStage) progressStage.textContent = "Uploading evidence pack";
    if (progressMessage) progressMessage.textContent = "Sending the request to the local worker.";
    if (progressElapsed) progressElapsed.textContent = "0.0s";
    if (progressBar) progressBar.style.width = "3%";
    if (progressEvents) progressEvents.replaceChildren();

    try {
      const response = await fetch(apiUrl("/api/extractions"), {
        method: "POST",
        body: new FormData(form),
      });
      const payload = await response.json();
      if (!response.ok) {
        showProgressError(payload.errors?.[0] || "Extraction could not be started.");
        return;
      }
      pollExtraction(payload.status_url);
    } catch (_error) {
      showProgressError("The extraction request could not reach the local server.");
    }
  });
}
