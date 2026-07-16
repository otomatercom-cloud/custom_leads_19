/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { Component, onWillStart, useState } from "@odoo/owl";

const STAGES = [
    { key: "funnel",         label: "Funnel",     caption: "Fresh leads entering the pipeline",    icon: "fa-filter",         accent: "funnel"    },
    { key: "prospects",      label: "Prospects",  caption: "Qualified leads ready for counselling", icon: "fa-user",           accent: "prospect"  },
    { key: "rnr_dnp",        label: "RNR / DNP",  caption: "Ringing, not reachable, did not pick", icon: "fa-phone",          accent: "rnr"       },
    { key: "admission_done", label: "Admissions", caption: "Converted — admission completed",       icon: "fa-graduation-cap", accent: "admission" },
    { key: "re_try",         label: "Re-Try",     caption: "Leads being followed up again",         icon: "fa-refresh",        accent: "retry"     },
    { key: "alumni",         label: "Alumni",     caption: "Past students and alumni",              icon: "fa-star",           accent: "alumni"    },
    { key: "junk",           label: "Junk",       caption: "Invalid or irrelevant leads",           icon: "fa-trash",          accent: "junk"      },
];

const QUALITY_LABELS = {
    new: "🆕 New", hot: "🔥 Hot", warm: "🌞 Warm", cold: "❄️ Cold",
    first_attempt: "🎯 First Attempt", waiting_for_admission: "⏳ Waiting for Admission",
    admission: "🎓 Admission", not_responding: "🔕 Ringing Not Responding",
    call_later: "📞 Call Back",
    follow_up: "⏰ Follow Up", not_reachable: "⏳ Busy",
    not_attended: "📵Not Attended",
    already_joined: "✅ Already Joined",
    wrong_number: "📵 Wrong number",
    not_interested: "❌ Not Interested",
};

const MEDAL = ["🥇", "🥈", "🥉"];

export class LeadStageDashboard extends Component {
    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.state  = useState({
            counts:        {},
            total:         0,
            loading:       true,
            canSeeTeams:   false,
            isManager:     false,
            teamData:      [],
            officerData:   [],
            myQuality:     {},
            myDaywise:     [],
            officerPeriod: "month",
            myTab:         "quality",    // quality | processed | chart
        });
        onWillStart(() => this.loadData());
    }

    get stages()  { return STAGES; }
    get medals()  { return MEDAL; }

    getCount(k)  { return this.state.counts[k] || 0; }
    getPct(k)    { return this.state.total ? Math.round(this.getCount(k) / this.state.total * 100) : 0; }

    get myQualityList() {
        return Object.entries(this.state.myQuality)
            .filter(([,v]) => v > 0)
            .sort((a,b) => b[1]-a[1])
            .map(([k,v]) => ({ key: k, label: QUALITY_LABELS[k] || k, count: v }));
    }

    get myTotalLeads() {
        return Object.values(this.state.myQuality).reduce((s,v)=>s+v, 0);
    }

    get sortedOfficers() {
        const p = "adm_" + this.state.officerPeriod;
        return [...this.state.officerData].sort((a,b) => b[p]-a[p]);
    }

    teamOfficersSorted(team) {
        const p = "adm_" + this.state.officerPeriod;
        return [...(team.officers||[])].sort((a,b)=>b[p]-a[p]);
    }

    officerAdm(o)  { return o["adm_"  + this.state.officerPeriod] || 0; }
    officerProc(o) { return o["proc_" + this.state.officerPeriod] || 0; }

    // Day-wise chart data — last 30 days, fill missing days with 0
    get chartData() {
        const map = {};
        for (const d of this.state.myDaywise) map[d.date] = d.count;
        const result = [];
        const today = new Date();
        for (let i = 29; i >= 0; i--) {
            const d = new Date(today);
            d.setDate(today.getDate() - i);
            const key = d.toISOString().slice(0,10);
            result.push({ date: key, label: key.slice(5), count: map[key] || 0 });
        }
        return result;
    }

    get chartMax() {
        return Math.max(1, ...this.chartData.map(d => d.count));
    }

    // ── Single RPC ───────────────────────────────────────────────────────
    async loadData() {
        this.state.loading = true;
        try {
            const d = await this.orm.call("leads.logic", "get_dashboard_data", []);
            this.state.counts      = d.stage_counts     || {};
            this.state.total       = Object.values(this.state.counts).reduce((s,v)=>s+v, 0);
            this.state.canSeeTeams = d.can_see_teams    || false;
            this.state.isManager   = d.is_manager       || false;
            this.state.teamData    = d.team_data        || [];
            this.state.officerData = d.officer_data     || [];
            this.state.myQuality   = d.my_quality_counts|| {};
            this.state.myDaywise   = d.my_daywise       || [];
        } finally {
            this.state.loading = false;
        }
    }

    setPeriod(p)  { this.state.officerPeriod = p; }
    setMyTab(t)   { this.state.myTab = t; }

    openStage(key) {
        const s = STAGES.find(x=>x.key===key);
        this.action.doAction({
            type:"ir.actions.act_window", name: s?s.label:"Leads",
            res_model:"leads.logic",
            views:[[false,"kanban"],[false,"list"],[false,"form"]],
            domain:[["lead_stage_category","=",key]], target:"current",
        });
    }

    openQualityLeads(qualityKey) {
        this.action.doAction({
            type:"ir.actions.act_window", name: QUALITY_LABELS[qualityKey]||qualityKey,
            res_model:"leads.logic",
            views:[[false,"list"],[false,"form"]],
            domain:[["lead_quality","=",qualityKey],["lead_owner.user_id","=",user.userId]],
            target:"current",
        });
    }

    openTeamLeads(teamId, stageKey) {
        const domain = [["team_id","=",teamId]];
        if (stageKey) domain.push(["lead_stage_category","=",stageKey]);
        this.action.doAction({
            type:"ir.actions.act_window", name:"Team Leads",
            res_model:"leads.logic",
            views:[[false,"list"],[false,"form"]],
            domain, target:"current",
        });
    }

    openOfficerLeads(empId, period) {
        const domain = [["lead_owner","=",empId],["lead_stage_category","=","admission_done"]];
        const today = new Date();
        if (period==="today") {
            const d = today.toISOString().slice(0,10);
            domain.push(["admission_date",">=",d]);
        } else if (period==="week") {
            const mon = new Date(today);
            mon.setDate(today.getDate()-today.getDay()+1);
            domain.push(["admission_date",">=",mon.toISOString().slice(0,10)]);
        } else if (period==="month") {
            const m = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,"0")}-01`;
            domain.push(["admission_date",">=",m]);
        }
        this.action.doAction({
            type:"ir.actions.act_window", name:"Officer Admissions",
            res_model:"leads.logic",
            views:[[false,"list"],[false,"form"]],
            domain, target:"current",
        });
    }

    async loadDailyCampaign() {
        this.state.campaignLoading = true;
        try {
            const data = await this.orm.call(
                "call.campaign", "get_dashboard_campaign_info", [], {}
            );
            this.state.role = data.role || 'officer';
            this.state.campaign = data.own_campaign || null;
            this.state.teamSummary = data.team_summary || null;
            if (!data.own_campaign) {
                this.state.campaignError = "No campaign available.";
            }
        } catch (e) {
            this.state.campaignError = "Could not load daily campaign.";
        } finally {
            this.state.campaignLoading = false;
        }
    }

    async generateTeamCampaigns() {
        this.state.generatingTeam = true;
        try {
            const tl_id = this.state.teamSummary && this.state.teamSummary.tl_employee_id;
            const result = await this.orm.call(
                "call.campaign", "generate_team_campaigns",
                [tl_id || false], {}
            );
            this.notification.add(
                `✅ Done! ${result.created} new campaigns created, ${result.existing} already existed for ${result.total} officers.`,
                { type: "success", sticky: false }
            );
            // Reload team summary
            await this.loadDailyCampaign();
        } catch(e) {
            this.notification.add("Error generating campaigns: " + e.message, { type: "danger" });
        } finally {
            this.state.generatingTeam = false;
        }
    }

    openOfficerCampaign(campaignId) {
        this.action.doAction({
            type: "ir.actions.client",
            tag: "call_campaign_runner",
            name: "📞 Campaign",
            params: { campaign_id: campaignId },
        });
    }

    startDailyCampaign() {
        const c = this.state.campaign;
        if (!c) return;
        this.action.doAction({
            type: "ir.actions.client",
            tag: "call_campaign_runner",
            name: "📞 " + c.campaign_name,
            params: { campaign_id: c.campaign_id },
        });
    }

    openAnalysis() {
        this.action.doAction("custom_leads_19.action_lead_stage_analysis");
    }

    async openCampaigns() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Call Campaigns",
            res_model: "call.campaign",
            views: [[false, "list"], [false, "form"]],
            target: "main",
        });
    }
}

LeadStageDashboard.template = "custom_leads_19.LeadStageDashboard";
registry.category("actions").add("custom_leads_19.lead_stage_dashboard", LeadStageDashboard);
