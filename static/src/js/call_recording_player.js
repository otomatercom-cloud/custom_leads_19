/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

/** Inline audio player for a call log row: uses the recording URL, else the uploaded recording file. */
export class CallRecordingPlayer extends Component {
    static template = "custom_leads_19.CallRecordingPlayer";
    static props = ["*"];

    get src() {
        const data = this.props.record.data;
        const url = (data.recording_url || "").trim();
        if (url) {
            return url;
        }
        if (data.has_recording && this.props.record.resId) {
            return `/web/content/lead.call.log/${this.props.record.resId}/recording`;
        }
        return "";
    }
}

registry.category("fields").add("call_recording_player", {
    component: CallRecordingPlayer,
    supportedTypes: ["char"],
});
