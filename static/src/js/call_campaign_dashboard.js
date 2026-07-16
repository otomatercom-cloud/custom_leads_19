/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const QUALITY_OPTIONS = [
    { value: "hot",                 label: "🔥 Hot" },
    { value: "warm",                label: "🌞 Warm" },
    { value: "follow_up",           label: "⏰ Follow Up" },
    { value: "call_later",          label: "📞 Call Back" },
    { value: "first_attempt",       label: "🎯 First Attempt" },
    { value: "new",                 label: "🆕 New" },
    { value: "not_responding",      label: "🔕 Ringing Not Responding" },
    { value: "cold",                label: "❄️ Cold" },
    { value: "not_attended",        label: "📵Not Attended" },
    { value: "waiting_for_admission", label: "⏳ Waiting for Admission" },
];

const ALL_QUALITY_VALUES = QUALITY_OPTIONS.map(q => q.value);

class CallCampaignDashboard extends Component {
    static template = "custom_leads_19.CallCampaignDashboard";
    static props = ["*"];

    setup() {
        this.orm          = useService("orm");
        this.action       = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            campaigns: [],
            officerBreakdown: [],
            stats: { total: 0, running: 0, draft: 0, done: 0,
                     total_leads: 0, total_called: 0, total_pending: 0 },
            filter: "all",
            search: "",
            role: "officer",
            // Generate modal
            showGenerateModal: false,
            generating: false,
            generateResult: null,
            genType: "combined",          // combined | all_leads | quality | date
            genQualities: [...ALL_QUALITY_VALUES],  // selected qualities
            genSourceIds: [],            // selected source ids (empty = all sources)
            genDateFrom: new Date().toISOString().slice(0, 10),
            genDateTo:   new Date().toISOString().slice(0, 10),
            genMaxLeads: 50,
            genIncludeTL: true,
            genClearExisting: true,
            genAutoStart: true,
            // Member selection
            availableMembers: [],
            selectedMemberIds: [],   // empty = all
            membersLoading: false,
            // Source selection
            availableSources: [],
            sourcesLoading: false,
            // Other
            startingAll: false,
            mobileMenuOpen: false,
        });

        this.qualityOptions = QUALITY_OPTIONS;
        onWillStart(async () => await this.loadCampaigns());
    }

    async loadCampaigns() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "call.campaign", "get_campaign_dashboard_data", [], {}
            );
            this.state.campaigns        = data.campaigns;
            this.state.stats            = data.stats;
            this.state.role             = data.role;
            this.state.officerBreakdown = data.officer_breakdown || [];
        } catch(e) {
            this.notification.add("Error loading: " + e.message, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    // ── Filters ───────────────────────────────────────────────────────────
    get filteredCampaigns() {
        let list = this.state.campaigns;
        if (this.state.filter === "running") list = list.filter(c => c.state === "running");
        else if (this.state.filter === "draft") list = list.filter(c => c.state === "draft");
        else if (this.state.filter === "done")  list = list.filter(c => c.state === "done");
        else if (this.state.filter === "mine")  list = list.filter(c => c.is_mine);
        if (this.state.search) {
            const q = this.state.search.toLowerCase();
            list = list.filter(c =>
                c.name.toLowerCase().includes(q) ||
                (c.created_by || "").toLowerCase().includes(q)
            );
        }
        return list;
    }

    get isAdminRole() {
        return this.state.role === "manager" || this.state.role === "tl";
    }

    onSetFilter(f)     { return () => { this.state.filter = f; this.state.mobileMenuOpen = false; }; }
    onSearchInput(ev)  { this.state.search = ev.target.value; }
    toggleMobileMenu() { this.state.mobileMenuOpen = !this.state.mobileMenuOpen; }

    // ── Generate Modal ───────────────────────────────────────────────────
    async openGenerateModal() {
        this.state.generateResult    = null;
        this.state.genType           = "combined";
        this.state.genQualities      = [...ALL_QUALITY_VALUES];
        this.state.genSourceIds      = [];
        this.state.genMaxLeads       = 50;
        this.state.genIncludeTL      = true;
        this.state.genClearExisting  = true;
        this.state.genAutoStart      = true;
        this.state.selectedMemberIds = [];
        const today = new Date().toISOString().slice(0, 10);
        this.state.genDateFrom = today;
        this.state.genDateTo   = today;
        this.state.showGenerateModal = true;
        // Load selectable members
        this.state.membersLoading = true;
        try {
            const members = await this.orm.call(
                "call.campaign", "get_selectable_members", [], {}
            );
            this.state.availableMembers = members;
            // Pre-select all
            this.state.selectedMemberIds = members.map(m => m.id);
        } catch(e) {
            this.state.availableMembers = [];
        } finally {
            this.state.membersLoading = false;
        }
        // Load selectable sources (empty selection = no filter = all sources)
        this.state.sourcesLoading = true;
        try {
            const sources = await this.orm.call(
                "call.campaign", "get_selectable_sources", [], {}
            );
            this.state.availableSources = sources;
        } catch(e) {
            this.state.availableSources = [];
        } finally {
            this.state.sourcesLoading = false;
        }
    }
    closeGenerateModal() {
        this.state.showGenerateModal = false;
        this.state.generateResult    = null;
    }

    onGenTypeChange(ev)        { this.state.genType = ev.target.value; }

    toggleMember(id) {
        const idx = this.state.selectedMemberIds.indexOf(id);
        if (idx >= 0) this.state.selectedMemberIds.splice(idx, 1);
        else this.state.selectedMemberIds.push(id);
    }
    isMemberSelected(id)  { return this.state.selectedMemberIds.includes(id); }
    selectAllMembers()    { this.state.selectedMemberIds = this.state.availableMembers.map(m => m.id); }
    clearAllMembers()     { this.state.selectedMemberIds = []; }
    onGenMaxLeadsInput(ev)     { this.state.genMaxLeads = parseInt(ev.target.value) || 50; }
    onGenDateFromChange(ev)    { this.state.genDateFrom = ev.target.value; }
    onGenDateToChange(ev)      { this.state.genDateTo   = ev.target.value; }
    onGenIncludeTLChange(ev)   { this.state.genIncludeTL     = ev.target.checked; }
    onGenClearChange(ev)       { this.state.genClearExisting = ev.target.checked; }
    onGenAutoStartChange(ev)   { this.state.genAutoStart     = ev.target.checked; }

    toggleQuality(val) {
        const idx = this.state.genQualities.indexOf(val);
        if (idx >= 0) this.state.genQualities.splice(idx, 1);
        else this.state.genQualities.push(val);
    }
    isQualitySelected(val) { return this.state.genQualities.includes(val); }
    selectAllQualities()   { this.state.genQualities = [...ALL_QUALITY_VALUES]; }
    clearAllQualities()    { this.state.genQualities = []; }

    // Sources: empty array means "no filter" (all sources included)
    toggleSource(id) {
        const idx = this.state.genSourceIds.indexOf(id);
        if (idx >= 0) this.state.genSourceIds.splice(idx, 1);
        else this.state.genSourceIds.push(id);
    }
    isSourceSelected(id)  { return this.state.genSourceIds.includes(id); }
    selectAllSources()    { this.state.genSourceIds = this.state.availableSources.map(s => s.id); }
    clearAllSources()     { this.state.genSourceIds = []; }

    async confirmGenerate() {
        if (this.state.genType === "quality" && !this.state.genQualities.length) {
            this.notification.add("Select at least one quality.", { type: "warning" });
            return;
        }
        this.state.generating = true;
        try {
            const result = await this.orm.call(
                "call.campaign", "generate_smart_campaigns", [],
                {
                    options: {
                        campaign_type:        this.state.genType,
                        quality_filter:       this.state.genQualities,
                        source_ids:           this.state.genSourceIds,
                        date_from:            this.state.genDateFrom,
                        date_to:              this.state.genDateTo,
                        max_leads:            this.state.genMaxLeads,
                        include_tl:           this.state.genIncludeTL,
                        clear_existing:       this.state.genClearExisting,
                        auto_start:           this.state.genAutoStart,
                        selected_employee_ids: this.state.selectedMemberIds,
                    }
                }
            );
            this.state.generateResult = result;
            await this.loadCampaigns();
            this.notification.add(
                `✅ ${result.created} campaign(s) created` +
                (result.deleted ? `, ${result.deleted} old removed` : ""),
                { type: "success" }
            );
        } catch(e) {
            this.notification.add("Generate failed: " + e.message, { type: "danger" });
        } finally {
            this.state.generating = false;
        }
    }

    // ── Campaign actions ─────────────────────────────────────────────────
    async startSingle(campaignId) {
        try {
            await this.orm.call("call.campaign", "action_start_all_drafts", [],
                { campaign_ids: [campaignId] });
            this.notification.add("Campaign started!", { type: "success" });
            await this.loadCampaigns();
        } catch(e) {
            this.notification.add("Failed: " + e.message, { type: "danger" });
        }
    }

    async startAllDrafts() {
        const drafts = this.state.campaigns.filter(c => c.state === "draft");
        if (!drafts.length) { this.notification.add("No draft campaigns.", { type: "warning" }); return; }
        this.state.startingAll = true;
        try {
            const r = await this.orm.call("call.campaign", "action_start_all_drafts", [],
                { campaign_ids: drafts.map(c => c.id) });
            this.notification.add(`✅ ${r.started} campaign(s) started!`, { type: "success" });
            await this.loadCampaigns();
        } catch(e) {
            this.notification.add("Failed: " + e.message, { type: "danger" });
        } finally { this.state.startingAll = false; }
    }

    // ── Navigation ───────────────────────────────────────────────────────
    openRunner(campaignId, campaignName) {
        this.action.doAction({
            type: "ir.actions.client",
            tag: "call_campaign_runner",
            name: "📞 " + campaignName,
            params: { campaign_id: campaignId },
        });
    }
    openForm(campaignId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "call.campaign",
            res_id: campaignId,
            views: [[false, "form"]],
            target: "main",
        });
    }
    createNew() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "call.campaign",
            views: [[false, "form"]],
            target: "main",
        });
    }

    // ── Helpers ──────────────────────────────────────────────────────────
    progressPct(c) { return c.total ? Math.round((c.called / c.total) * 100) : 0; }
    overallPct()   { const s = this.state.stats; return s.total_leads ? Math.round((s.total_called / s.total_leads) * 100) : 0; }
    stateLabel(s)  { return { draft: "Draft", running: "Running", done: "Done", cancelled: "Cancelled" }[s] || s; }
    stateClass(s)  { return { draft: "o_cc_badge_draft", running: "o_cc_badge_running", done: "o_cc_badge_done", cancelled: "o_cc_badge_cancelled" }[s] || ""; }
}

registry.category("actions").add("call_campaign_dashboard", CallCampaignDashboard);
