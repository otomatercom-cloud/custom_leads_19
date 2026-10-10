/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const secs = (s) => {
    s = Math.round(s || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return h ? `${h}h ${pad(m)}m ${pad(x)}s` : m ? `${m}m ${pad(x)}s` : `${x}s`;
};
const hrs = (h) => {
    if (!h || h <= 0) return "0m";
    const m = Math.round(h * 60), d = Math.floor(m / 1440), hh = Math.floor((m % 1440) / 60), mm = m % 60;
    return d ? (hh ? `${d}d ${hh}h` : `${d}d`) : hh ? (mm ? `${hh}h ${mm}m` : `${hh}h`) : `${mm}m`;
};
const RANGES = {
    today: () => [new Date(), new Date()],
    d7: () => [new Date(Date.now() - 6 * 864e5), new Date()],
    d30: () => [new Date(Date.now() - 29 * 864e5), new Date()],
    month: () => { const n = new Date(); return [new Date(n.getFullYear(), n.getMonth(), 1), n]; },
    year: () => { const n = new Date(); return [new Date(n.getFullYear(), 0, 1), n]; },
};
const COLORS = ["#2f6f73", "#d98c2b", "#7a5195", "#c0504d", "#4f81bd"];

export class LeadReports extends Component {
    static template = "custom_leads_19.LeadReports";

    setup() {
        this.orm = useService("orm");
        const [a, b] = RANGES.d30();
        this.state = useState({
            catalog: [], opts: { sources: [], teams: [], owners: [], courses: [] },
            report: "intake_source", search: "", loading: false, error: "", data: null,
            f: { date_from: ymd(a), date_to: ymd(b), source: "", team: "", owner: "", course: "", group: "day" },
            range: "d30",
        });
        onWillStart(async () => {
            this.state.catalog = await this.orm.call("otm.lead.reports", "get_catalog", []);
            this.state.opts = await this.orm.call("otm.lead.reports", "get_options", []);
            await this.load();
        });
    }

    get groups() {
        const q = this.state.search.trim().toLowerCase();
        return this.state.catalog
            .map((g) => ({ group: g.group, reports: g.reports.filter((r) => !q || (r.title + r.desc).toLowerCase().includes(q)) }))
            .filter((g) => g.reports.length);
    }
    get desc() {
        for (const g of this.state.catalog) for (const r of g.reports) if (r.id === this.state.report) return r.desc;
        return "";
    }
    get isTrend() { return this.state.report === "intake_trend"; }

    async load() {
        this.state.loading = true;
        this.state.error = "";
        try {
            const f = {};
            for (const [k, v] of Object.entries(this.state.f)) if (v) f[k] = v;
            this.state.data = await this.orm.call("otm.lead.reports", "run", [this.state.report, f]);
        } catch (e) {
            this.state.error = (e.data && e.data.message) || "Could not load this report. Refresh and try again.";
            this.state.data = null;
        }
        this.state.loading = false;
    }
    pick(id) { this.state.report = id; this.load(); }
    setRange(k) {
        const [a, b] = RANGES[k]();
        this.state.range = k;
        this.state.f.date_from = ymd(a);
        this.state.f.date_to = ymd(b);
        this.load();
    }
    onFilter(key, ev) {
        this.state.f[key] = ev.target.value;
        if (key.startsWith("date")) this.state.range = "";
        this.load();
    }

    fmt(col, v) {
        if (v === null || v === undefined || v === false) return "";
        switch (col.type) {
            case "int": return Number(v).toLocaleString();
            case "num": return Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 });
            case "pct": return `${Number(v).toFixed(1)}%`;
            case "secs": return secs(v);
            case "hrs": return hrs(v);
            case "dt": return String(v).replace("T", " ").slice(0, 16);
            default: return String(v);
        }
    }
    heat(col, v) {
        if (!this.state.data || !this.state.data.heat || !col.key.startsWith("h") || !v) return "";
        const max = Math.max(1, ...this.state.data.rows.flatMap((r) => Object.entries(r).filter(([k]) => /^h\d+$/.test(k)).map(([, x]) => x)));
        return `background:rgba(47,111,115,${(0.12 + 0.75 * v / max).toFixed(2)});color:${v / max > 0.55 ? "#fff" : "inherit"}`;
    }

    // ── chart (grouped bars, or lines for trends) ──
    get chart() {
        const d = this.state.data;
        if (!d || !d.chart || !d.rows.length) return null;
        const rows = d.rows.slice(0, d.chart.kind === "line" ? 400 : 14);
        const ys = d.chart.ys;
        const W = 860, H = 240, L = 44, B = 56, T = 12, R = 8;
        const max = Math.max(1, ...rows.flatMap((r) => ys.map((y) => r[y.key] || 0)));
        const pw = W - L - R, ph = H - T - B, step = pw / rows.length;
        const items = [];
        const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => ({ y: T + ph - t * ph, label: Math.round(max * t * 10) / 10 }));
        const every = Math.ceil(rows.length / 14);
        const labels = rows.map((r, i) => ({ x: L + step * i + step / 2, text: String(r[d.chart.x]).slice(0, 14), show: i % every === 0 }));
        if (d.chart.kind === "line") {
            const lines = ys.map((y, k) => ({
                color: COLORS[k], points: rows.map((r, i) => `${(L + step * i + step / 2).toFixed(1)},${(T + ph - ((r[y.key] || 0) / max) * ph).toFixed(1)}`).join(" "),
            }));
            return { W, H, B, ticks, labels, lines, legend: ys.map((y, k) => ({ label: y.label, color: COLORS[k] })), L, T, ph, pw };
        }
        const bw = Math.max(3, (step * 0.7) / ys.length);
        rows.forEach((r, i) => ys.forEach((y, k) => {
            const h = ((r[y.key] || 0) / max) * ph;
            items.push({ x: L + step * i + step * 0.15 + bw * k, y: T + ph - h, w: bw, h, color: COLORS[k], tip: `${r[d.chart.x]} - ${y.label}: ${r[y.key] || 0}` });
        }));
        return { W, H, B, ticks, labels, bars: items, legend: ys.map((y, k) => ({ label: y.label, color: COLORS[k] })), L, T, ph, pw };
    }

    // ── export / print ──
    exportCsv() {
        const d = this.state.data;
        if (!d) return;
        const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
        const lines = [d.columns.map((c) => esc(c.label)).join(",")];
        for (const r of d.rows) lines.push(d.columns.map((c) => esc(this.fmt(c, r[c.key]))).join(","));
        if (d.totals && Object.keys(d.totals).length) {
            lines.push(d.columns.map((c, i) => esc(i === 0 ? "Total" : d.totals[c.key] !== undefined ? this.fmt(c, d.totals[c.key]) : "")).join(","));
        }
        const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${d.title.replace(/[^\w]+/g, "_")}_${this.state.f.date_from}_${this.state.f.date_to}.csv`;
        a.click();
        URL.revokeObjectURL(a.href);
    }
    print() { window.print(); }
}

registry.category("actions").add("custom_leads_19.lead_reports", LeadReports);
