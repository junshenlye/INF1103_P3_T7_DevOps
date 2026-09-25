const form = document.querySelector("#assessment-form");
const moduleList = document.querySelector("#module-list");
const moduleTemplate = document.querySelector("#module-template");
const addModuleButton = document.querySelector("#add-module");
const moduleCount = document.querySelector("#module-count");
const progressPanel = document.querySelector("#extraction-progress");
const progressStage = document.querySelector("#progress-stage");
const progressElapsed = document.querySelector("#progress-elapsed");
const progressMessage = document.querySelector("#progress-message");
const apiBaseUrl = document.body.dataset.apiBase || window.location.origin;

function apiUrl(path) {
  return path.startsWith("http") ? path : `${apiBaseUrl}${path}`;
}

function renumberModules() {
  const entries = Array.from(moduleList.querySelectorAll(".module-entry"));
  entries.forEach((entry, index) => {
    entry.querySelector("[data-module-number]").textContent = index + 1;
    entry.querySelectorAll("[data-field]").forEach((field) => {
      field.name = `${field.dataset.field}_${index}`;
      if (field.dataset.field === "source_files") {
        field.id = `source-files-${index}`;
      }
    });
    entry.querySelector("[data-remove-module]").hidden = entries.length === 1;
  });
  moduleCount.value = entries.length;
}

function addModule() {
  moduleList.appendChild(moduleTemplate.content.cloneNode(true));
  renumberModules();
}

function renderFiles(zone) {
  const input = zone.querySelector("input[type='file']");
  const list = zone.querySelector(".file-list");
  list.replaceChildren();
  Array.from(input.files).forEach((file) => {
    const item = document.createElement("div");
    item.className = "file-pill";
    item.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
    list.appendChild(item);
  });
}

addModuleButton?.addEventListener("click", addModule);
moduleList?.addEventListener("click", (event) => {
  const remove = event.target.closest("[data-remove-module]");
  if (remove && moduleList.children.length > 1) {
    remove.closest(".module-entry").remove();
    renumberModules();
    return;
  }
});

moduleList?.addEventListener("change", (event) => {
  if (event.target.matches("input[type='file']")) renderFiles(event.target.closest("[data-drop-zone]"));
});

moduleList?.addEventListener("keydown", (event) => {
  const zone = event.target.closest("[data-drop-zone]");
  if (
    zone &&
    !event.target.matches("input[type='file']") &&
    (event.key === "Enter" || event.key === " ")
  ) {
    event.preventDefault();
    zone.querySelector("input[type='file']").click();
  }
});

["dragenter", "dragover", "dragleave", "drop"].forEach((name) => {
  moduleList?.addEventListener(name, (event) => {
    const zone = event.target.closest("[data-drop-zone]");
    if (!zone) return;
    event.preventDefault();
    zone.classList.toggle("is-dragging", name === "dragenter" || name === "dragover");
    if (name === "drop" && event.dataTransfer?.files.length) {
      const input = zone.querySelector("input[type='file']");
      try {
        const transfer = new DataTransfer();
        Array.from(event.dataTransfer.files).forEach((file) => transfer.items.add(file));
        input.files = transfer.files;
      } catch (_error) {
        input.files = event.dataTransfer.files;
      }
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
});

function resetSubmitButton() {
  const button = form?.querySelector("button[type='submit']");
  if (!button) return;
  button.disabled = false;
  button.querySelector("span:first-child").textContent = "Build pacing timeline";
}

function showProgressError(message) {
  progressPanel.hidden = false;
  progressPanel.classList.add("is-failed");
  progressStage.textContent = "Timeline could not be built";
  progressMessage.textContent = message;
  resetSubmitButton();
}

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  renumberModules();
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  button.querySelector("span:first-child").textContent = "Building timeline…";
  progressPanel.hidden = false;
  progressPanel.classList.remove("is-failed");
  progressStage.textContent = "Interpreting assessment evidence";
  progressMessage.textContent = "Modules are being mapped onto the trimester.";
  const startedAt = Date.now();
  const timer = window.setInterval(() => {
    progressElapsed.textContent = `${((Date.now() - startedAt) / 1000).toFixed(1)}s`;
  }, 200);
  try {
    const response = await fetch(apiUrl("/api/extractions"), { method: "POST", body: new FormData(form) });
    const payload = await response.json();
    window.clearInterval(timer);
    if (!response.ok) {
      showProgressError(payload.errors?.[0] || "The pacing timeline could not be created.");
      return;
    }
    window.location.assign("/");
  } catch (_error) {
    window.clearInterval(timer);
    showProgressError("The request could not reach the local server.");
  }
});

if (moduleList && moduleTemplate) addModule();
