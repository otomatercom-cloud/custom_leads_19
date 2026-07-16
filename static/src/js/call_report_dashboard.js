/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

function localDateStr(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
}

export class CallReportDashboard extends Component {
    static template = "custom_leads_19.CallReportDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const today = localDateStr(new Date());
        this.state = useState({
            loading: true,
            dateFrom: today,
            dateTo: today,
            activeRange: "today",
            data: null,
            error: "",
        });
        onWillStart(() => this.loadData());
    }

    // ── data ────────────────────────────────────────────────────────
    async loadData() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.data = await this.orm.call(
                "lead.call.log",
                "get_call_report",
                [this.state.dateFrom, this.state.dateTo]
            );
            // Sync back normalized dates from server
            this.state.dateFrom = this.state.data.date_from;
            this.state.dateTo = this.state.data.date_to;
        } catch (e) {
            console.error("Call report load failed", e);
            this.state.error = "Failed to load call report. Please refresh.";
        } finally {
            this.state.loading = false;
        }
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        this.state.activeRange = "";
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        this.state.activeRange = "";
    }

    applyFilter() {
        if (!this.state.dateFrom || !this.state.dateTo) {
            return;
        }
        this.loadData();
    }

    setQuickRange(range) {
        const now = new Date();
        let from = new Date(now);
        let to = new Date(now);
        if (range === "yesterday") {
            from.setDate(now.getDate() - 1);
            to.setDate(now.getDate() - 1);
        } else if (range === "week") {
            from.setDate(now.getDate() - 6);
        } else if (range === "month") {
            from = new Date(now.getFullYear(), now.getMonth(), 1);
        }
        this.state.dateFrom = localDateStr(from);
        this.state.dateTo = localDateStr(to);
        this.state.activeRange = range;
        this.loadData();
    }

    // ── computed ────────────────────────────────────────────────────
    get summary() {
        return (this.state.data && this.state.data.summary) || {};
    }

    get teams() {
        return (this.state.data && this.state.data.teams) || [];
    }

    get others() {
        return (this.state.data && this.state.data.others) || [];
    }

    get hasRows() {
        return this.teams.length > 0 || this.others.length > 0;
    }

    connectRate(row) {
        return row.calls
            ? Math.round((row.connected / row.calls) * 100)
            : 0;
    }

    // ── actions ─────────────────────────────────────────────────────
    exportExcel() {
        const url =
            "/custom_leads/call_report/export?date_from=" +
            encodeURIComponent(this.state.dateFrom) +
            "&date_to=" +
            encodeURIComponent(this.state.dateTo);
        window.open(url, "_blank");
    }

    openUserCalls(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Calls — ${row.name}`,
            res_model: "lead.call.log",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [
                ["user_id", "=", row.user_id],
                ["call_time", ">=", `${this.state.dateFrom} 00:00:00`],
                ["call_time", "<=", `${this.state.dateTo} 23:59:59`],
            ],
            target: "current",
        });
    }

    openAllCalls() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Call Logs",
            res_model: "lead.call.log",
            view_mode: "list,pivot,form",
            views: [
                [false, "list"],
                [false, "pivot"],
                [false, "form"],
            ],
            domain: [
                ["call_time", ">=", `${this.state.dateFrom} 00:00:00`],
                ["call_time", "<=", `${this.state.dateTo} 23:59:59`],
            ],
            target: "current",
        });
    }
}

registry
    .category("actions")
    .add("custom_leads_19.call_report_dashboard", CallReportDashboard);
