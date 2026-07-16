/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

console.log("Loading LeadFunnelListController Module...");

class LeadFunnelListController extends ListController {
    setup() {
        super.setup();
        console.log("LeadFunnelListController: Setup called");
    }

    async onRowClicked(record, ev) {
        console.log("LeadFunnelListController: onRowClicked");
        // Prevent default list behavior (edit or open)
        ev.preventDefault();
        ev.stopPropagation();
        await this.openRecord(record);
    }

    async openRecord(record) {
        console.log("LeadFunnelListController: openRecord called for record", record.resId);
        const actionService = this.env.services.action;
        try {
            const confirm_action = await this.orm.call(
                "leads.logic",
                "action_open_confirm_wizard",
                [[record.resId]],
                { context: this.context }
            );
            console.log("Confirm Action received:", confirm_action);
            if (confirm_action) {
                await actionService.doAction(confirm_action);
            } else {
                console.warn("No confirm action returned, falling back.");
                super.openRecord(record);
            }
        } catch (error) {
            console.error("Error opening confirmation wizard:", error);
            super.openRecord(record);
        }
    }
}

export const LeadFunnelListView = {
    ...listView,
    Controller: LeadFunnelListController,
};

registry.category("views").add("lead_funnel_list", LeadFunnelListView);
registry.category("views").add("custom_list_renderer", LeadFunnelListView);
