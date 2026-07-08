// Job polling: when the page loads with a non-terminal job, poll
// GET /jobs/{id} every 2s until state hits done/failed. On terminal
// state, fetch the rendered HTML fragment from /app/jobs/{id}/partial
// and swap it into #result-region — preserves scroll, no page reload.

(function () {
    'use strict';
    // --- Shareable link: populate with current URL, wire copy button ---
    const shareInput = document.getElementById('share-url');
    const copyBtn = document.getElementById('share-copy');
    if (shareInput && copyBtn) {
        shareInput.value = window.location.href;
        copyBtn.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(shareInput.value);
                const original = copyBtn.textContent;
                copyBtn.textContent = 'Copied';
                copyBtn.classList.add('share-link-button-copied');
                setTimeout(() => {
                    copyBtn.textContent = original;
                    copyBtn.classList.remove('share-link-button-copied');
                }, 1500);
            } catch (err) {
                // Fallback for browsers without clipboard API (rare on http localhost)
                shareInput.select();
                document.execCommand('copy');
            }
        });
    }
    const POLL_INTERVAL_MS = 2000;
    const region = document.getElementById('result-region');
    if (!region) return;

    // Terminal state = server already rendered the full result;
    // no polling needed.
    if (region.dataset.isTerminal === 'true') return;

    const jobId = region.dataset.jobId;
    const startTime = Date.now();
    const elapsedEl = document.getElementById('live-elapsed');
    const stateEl = document.getElementById('live-state');

    // Elapsed counter ticks independently of poll cadence so it
    // reads live even between polls.
    const tickElapsed = () => {
        if (!elapsedEl) return;
        const seconds = Math.floor((Date.now() - startTime) / 1000);
        elapsedEl.textContent = `${seconds}s`;
    };
    tickElapsed();
    const elapsedTimer = setInterval(tickElapsed, 1000);

    // Poll loop.
    async function poll() {
        try {
            const resp = await fetch(`/jobs/${jobId}`);
            if (!resp.ok) {
                // Job disappeared (TTL expired, or server restart).
                // Stop polling and show a soft error.
                clearInterval(elapsedTimer);
                showPollError(`Server returned ${resp.status}. The job may have expired.`);
                return;
            }
            const data = await resp.json();

            if (stateEl && data.state && data.state !== stateEl.dataset.state) {
                stateEl.textContent = data.state;
                stateEl.dataset.state = data.state;
            }

            if (data.state === 'done' || data.state === 'failed') {
                clearInterval(elapsedTimer);
                await swapInPartial();
                return;
            }
        } catch (err) {
            // Network hiccup — keep polling. Only give up on
            // 4xx/5xx statuses handled above.
            console.warn('Poll error, retrying:', err);
        }
        setTimeout(poll, POLL_INTERVAL_MS);
    }

    async function swapInPartial() {
            try {
                const resp = await fetch(`/app/jobs/${jobId}/partial`);
                if (!resp.ok) {
                    showPollError(`Failed to load result (status ${resp.status}).`);
                    document.title = 'Analysis failed — Golf Swing Diagnostic';
                    return;
                }
                const html = await resp.text();
                region.innerHTML = html;
                region.dataset.isTerminal = 'true';

                // Update tab title to reflect the terminal state. The server
                // baked in "Analyzing…" when the page first loaded; without
                // this, the tab stays wrong forever after the swap.
                const finalState = region.querySelector('.result-failed') ? 'failed' : 'done';
                document.title = finalState === 'failed'
                    ? 'Analysis failed — Golf Swing Diagnostic'
                    : 'Diagnosis — Golf Swing Diagnostic';

                // Small nudge so the reader lands at the top of the
                // fresh content rather than mid-page.
                region.scrollIntoView({ behavior: 'smooth', block: 'start' });
            } catch (err) {
                showPollError(`Failed to load result: ${err.message}`);
                document.title = 'Analysis failed — Golf Swing Diagnostic';
            }
        }

    function showPollError(msg) {
        region.innerHTML = `
            <section class="result-failed">
                <h2>Something went wrong while polling</h2>
                <p class="result-failed-message">${escapeHtml(msg)}</p>
                <p class="result-failed-next">
                    <a href="/app">Start a new analysis</a>.
                </p>
            </section>
        `;
    }

    function escapeHtml(s) {
        const div = document.createElement('div');
        div.textContent = s;
        return div.innerHTML;
    }

    // Kick it off.
    setTimeout(poll, POLL_INTERVAL_MS);
})();