/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (d, n) => {
    const x = new Date(d.getTime());
    x.setDate(x.getDate() + n);
    return x;
};

export class MetaAdsDashboard extends Component {
    static template = "custom_leads_19.MetaAdsDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const today = new Date();
        this.state = useState({
            loading: true, syncing: false, error: "", data: null, search: "", sort: "leads", dir: -1,
            from: ymd(addDays(today, -6)), to: ymd(today), preset: "7",
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.data = await this.orm.call("leads.logic", "get_meta_dashboard", [this.state.from, this.state.to]);
            this.state.from = this.state.data.from;
            this.state.to = this.state.data.to;
        } catch (e) {
            const msg = (e && e.data && e.data.message) || (e && e.message) || "";
            this.state.error = "Could not load the dashboard. " + String(msg).slice(0, 300);
        } finally {
            this.state.loading = false;
        }
    }

    setPreset(p) {
        const today = new Date();
        this.state.preset = p;
        if (p === "0") {
            this.state.from = this.state.to = ymd(today);
        } else if (p === "1") {
            this.state.from = this.state.to = ymd(addDays(today, -1));
        } else if (p === "month") {
            this.state.from = ymd(new Date(today.getFullYear(), today.getMonth(), 1));
            this.state.to = ymd(today);
        } else {
            this.state.from = ymd(addDays(today, -(parseInt(p, 10) - 1)));
            this.state.to = ymd(today);
        }
        this.load();
    }
    onDate(which, ev) {
        if (ev.target.value) {
            this.state[which] = ev.target.value;
            this.state.preset = "";
            this.load();
        }
    }
    onSearch(ev) {
        this.state.search = ev.target.value;
    }
    setSort(k) {
        if (this.state.sort === k) {
            this.state.dir = -this.state.dir;
        } else {
            this.state.sort = k;
            this.state.dir = -1;
        }
    }

    async sync() {
        this.state.syncing = true;
        try {
            const days = Math.max(1, Math.round((new Date(this.state.to) - new Date(this.state.from)) / 86400000) + 1);
            const n = await this.orm.call("otm.meta.spend", "sync_meta_ads", [days]);
            this.notification.add(`${n} day/campaign rows updated from Meta.`, { type: "success" });
            await this.load();
        } catch (e) {
            const msg = (e && e.data && e.data.message) || (e && e.message) || "Sync failed";
            this.notification.add(String(msg).slice(0, 400), { type: "danger", sticky: true });
        } finally {
            this.state.syncing = false;
        }
    }

    get rows() {
        const d = this.state.data;
        if (!d) {
            return [];
        }
        const q = this.state.search.trim().toLowerCase();
        const k = this.state.sort;
        const val = (r) => (r[k] === null || r[k] === undefined ? -1 : r[k]);
        return d.rows
            .filter((r) => !q || r.name.toLowerCase().includes(q))
            .sort((a, b) => (k === "name" ? a.name.localeCompare(b.name) * -this.state.dir : (val(a) - val(b)) * this.state.dir));
    }
    get maxLeads() {
        return Math.max(1, ...(this.state.data ? this.state.data.daily_leads : [1]));
    }
    get showDayNotes() {
        return this.state.data && this.state.data.days.length <= 14;
    }
    barH(n) {
        return Math.round((n / this.maxLeads) * 100);
    }
    dayCpl(i) {
        const d = this.state.data;
        return d.daily_leads[i] && d.daily_spend[i] ? d.daily_spend[i] / d.daily_leads[i] : null;
    }
    dayLabel(s) {
        return `${s.slice(8, 10)}/${s.slice(5, 7)}`;
    }
    cellStyle(n, max) {
        if (!n) {
            return "";
        }
        const a = 0.12 + 0.55 * Math.min(1, n / Math.max(1, max));
        return `background: rgba(28,126,214,${a.toFixed(2)})`;
    }
    rowMax(r) {
        return Math.max(1, ...r.daily);
    }
    money(v) {
        return v === null || v === undefined ? "-" : "₹" + Math.round(v).toLocaleString("en-IN");
    }
    money2(v) {
        return v === null || v === undefined ? "-" : "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 });
    }
    num(v) {
        return v === null || v === undefined ? "-" : Number(v).toLocaleString("en-IN");
    }
    pct(v) {
        return v === null || v === undefined ? "-" : v + "%";
    }

    openLeads(r, dayIdx) {
        const d = this.state.data;
        const domain = [["leads_source.name", "ilike", "meta"]];
        if (dayIdx === undefined) {
            domain.push(["create_date", ">=", d.range.s], ["create_date", "<", d.range.e]);
        } else {
            // one day: shift the UTC range of the whole period by whole days from the start
            const s = new Date(d.range.s.replace(" ", "T") + "Z");
            const from = new Date(s.getTime() + dayIdx * 86400000);
            const to = new Date(from.getTime() + 86400000);
            const f = (x) => x.toISOString().slice(0, 19).replace("T", " ");
            domain.push(["create_date", ">=", f(from)], ["create_date", "<", f(to)]);
        }
        if (r) {
            if (r.name === "(no campaign)") {
                domain.push(["source_campaign_id", "=", false]);
            } else {
                domain.push(["source_campaign_id.name", "=", r.name]);
            }
        }
        this.action.doAction({
            type: "ir.actions.act_window", name: r ? r.name : "Meta leads", res_model: "leads.logic",
            views: [[false, "list"], [false, "form"]], domain, target: "current",
        });
    }
}

registry.category("actions").add("custom_leads_19.meta_ads_dashboard", MetaAdsDashboard);
