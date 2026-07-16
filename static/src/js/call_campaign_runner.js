/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const QUALITY_LABELS = {
    new: "🆕 New", hot: "🔥 Hot", warm: "🌞 Warm", cold: "❄️ Cold",
    first_attempt: "🎯 First Attempt", waiting_for_admission: "⏳ Waiting for Admission",
    admission: "🎓 Admission", not_responding: "🔕 Ringing Not Responding",
    call_later: "📞 Call Back",
    follow_up: "⏰ Follow Up", not_reachable: "⏳ Busy",
    not_attended: "📵Not Attended",
    already_joined: "✅ Already Joined",
    wrong_number: "📵 Wrong number", not_interested: "❌ Not Interested",
};

const QUALITY_OPTIONS = Object.entries(QUALITY_LABELS).map(([v, l]) => ({ value: v, label: l }));

class CallCampaignRunner extends Component {
    static template = "custom_leads_19.CallCampaignRunner";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            campaignName: "",
            leads: [],
            currentIndex: 0,
            total: 0,
            calledCount: 0,
            // Response form state
            showResponseForm: false,
            callActive: false,
            selectedQuality: "",
            responseText: "",
            submitting: false,
            done: false,
            // Follow-up scheduling
            scheduleFollowup: false,
            followupDate: "",
            followupNotes: "",
            loadError: "",
            retrying: false,
        });
        // Idempotency key for the in-flight submission — stays the same
        // across retries of the SAME response so the server can dedupe,
        // regenerated only after a confirmed success or when moving to a
        // different lead.
        this.submissionUid = null;

        const params = this.props.action.params || {};
        let campaignId = params.campaign_id;
        if (!campaignId) {
            const match = window.location.pathname.match(/\/call\.campaign\/(\d+)\//);
            if (match) {
                campaignId = parseInt(match[1], 10);
            }
        }
        this.campaignId = campaignId;

        onWillStart(async () => {
            if (this.campaignId) {
                await this.loadLeads();
            } else {
                this.state.loading = false;
                this.state.done = false;
            }
        });
    }

    async loadLeads() {
        this.state.loading = true;
        this.state.loadError = "";
        try {
            await this._loadLeadsInner();
        } catch (err) {
            console.error("Campaign load failed", err);
            this.state.loading = false;
            this.state.loadError =
                "Couldn't load the campaign — the connection failed or was " +
                "interrupted. Check your network and tap Retry.";
        }
    }

    async _loadLeadsInner() {
        const data = await this.orm.call("call.campaign", "get_campaign_leads", [this.campaignId]);
        this.state.leads = data.leads;
        this.state.campaignName = data.campaign_name;
        this.state.total = data.total || 0;
        this.state.calledCount = data.called || 0;

        const firstPending = data.leads.findIndex(l => !l.called);
        this.state.currentIndex = firstPending >= 0 ? firstPending : 0;
        this.state.loading = false;
        this.state.showSidebar = false;
        this.state.done = data.leads.every(l => l.called);
    }

    get currentLead() {
        return this.state.leads[this.state.currentIndex] || null;
    }

    get progress() {
        if (!this.state.total) return 0;
        return Math.round((this.state.calledCount / this.state.total) * 100);
    }

    get qualityOptions() {
        return QUALITY_OPTIONS;
    }

    /** Returns a default datetime string for tomorrow same time (for followup picker) */
    _defaultFollowupDate() {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        // Format to YYYY-MM-DDTHH:MM for datetime-local input
        const pad = n => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    async onWhatsApp() {
        const lead = this.currentLead;
        if (!lead || !lead.phone) return;
        // Strip all non-digit chars (spaces, dashes, brackets, leading +)
        const num = lead.phone.replace(/[\s\-\(\)\+]/g, '');

        // --- Kodular / App Inventor style wrapper apps ---
        // Kodular's WebViewer component exposes a JS bridge called
        // "AppInventor" with a setWebViewString() method. Writing to it fires
        // the WebViewer1.WebViewStringChanged event in the Kodular app's
        // blocks, which can then use an Activity Starter component
        // (ACTION_VIEW on a wa.me URI) to launch WhatsApp natively — this
        // works because Activity Starter calls Android's startActivity()
        // directly and is NOT restricted by the WebView's URL scheme rules
        // the way in-page navigation (window.open/location.href/wa.me's own
        // internal whatsapp:// redirect) is. window.AppInventor is only
        // defined when running inside a Kodular/App Inventor WebViewer, so
        // this is a no-op in regular browsers or the Odoo mobile app.
        if (window.AppInventor && typeof window.AppInventor.setWebViewString === 'function') {
            window.AppInventor.setWebViewString('whatsapp:' + num);
        }

        // The Odoo mobile app renders this component inside its own embedded
        // WebView. That WebView can only navigate http(s):// URLs itself — it
        // does not forward custom schemes (whatsapp://, intent://, etc.) to
        // Android's app-launch system. wa.me's own internal script tries a
        // 'whatsapp://' handoff after loading, which is why it fails with
        // ERR_UNKNOWN_URL_SCHEME here, regardless of whether we open it via
        // window.open(), location.href, or ir.actions.act_url — none of
        // those can escape the WebView on this shell. So instead of trying
        // to auto-launch the app, copy the number and let the user open
        // WhatsApp themselves — this works everywhere, wrapper or not.
        try {
            await navigator.clipboard.writeText(num);
            this.notification.add(
                `📋 Number copied: ${num}. Open WhatsApp and paste it into a new chat.`,
                { type: "info", sticky: false }
            );
        } catch (err) {
            // Clipboard API may be blocked in some contexts; still attempt
            // the direct link as a best-effort fallback for browsers where
            // it does work (e.g. testing outside the mobile app wrapper).
            this.notification.add(
                `WhatsApp number: ${num}`,
                { type: "info", sticky: false }
            );
            window.open('https://wa.me/' + num, '_blank');
        }
    }

    onViewLead() {
        const lead = this.currentLead;
        if (!lead) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'leads.logic',
            res_id: lead.id,
            views: [[false, 'form']],
            target: 'new',   // opens in dialog so campaign stays open
        });
    }

    onClickCall() {
        const lead = this.currentLead;
        if (!lead) return;
        window.open("tel:" + lead.phone, "_blank");
        this.state.callActive = true;
        this.state.showResponseForm = true;
        // ── Auto-upgrade New → First Attempt when call starts ──
        this.state.selectedQuality = (lead.quality === "new") ? "first_attempt" : (lead.quality || "first_attempt");
        this.state.responseText = "";
        // Reset followup fields
        this.state.scheduleFollowup = false;
        this.state.followupDate = this._defaultFollowupDate();
        this.state.followupNotes = "";
    }

    onQualityChange(ev) {
        this.state.selectedQuality = ev.target.value;
    }

    onResponseInput(ev) {
        this.state.responseText = ev.target.value;
    }

    onToggleFollowup(ev) {
        this.state.scheduleFollowup = ev.target.checked;
    }

    onFollowupDateChange(ev) {
        this.state.followupDate = ev.target.value;
    }

    onFollowupNotesInput(ev) {
        this.state.followupNotes = ev.target.value;
    }

    async onSubmitResponse() {
        const lead = this.currentLead;
        if (!lead) return;

        // Validate followup date if scheduling
        if (this.state.scheduleFollowup && !this.state.followupDate) {
            this.notification.add("Please set a Follow-Up date before submitting.", { type: "warning" });
            return;
        }

        this.state.submitting = true;
        // One idempotency key per response — reused across every retry of
        // this same submission so a "request succeeded but reply was lost"
        // situation can never save the response twice on the server.
        if (!this.submissionUid || this.submissionUidLeadId !== lead.id) {
            this.submissionUid =
                (window.crypto && window.crypto.randomUUID)
                    ? window.crypto.randomUUID()
                    : "sub-" + Date.now() + "-" + Math.random().toString(36).slice(2);
            this.submissionUidLeadId = lead.id;
        }
        const args = [
            this.campaignId,
            lead.id,
            this.state.selectedQuality,
            this.state.responseText,
            this.state.scheduleFollowup ? this.state.followupDate : false,
            this.state.scheduleFollowup ? this.state.followupNotes : "",
            this.submissionUid,
        ];
        try {
            // Up to 3 attempts with short backoff — mobile networks drop
            // single requests all the time; a silent quick retry usually
            // saves the officer from ever seeing an error.
            let lastError = null;
            let ok = false;
            for (let attempt = 1; attempt <= 3 && !ok; attempt++) {
                try {
                    await this.orm.call("call.campaign", "submit_call_response", args);
                    ok = true;
                } catch (err) {
                    lastError = err;
                    if (attempt < 3) {
                        this.state.retrying = true;
                        await new Promise(r => setTimeout(r, attempt * 1500));
                    }
                }
            }
            this.state.retrying = false;
            if (!ok) {
                throw lastError;
            }
            this.submissionUid = null; // confirmed saved — next response gets a fresh key

            // Update local state
            this.state.leads[this.state.currentIndex].called = true;
            this.state.leads[this.state.currentIndex].quality = this.state.selectedQuality;
            this.state.leads[this.state.currentIndex].quality_label = QUALITY_LABELS[this.state.selectedQuality] || this.state.selectedQuality;
            this.state.leads[this.state.currentIndex].call_response = this.state.responseText;
            this.state.calledCount++;
            this.state.showResponseForm = false;
            this.state.callActive = false;
            this.state.scheduleFollowup = false;

            if (this.state.scheduleFollowup) {
                this.notification.add("📅 Follow-up scheduled!", { type: "success" });
            }

            // Advance to next uncalled lead
            const nextIndex = this.state.leads.findIndex(
                (l, i) => i > this.state.currentIndex && !l.called
            );
            if (nextIndex >= 0) {
                this.state.currentIndex = nextIndex;
            } else {
                const anyPending = this.state.leads.find(l => !l.called);
                if (!anyPending) {
                    this.state.done = true;
                    this.notification.add("🎉 Campaign completed! All leads called.", { type: "success" });
                }
            }
        } catch (e) {
            this.state.retrying = false;
            this.notification.add(
                "Couldn't save the response after 3 attempts — your notes are " +
                "still here. Check your network and press Submit again (it " +
                "will not be saved twice).",
                { type: "danger", sticky: true }
            );
        } finally {
            this.state.submitting = false;
        }
    }

    onSkip() {
        const nextIndex = this.state.leads.findIndex(
            (l, i) => i > this.state.currentIndex && !l.called
        );
        if (nextIndex >= 0) {
            this.state.currentIndex = nextIndex;
        }
        this.state.showResponseForm = false;
        this.state.callActive = false;
        this.state.scheduleFollowup = false;
    }

    onSelectLead(index) {
        this.state.currentIndex = index;
        this.state.showResponseForm = false;
        this.state.callActive = false;
        this.state.scheduleFollowup = false;
    }

    toggleSidebar() {
        this.state.showSidebar = !this.state.showSidebar;
    }

    onBackToCampaign() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "call.campaign",
            res_id: this.campaignId,
            views: [[false, "form"]],
            target: "main",
        });
    }
}

registry.category("actions").add("call_campaign_runner", CallCampaignRunner);
