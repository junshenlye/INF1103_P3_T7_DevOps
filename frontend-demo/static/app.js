const dropZone = document.querySelector("#drop-zone");
const fileInput = document.querySelector("#source-files");
const fileList = document.querySelector("#file-list");
const form = document.querySelector("#assessment-form");

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

if (form) {
  form.addEventListener("submit", () => {
    const button = form.querySelector("button[type='submit']");
    if (!button) return;
    button.disabled = true;
    button.querySelector("span:first-child").textContent = "Extracting all events…";
  });
}
