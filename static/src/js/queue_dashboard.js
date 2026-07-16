/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, useState } from "@odoo/owl";

class QueueDashboard extends Component {
    static template = "custom_leads_19.QueueDashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            loading: true,
            data: null,
            error: null,
        });
        onMounted(() => this.loadData());
    }

    async loadData() {
        try {
            const data = await this.orm.call(
                "leads.logic",
                "get_queue_dashboard_data",
                []
            );
            this.state.data = data;
            this.state.loading = false;
        } catch (e) {
            this.state.error = e.message || "Failed to load queue data.";
            this.state.loading = false;
        }
    }

    openAllQueues() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "All Officer Queues",
            res_model: "leads.logic",
            view_mode: "kanban,list",
            domain: [["daily_queue_date", "=", new Date().toISOString().slice(0, 10)]],
        });
    }

    _qualityColor(quality) {
        const map = {
            hot: '#D85A30',
            warm: '#BA7517',
            cold: '#185FA5',
            not_responding: '#6c757d',
            not_reachable: '#6c757d',
            not_attended: '#6c757d',
            new: '#0dcaf0',
            first_attempt: '#0d6efd',
            call_later: '#fd7e14',
            follow_up: '#6610f2',
            waiting_for_admission: '#e67e22',
            already_joined: '#198754',
            wrong_number: '#e74c3c',
            not_interested: '#e74c3c',
        };
        return map[quality] || '#adb5bd';
    }

    openAssignWizard() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Assign Queue to Officer",
            res_model: "manual.queue.assign.wizard",
            view_mode: "form",
            target: "new",
        });
    }
}

registry.category("actions").add("custom_leads_19.queue_dashboard", QueueDashboard);
