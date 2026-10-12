/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { GUIDE, FLOW } from "./user_guide_data";

export class LeadUserGuide extends Component {
    static template = "custom_leads_19.UserGuide";

    setup() {
        this.guide = GUIDE;
        this.flow = FLOW;
        this.state = useState({ active: GUIDE[0].id, q: "", closed: {} });
    }

    get current() {
        return this.guide.find((s) => s.id === this.state.active) || this.guide[0];
    }

    get total() {
        return this.guide.reduce((n, s) => n + s.items.length, 0);
    }

    get results() {
        const q = this.state.q.trim().toLowerCase();
        if (!q) return [];
        const out = [];
        for (const s of this.guide) {
            for (const it of s.items) {
                if (JSON.stringify(it).toLowerCase().includes(q)) out.push({ section: s, item: it });
            }
        }
        return out;
    }

    select(id) {
        this.state.active = id;
        this.state.q = "";
        const el = document.querySelector(".o_ug_main");
        if (el) el.scrollTop = 0;
    }

    openFromSearch(res) {
        this.state.q = "";
        this.state.active = res.section.id;
    }

    key(sec, it) {
        return sec.id + "|" + it.t;
    }

    isClosed(sec, it) {
        return !!this.state.closed[this.key(sec, it)];
    }

    toggle(sec, it) {
        const k = this.key(sec, it);
        this.state.closed[k] = !this.state.closed[k];
    }

    collapseAll(flag) {
        for (const it of this.current.items) this.state.closed[this.key(this.current, it)] = flag;
    }

    print() {
        window.print();
    }
}

registry.category("actions").add("custom_leads_19.user_guide", LeadUserGuide);
