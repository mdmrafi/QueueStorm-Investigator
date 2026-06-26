/* ─── QueueStorm Investigator — frontend ──────────────────────────────────── */
(() => {
    'use strict';

    const API_PORT = (() => {
        // Allow runtime override via ?api_port=NNNN. Falls back to the build-time
        // replacement below (see index.html). Defaults to 8000 so the local dev
        // workflow keeps working unchanged.
        const params = new URLSearchParams(window.location.search);
        const qp = parseInt(params.get('api_port') || '', 10);
        if (Number.isFinite(qp) && qp > 0 && qp < 65536) return qp;
        const fromBuild = parseInt(window.__API_PORT__ || '', 10);
        if (Number.isFinite(fromBuild) && fromBuild > 0 && fromBuild < 65536) return fromBuild;
        return 8000;
    })();

    const API_BASE = (() => {
        // Allow override via ?api=http://host:port for prod. Default to the
        // current host with API_PORT so a same-host two-port dev setup works.
        const params = new URLSearchParams(window.location.search);
        const override = params.get('api');
        if (override) return override.replace(/\/+$/, '');
        return `${window.location.protocol}//${window.location.hostname}:${API_PORT}`;
    })();

    // ── Elements ────────────────────────────────────────────────────────────
    const els = {
        form:         document.getElementById('ticketForm'),
        ticket_id:    document.getElementById('ticket_id'),
        complaint:    document.getElementById('complaint'),
        language:     document.getElementById('language'),
        channel:      document.getElementById('channel'),
        user_type:    document.getElementById('user_type'),
        campaign:     document.getElementById('campaign_context'),
        txnContainer: document.getElementById('txnContainer'),
        metaContainer:document.getElementById('metaContainer'),
        addTxnBtn:    document.getElementById('addTxnBtn'),
        addMetaBtn:   document.getElementById('addMetaBtn'),
        submitBtn:    document.getElementById('submitBtn'),
        resetBtn:     document.getElementById('resetBtn'),
        samplePicker: document.getElementById('samplePicker'),
        verdictBody:  document.getElementById('verdictBody'),
        verdictMeta:  document.getElementById('verdictMeta'),
        toast:        document.getElementById('toast'),
    };

    // ── Toast ───────────────────────────────────────────────────────────────
    let toastTimer;
    function toast(msg, kind = 'error') {
        els.toast.textContent = msg;
        els.toast.className = `toast ${kind}`;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => els.toast.classList.add('hidden'), 5000);
    }

    // ── Transaction row builder ─────────────────────────────────────────────
    function addTxnRow(prefill = {}) {
        const row = document.createElement('div');
        row.className = 'txn-row';
        row.innerHTML = `
            <input type="text" placeholder="TXN-…" data-k="transaction_id" value="${escAttr(prefill.transaction_id)}">
            <input type="text" placeholder="2026-04-14T14:08:22Z" data-k="timestamp" value="${escAttr(prefill.timestamp)}">
            <select data-k="type">
                <option value="">type</option>
                ${['transfer','payment','cash_in','cash_out','settlement','refund']
                    .map(t => `<option value="${t}" ${prefill.type===t?'selected':''}>${t}</option>`).join('')}
            </select>
            <input type="number" placeholder="amount" data-k="amount" step="0.01" value="${escAttr(prefill.amount)}">
            <input type="text" placeholder="counterparty" data-k="counterparty" value="${escAttr(prefill.counterparty)}">
            <div style="display:flex;gap:.3rem;align-items:center;">
                <select data-k="status" style="flex:1;">
                    <option value="">status</option>
                    ${['completed','failed','pending','reversed']
                        .map(s => `<option value="${s}" ${prefill.status===s?'selected':''}>${s}</option>`).join('')}
                </select>
                <button type="button" class="remove-btn" title="Remove">×</button>
            </div>
        `;
        row.querySelector('.remove-btn').addEventListener('click', () => row.remove());
        els.txnContainer.appendChild(row);
    }

    function addMetaRow(prefill = {}) {
        const row = document.createElement('div');
        row.className = 'meta-row';
        row.innerHTML = `
            <input type="text" placeholder="key"   data-mk="k" value="${escAttr(prefill.k)}">
            <input type="text" placeholder="value" data-mk="v" value="${escAttr(prefill.v)}">
            <button type="button" class="remove-btn" title="Remove">×</button>
        `;
        row.querySelector('.remove-btn').addEventListener('click', () => row.remove());
        els.metaContainer.appendChild(row);
    }

    function escAttr(v) {
        if (v === undefined || v === null) return '';
        return String(v).replace(/[&<>"']/g, c => ({
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }[c]));
    }

    function readTransactions() {
        const rows = els.txnContainer.querySelectorAll('.txn-row');
        const out = [];
        for (const r of rows) {
            const obj = {};
            let hasAny = false;
            r.querySelectorAll('[data-k]').forEach(inp => {
                const k = inp.dataset.k;
                const v = inp.value.trim();
                if (v !== '') { obj[k] = k === 'amount' ? Number(v) : v; hasAny = true; }
            });
            // Require all txn fields to be non-empty
            const required = ['transaction_id','timestamp','type','amount','counterparty','status'];
            if (required.every(k => obj[k] !== undefined && obj[k] !== '')) {
                out.push(obj);
            } else if (hasAny) {
                toast('Transaction row is incomplete and was skipped', 'error');
            }
        }
        return out;
    }

    function readMetadata() {
        const rows = els.metaContainer.querySelectorAll('.meta-row');
        const out = {};
        for (const r of rows) {
            const k = r.querySelector('[data-mk="k"]').value.trim();
            const v = r.querySelector('[data-mk="v"]').value.trim();
            if (k) out[k] = v;
        }
        return Object.keys(out).length ? out : undefined;
    }

    // ── Sample case loader ──────────────────────────────────────────────────
    let sampleCases = [];
    async function loadSamples() {
        // Sample JSON lives at frontend/samples.json (a copy of the project-
        // root SUST_Preli_Sample_Cases.json) so the same-origin static server
        // can serve it without parent-directory traversal.
        const url = './samples.json';
        try {
            const r = await fetch(url);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data = await r.json();
            sampleCases = data.cases || [];
            for (const c of sampleCases) {
                const opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = `${c.id} — ${c.label}`;
                els.samplePicker.appendChild(opt);
            }
        } catch (e) {
            console.warn(`Could not load sample cases (${e.message}).`);
            els.samplePicker.innerHTML = '<option value="">— samples unavailable —</option>';
        }
    }

    function applySample(caseId) {
        const c = sampleCases.find(x => x.id === caseId);
        if (!c) return;
        const inp = c.input;
        els.ticket_id.value = inp.ticket_id || '';
        els.complaint.value = inp.complaint || '';
        els.language.value  = inp.language || '';
        els.channel.value   = inp.channel || '';
        els.user_type.value = inp.user_type || '';
        els.campaign.value  = inp.campaign_context || '';

        els.txnContainer.innerHTML = '';
        (inp.transaction_history || []).forEach(t => addTxnRow(t));

        els.metaContainer.innerHTML = '';
        if (inp.metadata) {
            for (const [k, v] of Object.entries(inp.metadata)) addMetaRow({ k, v });
        }

        els.verdictBody.className = 'verdict-body empty';
        els.verdictBody.innerHTML = '<p class="placeholder">Sample loaded — click <strong>Analyze ticket</strong> to see the verdict.</p>';
        els.verdictMeta.textContent = `Loaded: ${c.label}`;
    }

    // ── Verdict rendering ───────────────────────────────────────────────────
    function renderVerdict(resp, elapsedMs) {
        const sev   = (resp.severity || 'low').toLowerCase();
        const ver   = (resp.evidence_verdict || '').toLowerCase();
        const dept  = resp.department || '';
        const caseT = resp.case_type || '';
        const txn   = resp.relevant_transaction_id;
        const conf  = (resp.confidence !== undefined && resp.confidence !== null)
            ? `${(resp.confidence * 100).toFixed(0)}%` : '—';
        const codes = resp.reason_codes || [];

        els.verdictMeta.textContent = `ticket ${resp.ticket_id} · ${elapsedMs} ms`;
        els.verdictBody.className = 'verdict-body';
        els.verdictBody.innerHTML = `
            <div class="verdict-header">
                <h3>${escAttr(caseT.replace(/_/g,' '))}</h3>
                <div>
                    <span class="badge badge-severity-${sev}">${sev}</span>
                    <span class="badge badge-verdict-${ver}">${ver.replace('_',' ')}</span>
                </div>
            </div>

            <dl class="field-grid">
                <dt>Department</dt><dd><span class="badge badge-dept">${escAttr(dept)}</span></dd>
                <dt>Case type</dt><dd><span class="badge badge-case">${escAttr(caseT)}</span></dd>
                <dt>Relevant txn</dt><dd>${txn ? `<span class="txn-id">${escAttr(txn)}</span>` : '<em style="color:#64748b">none</em>'}</dd>
                <dt>Confidence</dt><dd>${conf}</dd>
                <dt>Human review</dt><dd>${resp.human_review_required
                    ? '<strong style="color:#fca5a5">required</strong>'
                    : '<strong style="color:#6ee7b7">not required</strong>'}</dd>
            </dl>

            <div class="section">
                <div class="section-label">Agent summary</div>
                <div class="section-text">${escAttr(resp.agent_summary || '')}</div>
            </div>

            <div class="section action">
                <div class="section-label">Recommended next action</div>
                <div class="section-text">${escAttr(resp.recommended_next_action || '')}</div>
            </div>

            <div class="section customer">
                <div class="section-label">Customer reply</div>
                <div class="section-text">${escAttr(resp.customer_reply || '')}</div>
            </div>

            ${codes.length ? `
                <div class="section">
                    <div class="section-label">Reason codes</div>
                    <div class="chips">${codes.map(c => `<span class="chip">${escAttr(c)}</span>`).join('')}</div>
                </div>` : ''}

            <div class="${resp.human_review_required ? 'flag' : 'flag safe'}">
                ${resp.human_review_required
                    ? '⚠ This ticket has been flagged for human review.'
                    : '✓ No human review required for this ticket.'}
            </div>
        `;
    }

    function renderError(status, body) {
        els.verdictBody.className = 'verdict-body';
        let details = '';
        if (typeof body === 'object' && body !== null) {
            details = JSON.stringify(body, null, 2);
        } else {
            details = String(body);
        }
        els.verdictBody.innerHTML = `
            <h3 style="color:#fca5a5">HTTP ${status}</h3>
            <div class="error-block">${escAttr(details)}</div>
        `;
        els.verdictMeta.textContent = `error · HTTP ${status}`;
    }

    // ── Submit ──────────────────────────────────────────────────────────────
    async function onSubmit(e) {
        e.preventDefault();

        const body = {
            ticket_id:           els.ticket_id.value.trim(),
            complaint:           els.complaint.value,
            language:            emptyToUndef(els.language.value),
            channel:             emptyToUndef(els.channel.value),
            user_type:           emptyToUndef(els.user_type.value),
            campaign_context:    emptyToUndef(els.campaign.value),
            transaction_history: readTransactions() || undefined,
            metadata:            readMetadata(),
        };
        // Strip undefined for cleanliness
        Object.keys(body).forEach(k => body[k] === undefined && delete body[k]);

        if (!body.ticket_id) return toast('ticket_id is required', 'error');
        if (!body.complaint.trim()) return toast('complaint must not be empty', 'error');

        els.submitBtn.disabled = true;
        els.submitBtn.textContent = 'Analyzing…';
        const t0 = performance.now();

        try {
            const r = await fetch(`${API_BASE}/analyze-ticket`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const elapsed = Math.round(performance.now() - t0);
            const text = await r.text();
            let parsed;
            try { parsed = JSON.parse(text); } catch { parsed = text; }

            if (r.ok) {
                renderVerdict(parsed, elapsed);
            } else {
                renderError(r.status, parsed);
                toast(`HTTP ${r.status} from server`, 'error');
            }
        } catch (err) {
            renderError(0, { error: String(err.message || err), hint: `Is the API running at ${API_BASE}?` });
            toast(`Network error: ${err.message || err}`, 'error');
        } finally {
            els.submitBtn.disabled = false;
            els.submitBtn.textContent = 'Analyze ticket';
        }
    }

    function emptyToUndef(v) { return v === '' || v === null ? undefined : v; }

    function onReset() {
        els.form.reset();
        els.txnContainer.innerHTML = '';
        els.metaContainer.innerHTML = '';
        els.verdictBody.className = 'verdict-body empty';
        els.verdictBody.innerHTML = '<p class="placeholder">Submit a ticket to see the structured verdict here.</p>';
        els.verdictMeta.textContent = '';
        els.samplePicker.value = '';
    }

    // ── Boot ────────────────────────────────────────────────────────────────
    function init() {
        loadSamples();
        els.form.addEventListener('submit', onSubmit);
        els.resetBtn.addEventListener('click', onReset);
        els.addTxnBtn.addEventListener('click', () => addTxnRow());
        els.addMetaBtn.addEventListener('click', () => addMetaRow());
        els.samplePicker.addEventListener('change', e => {
            if (e.target.value) applySample(e.target.value);
        });
    }

    document.addEventListener('DOMContentLoaded', init);
})();
