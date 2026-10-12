/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";


/**
 * Return to the screen the call was started from (keeps the list pager, e.g. 5 / 80),
 * instead of opening a brand new single-record form (1 / 1).
 * Returns true when it managed to go back.
 */
async function goBackToCaller(env, skipName) {
    try {
        const crumbs = ((env.config && env.config.breadcrumbs) || []).filter(
            (b) => b && typeof b.onSelected === "function" && b.name !== skipName
        );
        const last = crumbs[crumbs.length - 1];
        if (last) {
            await last.onSelected();
            return true;
        }
    } catch (e) {
        console.error("goBackToCaller failed", e);
    }
    return false;
}

/**
 * Fires a tel: link via window.open (OS handles it as a phone dialler),
 * then immediately opens the lead quality + response wizard.
 * Used when Call Timer Popup is disabled in Settings.
 */
class LeadDirectCall extends Component {
    static template = "custom_leads_19.LeadDirectCall";
    static props = ["action", "actionStack?"];

    setup() {
        const actionService = useService("action");
        const env = this.env;
        const p = this.props.action.params || {};

        onMounted(async () => {
            // 1. Fire tel: — OS handles as phone dialler, does NOT navigate current page
            if (p.phone) {
                window.open((p.dial_scheme || "tel") + ":" + p.phone, "_blank");
            }

            // 2. Navigate to the lead form first so wizard opens on top of it
            let back = false;
            if (!p.open_lead) {
                back = await goBackToCaller(this.env, "");
            }
            if (p.lead_id && !back) {
                await actionService.doAction({
                    type: "ir.actions.act_window",
                    res_model: "leads.logic",
                    res_id: p.lead_id,
                    views: [[false, "form"]],
                    target: "main",
                });
            }

            // 3. Open the quality + response wizard on top of lead form
            if (p.wizard_action) {
                setTimeout(async () => {
                    try {
                        await actionService.doAction(p.wizard_action);
                    } catch (e) {
                        console.error("[DirectCall] Wizard open error:", e);
                    }
                }, 300);
            }
        });
    }
}

registry.category("actions").add("lead_direct_call", LeadDirectCall);
