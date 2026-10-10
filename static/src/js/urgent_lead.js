/** @odoo-module **/

import { registry } from "@web/core/registry";
import { reactive } from "@odoo/owl";
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const POLL_MS = 60 * 1000;

function beep() {
    try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) {
            return;
        }
        const ctx = new Ctx();
        [0, 0.28, 0.56].forEach((t) => {
            const o = ctx.createOscillator();
            const g = ctx.createGain();
            o.type = "square";
            o.frequency.value = 880;
            g.gain.value = 0.06;
            o.connect(g);
            g.connect(ctx.destination);
            o.start(ctx.currentTime + t);
            o.stop(ctx.currentTime + t + 0.18);
        });
        setTimeout(() => ctx.close(), 1500);
    } catch (e) {
        /* sound is a bonus - autoplay rules may block it */
    }
}

export const urgentLeadService = {
    dependencies: ["bus_service", "orm", "action"],
    start(env, { bus_service, orm, action }) {
        const state = reactive({ alerts: [] });
        let disabled = false;
        let failures = 0;

        function add(payload, withSound) {
            if (!payload || !payload.id || state.alerts.some((a) => a.id === payload.id)) {
                return;
            }
            state.alerts.push(payload);
            if (withSound) {
                beep();
            }
        }
        function remove(id) {
            const i = state.alerts.findIndex((a) => a.id === id);
            if (i >= 0) {
                state.alerts.splice(i, 1);
            }
        }
        async function refresh(withSound) {
            if (disabled) {
                return;
            }
            try {
                const rows = await orm.call("lead.urgent.alert", "get_my_pending", []);
                const ids = new Set(rows.map((r) => r.id));
                state.alerts.filter((a) => !ids.has(a.id)).forEach((a) => remove(a.id));
                rows.forEach((r) => add(r, withSound));
                failures = 0;
            } catch (e) {
                // user without lead access / logged out: stop after 3 failures in a row
                failures += 1;
                if (failures >= 3) {
                    disabled = true;
                }
            }
        }

        bus_service.subscribe("urgent_lead", (payload) => add(payload, true));
        bus_service.subscribe("urgent_lead_close", (payload) => remove(payload && payload.id));
        try {
            bus_service.start();
        } catch (e) {
            /* already started */
        }
        setTimeout(() => refresh(true), 3000);
        setInterval(() => refresh(true), POLL_MS);

        return {
            state,
            async call(a) {
                remove(a.id);
                const act = await orm.call("lead.urgent.alert", "action_call", [[a.id]]);
                if (act) {
                    await action.doAction(act);
                }
            },
            async open(a) {
                remove(a.id);
                await orm.call("lead.urgent.alert", "action_snooze", [[a.id]], { minutes: 10 });
                await action.doAction({
                    type: "ir.actions.act_window",
                    res_model: "leads.logic",
                    res_id: a.lead_id,
                    views: [[false, "form"]],
                    target: "current",
                });
            },
            async snooze(a, minutes) {
                remove(a.id);
                await orm.call("lead.urgent.alert", "action_snooze", [[a.id]], { minutes });
            },
        };
    },
};
registry.category("services").add("urgent_lead", urgentLeadService);

export class UrgentLeadPopup extends Component {
    static template = "custom_leads_19.UrgentLeadPopup";
    static props = {};
    setup() {
        this.svc = useService("urgent_lead");
        this.state = useState(this.svc.state);
    }
}
registry.category("main_components").add("custom_leads_19.UrgentLeadPopup", { Component: UrgentLeadPopup });
