
        // --- Tab Switching ---
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(tab.dataset.tab).classList.add('active');
            });
        });

        // --- File Upload (multi-file) ---
        const uploadZone = document.getElementById('upload-zone');
        const fileInput = document.getElementById('file-input');
        const fileList = document.getElementById('file-list');
        const uploadBtn = document.getElementById('upload-btn');
        const uploadContent = document.getElementById('upload-content');

        // Accumulated files (DataTransfer lets us build a custom FileList)
        let selectedFiles = new DataTransfer();

        uploadZone.addEventListener('click', (e) => {
            if (e.target.closest('.file-remove-btn')) return;
            fileInput.click();
        });

        uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadZone.classList.add('drag-over');
        });
        uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));

        uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadZone.classList.remove('drag-over');
            const files = e.dataTransfer.files;
            for (const f of files) {
                if (f.type === 'application/pdf') selectedFiles.items.add(f);
            }
            fileInput.files = selectedFiles.files;
            renderFileList();
        });

        fileInput.addEventListener('change', () => {
            for (const f of fileInput.files) {
                selectedFiles.items.add(f);
            }
            fileInput.files = selectedFiles.files;
            renderFileList();
        });

        function renderFileList() {
            const files = selectedFiles.files;
            if (files.length === 0) {
                fileList.style.display = 'none';
                uploadContent.style.display = 'flex';
                uploadBtn.disabled = true;
                uploadBtn.textContent = 'Upload & Track';
                return;
            }
            fileList.innerHTML = '';
            for (let i = 0; i < files.length; i++) {
                const item = document.createElement('div');
                item.className = 'file-preview';
                item.innerHTML = `
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                    <span class="file-name">${files[i].name}</span>
                    <button type="button" class="file-remove-btn" data-index="${i}">×</button>
                `;
                fileList.appendChild(item);
            }
            fileList.style.display = 'flex';
            uploadContent.style.display = 'none';
            uploadBtn.disabled = false;
            uploadBtn.textContent = files.length === 1 ? 'Upload & Track' : `Upload ${files.length} Files & Track`;
        }

        fileList.addEventListener('click', (e) => {
            const btn = e.target.closest('.file-remove-btn');
            if (!btn) return;
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            const newDT = new DataTransfer();
            for (let i = 0; i < selectedFiles.files.length; i++) {
                if (i !== idx) newDT.items.add(selectedFiles.files[i]);
            }
            selectedFiles = newDT;
            fileInput.files = selectedFiles.files;
            renderFileList();
        });
        // --- Completed Flights Toggle (smooth CSS animation) ---
        function toggleCompleted() {
            const body = document.getElementById('completed-body');
            const text = document.getElementById('toggle-text');
            const chevron = document.getElementById('toggle-chevron');
            const isExpanded = body.classList.contains('expanded');
            body.classList.toggle('expanded');
            chevron.style.transform = isExpanded ? '' : 'rotate(180deg)';
            text.textContent = isExpanded ? 'Show {{ completed|length }}' : 'Hide';
        }

        // --- Show/hide First Name field for VietJet ---
        const airlineRadios = document.querySelectorAll('input[name="airline"]');
        const firstnameGroup = document.getElementById('firstname-group');
        const firstnameInput = document.getElementById('firstname');
        function toggleFirstname() {
            const selected = document.querySelector('input[name="airline"]:checked');
            const isVietjet = selected && selected.value === 'vietjet';
            firstnameGroup.style.display = isVietjet ? '' : 'none';
            firstnameInput.required = isVietjet;
        }
        airlineRadios.forEach(r => r.addEventListener('change', toggleFirstname));
        toggleFirstname();

        // --- Loading Overlay with Timer ---
        document.getElementById('manual-form').addEventListener('submit', () => {
            document.getElementById('loading-overlay').style.display = 'flex';
            let seconds = 0;
            const timerEl = document.getElementById('loading-timer');
            setInterval(() => {
                seconds++;
                timerEl.textContent = seconds + 's';
                if (seconds === 30) {
                    document.querySelector('.loading-hint').textContent = 'Still working — airline sites can be slow...';
                }
            }, 1000);
        });

        // --- Detail Row Toggle (Desktop) ---
        function toggleDetail(id) {
            const row = document.getElementById(id);
            if (row) row.classList.toggle('show');
        }

        // --- Sortable Table ---
        let currentSortCol = -1;
        let currentSortDir = 'asc';

        function sortTable(colIndex) {
            const table = document.getElementById('bookings-table');
            const tbody = table.querySelector('tbody');
            const headers = table.querySelectorAll('th.sortable');

            // Toggle direction
            if (currentSortCol === colIndex) {
                currentSortDir = currentSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                currentSortDir = 'asc';
                currentSortCol = colIndex;
            }

            // Update header arrows
            headers.forEach(h => {
                h.classList.remove('sort-asc', 'sort-desc');
                const label = h.querySelector('.sort-label');
                if (label) label.textContent = '↕';
            });
            headers[colIndex].classList.add('sort-' + currentSortDir);
            const activeLabel = headers[colIndex].querySelector('.sort-label');
            if (activeLabel) activeLabel.textContent = currentSortDir === 'asc' ? '▲' : '▼';

            // Collect booking rows with their detail rows
            const rowGroups = [];
            const rows = Array.from(tbody.children);
            for (let i = 0; i < rows.length; i++) {
                const row = rows[i];
                if (row.classList.contains('booking-row')) {
                    const group = { main: row, detail: null };
                    // Check if next row is a detail row
                    if (i + 1 < rows.length && rows[i + 1].classList.contains('status-detail-row')) {
                        group.detail = rows[i + 1];
                        i++; // skip detail row
                    }
                    const cell = row.children[colIndex + 1]; // +1 for checkbox column
                    group.key = cell ? (cell.getAttribute('data-sort-key') || cell.textContent.trim()) : '';
                    rowGroups.push(group);
                }
            }

            // Sort
            rowGroups.sort((a, b) => {
                let va = a.key.toLowerCase();
                let vb = b.key.toLowerCase();
                // Try numeric comparison for dates/times
                if (va && vb && !isNaN(Date.parse(va)) && !isNaN(Date.parse(vb))) {
                    return currentSortDir === 'asc'
                        ? new Date(va) - new Date(vb)
                        : new Date(vb) - new Date(va);
                }
                if (va < vb) return currentSortDir === 'asc' ? -1 : 1;
                if (va > vb) return currentSortDir === 'asc' ? 1 : -1;
                return 0;
            });

            // Re-append in order
            rowGroups.forEach(g => {
                tbody.appendChild(g.main);
                if (g.detail) tbody.appendChild(g.detail);
            });
        }

        function confirmCheckAll() {
            const count = 0;
            const overlay = document.createElement('div');
            overlay.className = 'confirm-overlay';
            overlay.innerHTML = `
                <div class="confirm-card">
                    <h3>Check All ${count} PNRs?</h3>
                    <p>This will scrape all airline websites and may take a few minutes.</p>
                    <div class="confirm-actions">
                        <button class="btn-ghost" onclick="this.closest('.confirm-overlay').remove()">Cancel</button>
                        <button class="btn btn-primary" onclick="document.getElementById('check-all-form').submit(); this.closest('.confirm-overlay').remove(); setTimeout(startCheckPolling, 1000);">Check All</button>
                    </div>
                </div>
            `;
            document.body.appendChild(overlay);
            overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
        }

        // --- Auto-dismiss flash with smooth slide-out ---
        setTimeout(() => {
            document.querySelectorAll('.flash').forEach(el => {
                el.classList.add('flash-exit');
                setTimeout(() => el.remove(), 400);
            });
        }, 6000);

        // --- Scroll to bookings on success flash ---
        if (document.querySelector('.flash-success')) {
            setTimeout(() => {
                const section = document.getElementById('bookings-section');
                if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 300);
        }
        // --- Stop check via AJAX (no page reload) ---
        function stopCheckNow() {
            fetch(""dummy_url"", { method: 'POST' })
            .then(() => {
                document.getElementById('stop-btn-text').innerText = 'Stopping...';
            });
        }

        // --- Checklist Logic ---
        function toggleAllCheckboxes(masterCheckbox) {
            const checkboxes = document.querySelectorAll('.booking-checkbox');
            checkboxes.forEach(cb => {
                cb.checked = masterCheckbox.checked;
            });
            updateCheckSelectedBtn();
        }

        function updateCheckSelectedBtn() {
            const checkedCount = document.querySelectorAll('.booking-checkbox:checked').length;
            const btn = document.getElementById('check-selected-btn');
            if (checkedCount > 0) {
                btn.disabled = false;
                btn.querySelector('span').innerText = `Check Selected (${checkedCount})`;
            } else {
                btn.disabled = true;
                btn.querySelector('span').innerText = `Check Selected`;
                document.getElementById('select-all-bookings').checked = false;
            }
        }

        function checkSelectedPnrs() {
            const checkboxes = document.querySelectorAll('.booking-checkbox:checked');
            if (checkboxes.length === 0) return;
            
            const bookingIds = Array.from(checkboxes).map(cb => cb.value);
            
            // Create a form and submit it dynamically
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = ""dummy_url"";
            
            bookingIds.forEach(id => {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'booking_ids';
                input.value = id;
                form.appendChild(input);
            });
            
            document.body.appendChild(form);
            
            // Show loading state
            document.getElementById('check-selected-btn').classList.add('is-loading');
            
            form.submit();
        }

        // --- Helper: format relative time like the Jinja filter ---
        function timeAgo(dateStr) {
            if (!dateStr) return 'Not yet';
            const dt = new Date(dateStr.replace(' ', 'T'));
            const now = new Date();
            const diffMs = now - dt;
            const diffSec = diffMs / 1000;
            if (diffSec < 60) return 'Just now';
            if (diffSec < 3600) return Math.floor(diffSec / 60) + 'm ago';
            if (diffSec < 86400 && dt.toDateString() === now.toDateString()) {
                return 'Today, ' + dt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
            }
            const yesterday = new Date(now);
            yesterday.setDate(yesterday.getDate() - 1);
            if (dt.toDateString() === yesterday.toDateString()) {
                return 'Yesterday, ' + dt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
            }
            return dt.toLocaleDateString('en-US', { day: 'numeric', month: 'short' }) + ', ' +
                   dt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
        }

        // --- Live-update booking rows from API data ---
        let lastCheckedCount = 0;
        async function refreshBookingRows() {
            try {
                const res = await fetch('"dummy_url"');
                const bookings = await res.json();
                bookings.forEach(b => {
                    // Update desktop table rows
                    const row = document.querySelector(`tr[data-booking-id="${b.id}"]`);
                    if (row) {
                        // Status badge
                        const statusCell = row.querySelector('.status-badge');
                        if (statusCell) {
                            const statusClass = 'status-' + b.status.toLowerCase().replace(/ /g, '-');
                            statusCell.className = 'status-badge ' + statusClass;
                            statusCell.textContent = b.status;
                        }
                        // Last checked
                        const metaCell = row.querySelector('.meta-cell');
                        if (metaCell) {
                            metaCell.textContent = timeAgo(b.last_checked);
                            metaCell.setAttribute('data-sort-key', b.last_checked);
                        }
                    }
                    // Update mobile cards
                    const card = document.querySelector(`div.flight-card[data-booking-id="${b.id}"]`);
                    if (card) {
                        const statusBadge = card.querySelector('.status-badge');
                        if (statusBadge) {
                            const statusClass = 'status-' + b.status.toLowerCase().replace(/ /g, '-');
                            statusBadge.className = 'status-badge ' + statusClass;
                            statusBadge.textContent = b.status;
                        }
                        // Update border class
                        card.className = card.className.replace(/status-border-[\w-]+/g, '');
                        card.classList.add('flight-card', 'status-border-' + b.status.toLowerCase().replace(/ /g, '-'));
                        // Last checked
                        const checkedEl = card.querySelector('.meta-muted');
                        if (checkedEl) checkedEl.textContent = timeAgo(b.last_checked);
                    }
                });
            } catch (e) {
                console.error('Booking refresh error:', e);
            }
        }

        // --- Check progress polling ---
        let checkPolling = null;
        function startCheckPolling() {
            const bar = document.getElementById('check-progress-bar');
            const stopForm = document.getElementById('stop-check-form');
            const checkForm = document.getElementById('check-all-form');
            const countEl = document.getElementById('check-progress-count');

            checkPolling = setInterval(async () => {
                try {
                    const res = await fetch('"dummy_url"');
                    const data = await res.json();

                    if (data.running && !data.stop_requested) {
                        // Show stop, hide check
                        if (stopForm) stopForm.style.display = '';
                        if (checkForm) checkForm.style.display = 'none';
                        if (bar) {
                            bar.style.display = '';
                            const pct = data.total > 0 ? (data.checked / data.total) * 100 : 0;
                            bar.style.width = pct + '%';
                        }
                        if (countEl) countEl.textContent = data.checked + '/' + data.total;

                        // Live-update rows whenever a new PNR was checked
                        if (data.checked > lastCheckedCount) {
                            lastCheckedCount = data.checked;
                            refreshBookingRows();
                        }
                    } else {
                        // Done or stopped — show check, hide stop, do a final refresh
                        clearInterval(checkPolling);
                        if (bar) { bar.style.width = data.stop_requested ? '' : '100%'; }
                        // Final refresh of booking data, then reload for clean state
                        await refreshBookingRows();
                        setTimeout(() => window.location.reload(), 800);
                    }
                } catch (e) {
                    console.error('Poll error:', e);
                }
            }, 2000);
        }

        // Start polling if a check is running
        
        startCheckPolling();
        

    