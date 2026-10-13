/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const COLORS = {
    hot: "#d9480f", warm: "#e8890c", cold: "#1c7ed6", new: "#0ca6c9", first_attempt: "#4263eb",
    follow_up: "#7048e8", call_later: "#f08c00", waiting_for_admission: "#e67700", admission: "#2b8a3e",
    not_responding: "#868e96", not_reachable: "#868e96", bad_lead: "#868e96", may_be_later: "#f76707",
    crash_lead: "#e03131", not_interested: "#e03131", wrong_number: "#e03131", not_enquiry: "#e03131",
    joined_other_institute: "#868e96", logic_students: "#2f9e44", none: "#adb5bd",
};

export class BucketDashboard extends Component {
    static template = "custom_leads_19.BucketDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: "", date: ymd(new Date()), search: "", data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.data = await this.orm.call("leads.logic", "get_bucket_dashboard", [this.state.date]);
        } catch (e) {
            const msg = (e && e.data && e.data.message) || (e && e.message) || "";
            this.state.error = "Could not load the dashboard. " + String(msg).slice(0, 300);
        } finally {
            this.state.loading = false;
        }
    }

    onDate(ev) {
        if (ev.target.value) {
            this.state.date = ev.target.value;
            this.load();
        }
    }
    onSearch(ev) {
        this.state.search = ev.target.value;
    }
    shiftDay(n) {
        const d = new Date(this.state.date + "T00:00:00");
        d.setDate(d.getDate() + n);
        this.state.date = ymd(d);
        this.load();
    }

    get rows() {
        const q = (this.state.search || "").toLowerCase();
        const rows = (this.state.data && this.state.data.rows) || [];
        return q ? rows.filter((r) => (r.name || "").toLowerCase().includes(q)) : rows;
    }
    get totals() {
        const t = { bucket: 0, today: 0, today_lost: 0, y_new: 0, y_out: 0, y_in: 0, y_lost: 0, q: {} };
        for (const r of this.rows) {
            for (const k of ["bucket", "today", "today_lost", "y_new", "y_out", "y_in", "y_lost"]) {
                t[k] += r[k];
            }
            for (const [q, n] of Object.entries(r.today_q)) {
                t.q[q] = (t.q[q] || 0) + n;
            }
        }
        return t;
    }
    qualityChips(map) {
        const labels = (this.state.data && this.state.data.labels) || {};
        return Object.entries(map || {})
            .sort((a, b) => b[1] - a[1])
            .map(([k, n]) => ({
                key: k,
                n,
                label: (labels[k] || "No quality").replace(/^[^A-Za-z]+/, "").trim(),
                color: COLORS[k] || COLORS.none,
            }));
    }
    isLostKey(k) {
        return this.state.data.lost_qualities.includes(k);
    }

    openLeads(title, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "leads.logic",
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }
    openBucket(r, quality) {
        const dom = [["lead_owner", "=", r.id]];
        if (quality) {
            dom.push(["lead_quality", "=", quality === "none" ? false : quality]);
        }
        this.openLeads(r.name + " - bucket", dom);
    }
    openDay(r, which, quality) {
        const g = this.state.data.ranges;
        const [s, e] = which === "today" ? [g.t_s, g.t_e] : [g.y_s, g.y_e];
        const dom = [["lead_owner", "=", r.id], ["assigned_date", ">=", s], ["assigned_date", "<", e]];
        if (quality) {
            dom.push(["lead_quality", "=", quality === "none" ? false : quality]);
        }
        this.openLeads(r.name + (which === "today" ? " - today" : " - yesterday"), dom);
    }
}

registry.category("actions").add("custom_leads_19.bucket_dashboard", BucketDashboard);
