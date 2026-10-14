/** @odoo-module **/
// Filter row under the column headers of the Leads list (type in a column to filter that column).
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";
import { Domain } from "@web/core/domain";
import { useState, useRef, onWillStart, onMounted, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const TEXT_TYPES = ["char", "text", "many2one", "many2many", "one2many"];
const NUM_TYPES = ["integer", "float", "monetary"];
const DATE_TYPES = ["date", "datetime"];

export class ColFilterListRenderer extends ListRenderer {
    static template = "custom_leads_19.ColFilterListRenderer";

    setup() {
        super.setup();
        this.colFilter = useState({});
        this._colFilterTimer = null;
        this.colLayout = useState({ order: [], hidden: [] });
        this.colMenu = useState({ open: false, top: 0, right: 0 });      // this user's own column order (saved on the server)
        this._colOrm = useService("orm");
        this._colRoot = useRef("root");
        this._colDrag = null;
        onWillStart(async () => {
            try {
                const prefs = await this._colOrm.call("otm.user.list.layout", "get_prefs", [this._colLayoutKey()]);
                this.colLayout.order = Array.isArray(prefs && prefs.order) ? prefs.order : [];
                this.colLayout.hidden = Array.isArray(prefs && prefs.hidden) ? prefs.hidden : [];
                if ((this.colLayout.order.length || this.colLayout.hidden.length) && this.state && typeof this.getActiveColumns === "function") {
                    this.state.columns = this.getActiveColumns(this.props.list);
                }
            } catch (e) {
                console.warn("column layout not loaded", e);
            }
        });
        onMounted(() => this._colBindDrag());
        onPatched(() => this._colMarkHeaders());
    }

    _colLayoutKey() {
        const cfg = this.env.config || {};
        return `${this.props.list.resModel}:${cfg.actionId || 0}`;
    }

    /** Put the columns in this user's saved order (columns not in the saved list keep their place at the end). */
    _colSort(cols) {
        const order = (this.colLayout && this.colLayout.order) || [];
        if (!order.length || !Array.isArray(cols)) {
            return cols;
        }
        const pos = (c, i) => {
            const k = order.indexOf(c.name || c.id);
            return k >= 0 ? k : 10000 + i;
        };
        return cols
            .map((c, i) => [pos(c, i), c])
            .sort((a, b) => a[0] - b[0])
            .map((x) => x[1]);
    }

    getActiveColumns(...args) {
        const cols = this._colSort(super.getActiveColumns(...args));
        const hidden = (this.colLayout && this.colLayout.hidden) || [];
        if (!hidden.length || !Array.isArray(cols)) {
            return cols;
        }
        const left = cols.filter((c) => !hidden.includes(c.name || c.id));
        return left.length ? left : cols;          // never hide every column
    }

    /** Every column of this list (visible or hidden by the user), for the "Columns" menu. */
    get colAll() {
        const hidden = this.colLayout.hidden;
        let all = [];
        try {
            all = this._colSort(super.getActiveColumns(this.props.list)) || [];
        } catch (e) {
            all = this.filterColumns;
        }
        return all
            .filter((c) => c.type === "field")
            .map((c) => {
                const f = (this.props.list.fields && this.props.list.fields[c.name]) || {};
                return { name: c.name, label: c.label || c.string || f.string || c.name, on: !hidden.includes(c.name) };
            });
    }

    colToggleMenu(ev) {
        if (!this.colMenu.open) {
            const r = ev.currentTarget.getBoundingClientRect();
            this.colMenu.top = Math.round(r.bottom + 4);
            this.colMenu.right = Math.max(8, Math.round(window.innerWidth - r.right));
            this._colOutside = (e) => {
                if (!e.target.closest || !e.target.closest(".o_otm_colmenu, .o_otm_colbtn")) {
                    this.colMenu.open = false;
                    document.removeEventListener("mousedown", this._colOutside, true);
                }
            };
            document.addEventListener("mousedown", this._colOutside, true);
        }
        this.colMenu.open = !this.colMenu.open;
    }

    async colToggleColumn(name) {
        const hidden = this.colLayout.hidden.slice();
        const i = hidden.indexOf(name);
        if (i >= 0) {
            hidden.splice(i, 1);
        } else {
            if (this.colAll.filter((c) => c.on).length <= 1) {
                return;                                  // keep at least one column
            }
            hidden.push(name);
        }
        this.colLayout.hidden = hidden;
        this.state.columns = this.getActiveColumns(this.props.list);
        await this._colSave();
    }

    async _colSave() {
        try {
            await this._colOrm.call("otm.user.list.layout", "set_prefs", [
                this._colLayoutKey(), this.colLayout.order, this.colLayout.hidden,
            ]);
        } catch (e) {
            console.warn("column layout not saved", e);
        }
    }

    _colHeaders() {
        const root = this._colRoot && this._colRoot.el;
        return root ? [...root.querySelectorAll("thead tr:first-child th[data-name]")] : [];
    }

    _colMarkHeaders() {
        for (const th of this._colHeaders()) {
            th.setAttribute("draggable", "true");
            th.classList.add("o_otm_col_drag");
        }
    }

    _colBindDrag() {
        const root = this._colRoot && this._colRoot.el;
        if (!root) {
            return;
        }
        this._colMarkHeaders();
        const th = (ev) => ev.target.closest && ev.target.closest("thead tr:first-child th[data-name]");
        root.addEventListener("dragstart", (ev) => {
            const h = th(ev);
            if (!h || (ev.target.closest && ev.target.closest(".o_resize"))) {
                return;
            }
            this._colDrag = h.dataset.name;
            ev.dataTransfer.effectAllowed = "move";
            ev.dataTransfer.setData("text/plain", this._colDrag);
        });
        root.addEventListener("dragover", (ev) => {
            const h = th(ev);
            if (!h || !this._colDrag) {
                return;
            }
            ev.preventDefault();
            this._colHeaders().forEach((x) => x.classList.toggle("o_otm_drag_over", x === h && h.dataset.name !== this._colDrag));
        });
        root.addEventListener("drop", (ev) => {
            const h = th(ev);
            if (!h || !this._colDrag) {
                return;
            }
            ev.preventDefault();
            this._colMove(this._colDrag, h.dataset.name);
        });
        root.addEventListener("dragend", () => {
            this._colDrag = null;
            this._colHeaders().forEach((x) => x.classList.remove("o_otm_drag_over"));
        });
    }

    async _colMove(from, to) {
        this._colDrag = null;
        this._colHeaders().forEach((x) => x.classList.remove("o_otm_drag_over"));
        if (!from || !to || from === to) {
            return;
        }
        const names = this.filterColumns.map((c) => c.name || c.id);
        const fi = names.indexOf(from);
        const ti = names.indexOf(to);
        if (fi < 0 || ti < 0) {
            return;
        }
        names.splice(ti, 0, names.splice(fi, 1)[0]);
        this.colLayout.order = names;
        this.state.columns = this._colSort(this.state.columns);
        await this._colSave();
    }

    async resetColOrder() {
        this.colLayout.order = [];
        this.colLayout.hidden = [];
        await this._colSave();
        window.location.reload();
    }

    /** Visible columns - the property name differs between Odoo versions, so try each. */
    get filterColumns() {
        let cols = [];
        try {
            cols = this.getActiveColumns(this.props.list);       // same source the header uses (respects hidden / order)
        } catch (e) {
            cols = [];
        }
        if (!Array.isArray(cols) || !cols.length) {
            cols = (this.state && this.state.columns) || this.columns || [];
        }
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
