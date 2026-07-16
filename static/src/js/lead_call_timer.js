/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

class LeadCallTimer extends Component {
    static template = "custom_leads_19.LeadCallTimer";
    static props    = ["action", "actionStack?"];

    setup() {
        const p = this.props.action.params || {};
        this.state = useState({
            seconds:        0,
            isRunning:      true,
            isSaving:       false,
            recState:       'idle',
            recordingSize:  0,
            logId:          null,
            leadName:       p.lead_name || "Lead",
            phone:          p.phone     || "",
            leadId:         p.lead_id,
        });

        this.orm           = useService("orm");
        this.actionService = useService("action");
        this._timerInterval = null;
        this._mediaRecorder = null;
        this._audioChunks   = [];
        this._logId         = null;

        onMounted(() => {
            // Open phone dialler
            if (this.state.phone) {
                window.open("tel:" + this.state.phone.replace(/\s/g, ""));
            }
            // Start stopwatch
            this._timerInterval = setInterval(() => {
                if (this.state.isRunning) this.state.seconds++;
            }, 1000);

            // Check recording capability
            const isHttps = location.protocol === 'https:'
                || location.hostname === 'localhost'
                || location.hostname === '127.0.0.1';

            if (!isHttps) {
                // HTTP on mobile blocks mediaDevices entirely
                this.state.recState = 'http_required';
            } else if (!navigator.mediaDevices || !window.MediaRecorder) {
                this.state.recState = 'unsupported';
            }
            // else: stays 'idle' → show Enable button
        });

        onWillUnmount(() => {
            clearInterval(this._timerInterval);
            this._stopRecorder();
        });
    }

    // ── Mic: user explicitly clicks Enable ────────────────────────────────
    async enableRecording() {
        if (this.state.recState !== 'idle') return;
        this.state.recState = 'requesting';
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mimeType = MediaRecorder.isTypeSupported('audio/webm')
                ? 'audio/webm'
                : MediaRecorder.isTypeSupported('audio/ogg')
                    ? 'audio/ogg'
                    : '';
            const opts = mimeType ? { mimeType } : {};
            this._mediaRecorder = new MediaRecorder(stream, opts);
            this._audioChunks   = [];
            this._mediaRecorder.ondataavailable = (e) => {
                if (e.data && e.data.size > 0) {
                    this._audioChunks.push(e.data);
                    this.state.recordingSize += e.data.size;
                }
            };
            this._mediaRecorder.start(1000);
            this.state.recState = 'recording';
        } catch (err) {
            this.state.recState = err.name === 'NotAllowedError' ? 'denied' : 'unsupported';
            console.warn("Mic access error:", err.message);
        }
    }

    _stopRecorder() {
        try {
            if (this._mediaRecorder && this._mediaRecorder.state !== 'inactive') {
                this._mediaRecorder.stop();
                this._mediaRecorder.stream.getTracks().forEach(t => t.stop());
            }
        } catch (e) { /* ignore */ }
    }

    // Upload in background — does NOT block endCall
    _uploadRecordingBackground(logId) {
        if (!logId || !this._audioChunks.length || this.state.recState !== 'recording') return;
        const chunks   = [...this._audioChunks];
        const mimeType = this._mediaRecorder?.mimeType || 'audio/webm';
        const ext      = mimeType.includes('ogg') ? 'ogg' : 'webm';
        const filename = `call_${logId}.${ext}`;
        const blob     = new Blob(chunks, { type: mimeType });

        const reader = new FileReader();
        reader.onloadend = async () => {
            try {
                const base64 = reader.result.split(',')[1];
                await this.orm.call('lead.call.log', 'action_save_recording',
                    [[logId], base64, filename, mimeType]);
                console.log("Recording uploaded OK:", filename);
            } catch (e) {
                console.error("Recording upload failed:", e);
            }
        };
        reader.readAsDataURL(blob);
    }

    // ── Display helpers ───────────────────────────────────────────────────
    get timeDisplay() {
        const m = Math.floor(this.state.seconds / 60);
        const s = this.state.seconds % 60;
        return `${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
    }

    get recSizeDisplay() {
        const kb = this.state.recordingSize / 1024;
        return kb > 1024 ? `${(kb/1024).toFixed(1)} MB` : `${kb.toFixed(0)} KB`;
    }

    // ── Open lead in new tab (timer keeps running) ────────────────────────
    openLeadNewTab() {
        const url = `/odoo/leads/${this.state.leadId}`;
        window.open(url, '_blank');
    }

    // ── Jump to call log on lead form ─────────────────────────────────────
    async viewCallLog() {
        this._closeOverlay();
        try {
            await this.actionService.doAction({
                type: 'ir.actions.act_window',
                res_model: 'leads.logic',
                res_id: this.state.leadId,
                view_mode: 'form',
                views: [[false, 'form']],
                target: 'main',
            });
        } catch (e) { /* ignore */ }
    }

    pauseResume() { this.state.isRunning = !this.state.isRunning; }

    _closeOverlay() {
        const el = document.querySelector(".o_lead_call_timer_backdrop");
        if (el) {
            el.style.transition = "opacity 0.2s ease";
            el.style.opacity    = "0";
            setTimeout(() => el.remove(), 220);
        }
    }

    async endCall() {
        if (this.state.isSaving) return;
        clearInterval(this._timerInterval);
        this.state.isRunning = false;
        this.state.isSaving  = true;

        // Stop recorder — don't await, just signal stop
        this._stopRecorder();

        // Save call duration
        try {
            this._logId = await this.orm.call(
                "leads.logic", "action_save_call_duration",
                [[this.state.leadId], this.state.seconds]
            );
            this.state.logId = this._logId;   // shows "Call log saved" banner
        } catch (e) {
            console.error("Error saving duration:", e);
        }

        // 2. Start recording upload in background (non-blocking)
        setTimeout(() => this._uploadRecordingBackground(this._logId), 300);

        // 3. Fetch wizard action
        let wizardAction = null;
        try {
            wizardAction = await this.orm.call(
                "leads.logic", "action_kanban_quick_response",
                [[this.state.leadId]]
            );
        } catch (e) {
            console.error("Error fetching wizard:", e);
        }

        // 4. Close DOM overlay
        this._closeOverlay();

        // 5. Navigate to lead form first — this exits the timer URL cleanly
        try {
            await this.actionService.doAction({
                type: 'ir.actions.act_window',
                res_model: 'leads.logic',
                res_id: this.state.leadId,
                view_mode: 'form',
                views: [[false, 'form']],
                target: 'main',
            });
        } catch (e) {
            console.error("Error navigating to lead:", e);
        }

        // 6. Open response wizard on top of lead form
        if (wizardAction) {
            setTimeout(async () => {
                try {
                    await this.actionService.doAction(wizardAction);
                } catch (e) {
                    console.error("Error opening wizard:", e);
                }
            }, 300);
        }
    }

    cancel() {
        clearInterval(this._timerInterval);
        this._stopRecorder();
        this._closeOverlay();
    }
}

registry.category("actions").add("lead_call_timer", LeadCallTimer);
