/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

/** Chance-of-joining panel for the lead form (gauge, call quality, customer approach, timeline, next step). */
export class ConvInsight extends Component {
    static template = "custom_leads_19.ConvInsight";
    static props = ["*"];

    get d() {
        return this.props.record.data[this.props.name] || null;
    }
    get dash() {
        const d = this.d;
        return d ? ((d.chance / 100) * 2 * Math.PI * 42).toFixed(1) : 0;
    }
    get circ() {
        return (2 * Math.PI * 42).toFixed(1);
    }
    get bandLabel() {
        const b = this.d && this.d.band;
        return b === "high" ? "High" : b === "medium" ? "Medium" : "Low";
    }
    tone(v) {
        return v >= 70 ? "good" : v >= 50 ? "mid" : "bad";
    }
    barH(t) {
        if (!t.ok) {
            return 12;
        }
        return Math.max(16, Math.min(52, 16 + t.secs / 6));
    }
}

registry.category("fields").add("conv_insight", {
    component: ConvInsight,
    supportedTypes: ["json"],
});
