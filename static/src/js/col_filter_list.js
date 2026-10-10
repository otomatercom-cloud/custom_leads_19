/** @odoo-module **/
// Filter row under the column headers of the Leads list (type in a column to filter that column).
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";
import { Domain } from "@web/core/domain";
import { useState } from "@odoo/owl";

const TEXT_TYPES = ["char", "text", "many2one", "many2many", "one2many"];
const NUM_TYPES = ["integer", "float", "monetary"];
const DATE_TYPES = ["date", "datetime"];

export class ColFilterListRenderer extends ListRenderer {
    static template = "custom_leads_19.ColFilterListRenderer";

    setup() {
        super.setup();
        this.colFilter = useState({});
        this._colFilterTimer = null;
    }

    /** Visible columns - the property name differs between Odoo versions, so try each. */
    get filterColumns() {
        const cols = (this.state && this.state.columns) || this.columns || [];
        return Array.isArray(cols) ? cols : [];
    }

    colFilterField(column) {
        if (!column || column.type !== "field") {
            return null;
        }
        const f = this.props.list.fields && this.props.list.fields[column.name];
        if (!f || f.searchable === false) {
            return null;
        }
        return f;
    }

    colFilterKind(column) {
        const f = this.colFilterField(column);
        if (!f) {
            return "";
        }
        if (f.type === "selection") {
            return "selection";
        }
        if (DATE_TYPES.includes(f.type)) {
            return "date";
        }
        if (NUM_TYPES.includes(f.type)) {
            return "number";
        }
        if (TEXT_TYPES.includes(f.type)) {
            return "text";
        }
        return "";
    }

    colFilterOptions(column) {
        const f = this.colFilterField(column);
        return (f && f.selection) || [];
    }

    onColFilterInput(column, part, ev) {
        const slot = (this.colFilter[column.name] = this.colFilter[column.name] || {});
        slot[part] = ev.target.value;
        clearTimeout(this._colFilterTimer);
        this._colFilterTimer = setTimeout(() => this.applyColFilters(), 450);
    }

    applyColFilters() {
        const domain = [];
        for (const column of this.filterColumns) {
            const v = this.colFilter[column.name];
            const f = this.colFilterField(column);
            if (!v || !f) {
                continue;
            }
            const kind = this.colFilterKind(column);
            if (kind === "text" && v.value) {
                domain.push([column.name, "ilike", v.value]);
            } else if (kind === "selection" && v.value) {
                domain.push([column.name, "=", v.value]);
            } else if (kind === "number" && v.value !== undefined && v.value !== "") {
                domain.push([column.name, "=", Number(v.value)]);
            } else if (kind === "date") {
                const dt = f.type === "datetime";
                if (v.from) {
                    domain.push([column.name, ">=", dt ? `${v.from} 00:00:00` : v.from]);
                }
                if (v.to) {
                    domain.push([column.name, "<=", dt ? `${v.to} 23:59:59` : v.to]);
                }
            }
        }
        this.pushColFilterDomain(domain);
    }

    /** Odoo 19 has no setDomainParts: keep one hidden-id filter group in the search model and swap it. */
    pushColFilterDomain(domain) {
        const model = this.env.searchModel;
        if (!model) {
            return;
        }
        const old = this._colFilterGroupId;
        model.blockNotification = true;
        try {
            if (old) {
                model.deactivateGroup(old);
                this._colFilterGroupId = null;
            }
        } finally {
            model.blockNotification = false;
        }
        if (domain.length) {
            this._colFilterGroupId = model.nextGroupId;
            model.createNewFilters([
                { description: "Column filters", domain: new Domain(domain).toString() },
            ]);
        } else if (old) {
            model.search ? model._notify() : null;
        }
    }
}

export const colFilterListView = { ...listView, Renderer: ColFilterListRenderer };
registry.category("views").add("otm_col_filter_list", colFilterListView);
