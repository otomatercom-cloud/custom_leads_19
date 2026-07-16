/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

class ReattemptDashboard extends Component {
    static template = "custom_leads_19.ReattemptDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            pending: 0,
            approved: 0,
            assigned: 0,
            rejected: 0,
            total: 0,
            conversionPct: 0,
            loading: true,
            error: false,
        });
        onWillStart(async () => {
            await this.loadStats();
        });
    }

    async loadStats() {
        try {
            // Odoo 19: read_group returns __count (not field_name_count)
            const counts = await this.orm.call(
                "otomater.lead.reattempt",
                "read_group",
                [
                    [[("active"), "=", true]],
                    ["review_status"],
                    ["review_status"]
                ],
                { lazy: false }
            );
            let pending = 0, approved = 0, assigned = 0, rejected = 0;
            for (const row of counts) {
                const st = row.review_status;
                // Odoo 19 uses __count; fallback to legacy field_count for safety
                const cnt = row.__count || row.review_status_count || 0;
                if (st === "pending_review") pending = cnt;
                else if (st === "approved") approved = cnt;
                else if (st === "assigned") assigned = cnt;
                else if (st === "rejected") rejected = cnt;
            }
            const total = pending + approved + assigned + rejected;
            const converted = approved + assigned;
            const pct = total > 0 ? Math.round((converted / total) * 100) : 0;

            this.state.pending = pending;
            this.state.approved = approved;
            this.state.assigned = assigned;
            this.state.rejected = rejected;
            this.state.total = total;
            this.state.conversionPct = pct;
            this.state.loading = false;
        } catch (e) {
            console.error("ReattemptDashboard loadStats error:", e);
            this.state.loading = false;
            this.state.error = true;
        }
    }

    openPending() {
        this.action.doAction("custom_leads_19.action_reattempt_pending");
    }
    openApproved() {
        this.action.doAction("custom_leads_19.action_reattempt_approved");
    }
    openAssigned() {
        this.action.doAction("custom_leads_19.action_reattempt_assigned");
    }
    openRejected() {
        this.action.doAction("custom_leads_19.action_reattempt_rejected");
    }
    openAll() {
        this.action.doAction("custom_leads_19.action_reattempt_all");
    }
}

registry.category("actions").add("custom_leads_19.reattempt_dashboard", ReattemptDashboard);
