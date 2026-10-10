/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** 25m, 3h 10m, 2d 5h  (24h or more shows as days) */
export function fmtHrs(h) {
    if (!h || h <= 0) {
        return "0m";
    }
    const mins = Math.round(h * 60);
    const d = Math.floor(mins / 1440);
    const hh = Math.floor((mins % 1440) / 60);
    const m = mins % 60;
    if (d) {
        return hh ? `${d}d ${hh}h` : `${d}d`;
    }
    if (hh) {
        return m ? `${hh}h ${m}m` : `${hh}h`;
    }
    return `${m}m`;
}

const RANGES = {
    today: () => [new Date(), new Date()],
    d7: () => [new Date(Date.now() - 6 * 864e5), new Date()],
    d30: () => [new Date(Date.now() - 29 * 864e5), new Date()],
    month: () => {
        const n = new Date();
        return [new Date(n.getFullYear(), n.getMonth(), 1), n];
    },
    year: () => {
        const n = new Date();
        return [new Date(n.getFullYear(), 0, 1), n];
    },
};

export class ResponseDashboard extends Component {
    static template = "custom_leads_19.ResponseDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        const [a, b] = RANGES.d30();
        this.state = useState({
            loading: true,
            error: "",
            range: "d30",
            dateFrom: ymd(a),
            dateTo: ymd(b),
            group: "day",
            source: "",
            team: "",
            owner: "",
            tab: "owner",
            options: { sources: [], teams: [], owners: [] },
            data: null,
        });
        this.fmt = fmtHrs;
        onWillStart(async () => {
            try {
                this.state.options = await this.orm.call("leads.logic", "get_response_dashboard_options", []);
            } catch (e) {
                console.error(e);
            }
            await this.load();
        });
    }

    async load() {
        this.state.loading = true;
        this.state.error = "";
        try {
            const s = this.state;
            s.data = await this.orm.call("leads.logic", "get_response_dashboard", [
                s.dateFrom,
                s.dateTo,
                s.source ? parseInt(s.source) : false,
                s.team ? parseInt(s.team) : false,
                s.owner ? parseInt(s.owner) : false,
                s.group,
            ]);
        } catch (e) {
            console.error("Response dashboard failed", e);
            this.state.error = "Could not load the dashboard. Refresh and try again.";
        } finally {
            this.state.loading = false;
        }
    }

    setRange(key) {
        const [a, b] = RANGES[key]();
        Object.assign(this.state, { range: key, dateFrom: ymd(a), dateTo: ymd(b) });
        this.load();
    }
    setGroup(g) {
        this.state.group = g;
        this.load();
    }
    onDate(field, ev) {
        this.state[field] = ev.target.value;
        this.state.range = "";
        if (this.state.dateFrom && this.state.dateTo) {
            this.load();
        }
    }
    onFilter(field, ev) {
        this.state[field] = ev.target.value;
        this.load();
    }
    resetFilters() {
        Object.assign(this.state, { source: "", team: "", owner: "" });
        this.load();
    }
    setTab(t) {
        this.state.tab = t;
    }

    get rows() {
        const d = this.state.data;
        if (!d) {
            return [];
        }
        return { owner: d.by_owner, team: d.by_team, source: d.by_source }[this.state.tab] || [];
    }
    get tabTitle() {
        return { owner: "Admission officer", team: "Team", source: "Lead source" }[this.state.tab];
    }
    get maxDelay() {
        return Math.max(1, ...this.rows.map((r) => Math.max(r.assign, r.call)));
    }
    pct(v, max) {
        return Math.max(2, Math.round((v / (max || 1)) * 100)) + "%";
    }

    // ── SVG trend chart ──────────────────────────────────────────────
    get chart() {
        const t = (this.state.data && this.state.data.trend) || [];
        const W = 760, H = 250, L = 46, R = 14, T = 14, B = 34;
        const iw = W - L - R, ih = H - T - B;
        const maxY = Math.max(1, ...t.map((p) => Math.max(p.assign, p.call)));
        const maxL = Math.max(1, ...t.map((p) => p.leads));
        const n = t.length;
        const x = (i) => L + (n <= 1 ? iw / 2 : (iw * i) / (n - 1));
        const y = (v) => T + ih - (ih * v) / maxY;
        const line = (key) => t.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");
        const bw = Math.max(3, Math.min(26, (iw / Math.max(n, 1)) * 0.55));
        const step = Math.max(1, Math.ceil(n / 12));
        return {
            W, H, L, R, T, B, ih, iw,
            assignPath: line("assign"),
            callPath: line("call"),
            bars: t.map((p, i) => ({
                x: x(i) - bw / 2,
                w: bw,
                y: T + ih - (ih * 0.32 * p.leads) / maxL,
                h: (ih * 0.32 * p.leads) / maxL,
                leads: p.leads,
                label: p.label,
            })),
            pts: t.map((p, i) => ({
                x: x(i), ya: y(p.assign), yc: y(p.call), label: p.label,
                tip: `${p.label}: ${p.leads} leads | assign ${fmtHrs(p.assign)} | call ${fmtHrs(p.call)}`,
                showLabel: i % step === 0,
            })),
            grid: [0, 0.25, 0.5, 0.75, 1].map((f) => ({ y: T + ih - ih * f, text: fmtHrs(maxY * f) })),
        };
    }
}

registry.category("actions").add("custom_leads_19.response_dashboard", ResponseDashboard);
