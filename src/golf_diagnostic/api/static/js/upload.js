// Upload flow: validate client-side, POST multipart/form-data to
// /analyze, receive job_id, navigate to /app/jobs/{id}.
//
// All hard validation is server-side; client-side checks are
// convenience only (fast feedback for size/extension issues before
// the upload burns bytes).

(function () {
    'use strict';

    const MAX_VIDEOS = 5;
    const MAX_FILE_BYTES = 100 * 1024 * 1024;
    const MAX_TOTAL_BYTES = 500 * 1024 * 1024;
    const ALLOWED_EXTS = new Set(['.mov', '.mp4', '.m4v']);

    const selectedFiles = [];

    const form = document.getElementById('upload-form');
    const symptomSel = document.getElementById('symptom');
    const handednessInputs = document.querySelectorAll('input[name="handedness"]');
    const lhCaveat = document.getElementById('lh-caveat');
    const videoInput = document.getElementById('videos');
    const fileList = document.getElementById('file-list');
    const fileSummary = document.getElementById('file-summary');
    const contextInput = document.getElementById('user_context');
    const contextCount = document.getElementById('context-count');
    const submitBtn = document.getElementById('submit-btn');
    const status = document.getElementById('upload-status');

    // --- Handedness caveat toggle ---
    handednessInputs.forEach((input) => {
        input.addEventListener('change', () => {
            const isLeft = document.querySelector('input[name="handedness"]:checked').value === 'left';
            lhCaveat.hidden = !isLeft;
        });
    });

    // --- Context character counter ---
    const updateContextCount = () => {
        contextCount.textContent = contextInput.value.length;
    };
    contextInput.addEventListener('input', updateContextCount);
    updateContextCount();

    // --- File selection preview ---
    const bytesToMB = (bytes) => (bytes / (1024 * 1024)).toFixed(1);
    const extOf = (name) => {
        const idx = name.lastIndexOf('.');
        return idx >= 0 ? name.slice(idx).toLowerCase() : '';
    };

    videoInput.addEventListener('change', () => {
    const picked = Array.from(videoInput.files || []);
    picked.forEach((f) => {
        // Dedupe by name+size — re-picking the same file is a no-op.
        const dup = selectedFiles.some(
            (sf) => sf.name === f.name && sf.size === f.size
        );
        if (!dup) selectedFiles.push(f);
    });
    // Reset the input so re-picking the same file still fires 'change'.
    videoInput.value = '';
    renderFileList();
});

function renderFileList() {
    fileList.innerHTML = '';

    if (selectedFiles.length === 0) {
        fileList.hidden = true;
        fileSummary.textContent = '';
        return;
    }

    let totalBytes = 0;
    const problems = [];

    selectedFiles.forEach((f, idx) => {
        const li = document.createElement('li');
        const ext = extOf(f.name);
        const sizeOK = f.size <= MAX_FILE_BYTES;
        const extOK = ALLOWED_EXTS.has(ext);
        totalBytes += f.size;

        const label = document.createElement('span');
        label.textContent = `${f.name} — ${bytesToMB(f.size)} MB`;

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'file-remove';
        removeBtn.textContent = '×';
        removeBtn.setAttribute('aria-label', `Remove ${f.name}`);
        removeBtn.addEventListener('click', () => {
            selectedFiles.splice(idx, 1);
            renderFileList();
        });

        if (!sizeOK) {
            li.classList.add('file-problem');
            label.textContent += ` (over ${MAX_FILE_BYTES / (1024 * 1024)} MB limit)`;
            problems.push(`${f.name} exceeds per-file size limit`);
        }
        if (!extOK) {
            li.classList.add('file-problem');
            label.textContent += ` (unsupported type)`;
            problems.push(`${f.name} is not a supported video type`);
        }

        li.appendChild(label);
        li.appendChild(removeBtn);
        fileList.appendChild(li);
    });

    fileList.hidden = false;

    const parts = [
        `${selectedFiles.length} file${selectedFiles.length === 1 ? '' : 's'} selected — ${bytesToMB(totalBytes)} MB total`,
    ];
    if (selectedFiles.length > MAX_VIDEOS) {
        parts.push(`(over ${MAX_VIDEOS}-file limit)`);
        problems.push(`too many files (${selectedFiles.length} > ${MAX_VIDEOS})`);
    }
    if (totalBytes > MAX_TOTAL_BYTES) {
        parts.push(`(over ${MAX_TOTAL_BYTES / (1024 * 1024)} MB total limit)`);
        problems.push(`total size exceeds limit`);
    }
    fileSummary.textContent = parts.join(' ');
    fileSummary.className = problems.length > 0 ? 'field-hint field-hint-error' : 'field-hint';
}

    // --- Submit ---
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // Basic client-side sanity check — the server does the real
        // validation, this is just to catch obvious mistakes early.
        const files = selectedFiles;
        if (files.length === 0) {
            showStatus('Please select at least one video.', 'error');
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Uploading…';
        showStatus('Uploading videos…', 'info');

        const formData = new FormData();

        // Symptom: only include when non-empty. Missing field on the
        // server side routes to general mode.
        const symptom = symptomSel.value;
        if (symptom) {
            formData.append('symptom', symptom);
        }

        const handedness = document.querySelector('input[name="handedness"]:checked').value;
        formData.append('handedness', handedness);

        const userContext = contextInput.value.trim();
        if (userContext) {
            formData.append('user_context', userContext);
        }

        files.forEach((f) => formData.append('videos', f));

        try {
            const resp = await fetch('/analyze', {
                method: 'POST',
                body: formData,
            });
            const data = await resp.json();

            if (!resp.ok) {
                const detail = Array.isArray(data.detail)
                    ? data.detail.join(' · ')
                    : (data.detail || 'Upload failed.');
                showStatus(detail, 'error');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Analyze my swing';
                return;
            }

            showStatus('Upload complete — analyzing now.', 'info');
            window.location.href = `/app/jobs/${data.job_id}`;
        } catch (err) {
            showStatus(`Network error: ${err.message}`, 'error');
            submitBtn.disabled = false;
            submitBtn.textContent = 'Analyze my swing';
        }
    });

    function showStatus(msg, kind) {
        status.textContent = msg;
        status.className = `upload-status upload-status-${kind}`;
        status.hidden = false;
    }
})();