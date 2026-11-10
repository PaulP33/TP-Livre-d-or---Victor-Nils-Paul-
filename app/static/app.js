// compteur de caracteres
const content = document.getElementById("content");
const count = document.getElementById("count");
content.addEventListener("input", () => {
    count.textContent = content.value.length;
});

// apercu de la photo avant envoi
const photo = document.getElementById("photo");
const preview = document.getElementById("preview");
const dropzone = document.getElementById("dropzone");
const dropzoneText = document.getElementById("dropzone-text");
const removeBtn = document.getElementById("remove-photo");

function showPreview() {
    const file = photo.files[0];
    if (!file) {
        preview.removeAttribute("src");
        dropzone.classList.remove("has-photo");
        removeBtn.hidden = true;
        return;
    }
    preview.src = URL.createObjectURL(file);
    dropzone.classList.add("has-photo");
    removeBtn.hidden = false;
}

photo.addEventListener("change", showPreview);
removeBtn.addEventListener("click", () => {
    photo.value = "";
    showPreview();
});

["dragenter", "dragover"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
        e.preventDefault();
        dropzone.classList.add("dragging");
    })
);
["dragleave", "drop"].forEach((ev) =>
    dropzone.addEventListener(ev, () => dropzone.classList.remove("dragging"))
);
dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) {
        photo.files = e.dataTransfer.files;
        showPreview();
    }
});

// visionneuse
const lightbox = document.getElementById("lightbox");
const lightboxImg = document.getElementById("lightbox-img");
const lightboxCaption = document.getElementById("lightbox-caption");

document.querySelectorAll("[data-src]").forEach((el) =>
    el.addEventListener("click", () => {
        lightboxImg.src = el.dataset.src;
        lightboxCaption.textContent = el.dataset.caption;
        lightbox.hidden = false;
        document.body.style.overflow = "hidden";
    })
);

function closeLightbox() {
    lightbox.hidden = true;
    document.body.style.overflow = "";
}

lightbox.addEventListener("click", (e) => {
    if (e.target !== lightboxImg) closeLightbox();
});
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeLightbox();
});

// apparition des blocs au scroll
const observer = new IntersectionObserver(
    (entries) =>
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("visible");
                observer.unobserve(entry.target);
            }
        }),
    { threshold: 0.1 }
);
document.querySelectorAll(".reveal").forEach((el) => observer.observe(el));

// les chiffres des stats montent de 0 a leur valeur
document.querySelectorAll("[data-count]").forEach((el) => {
    const target = parseInt(el.dataset.count, 10);
    if (!target) return;
    let current = 0;
    const step = Math.max(1, Math.ceil(target / 40));
    const timer = setInterval(() => {
        current = Math.min(current + step, target);
        el.textContent = current;
        if (current === target) clearInterval(timer);
    }, 30);
});
