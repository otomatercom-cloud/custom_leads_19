/** @odoo-module **/
// Hiring leads: hide the admission-style header buttons that other modules add (WhatsApp templates, Bizwhatz...).
// The buttons are found by their label, so it works whichever module adds them.
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { useEffect } from "@odoo/owl";

const HIDE_FOR_HIRING = ["welcome message", "schedule whatsapp", "send to bizwhatz", "send to bizwhatsapp"];

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.props.resModel !== "leads.logic") {
            return;
        }
        useEffect(() => {
            const root = this.model && this.model.root;
            const el = (this.rootRef && this.rootRef.el) || document;
            const hiring = !!(root && root.data && root.data.is_hiring);
            for (const btn of el.querySelectorAll(".o_form_statusbar button, .o_statusbar_buttons button")) {
                const label = (btn.textContent || "").trim().toLowerCase();
                const match = HIDE_FOR_HIRING.some((t) => label.includes(t));
                if (match && hiring) {
                    btn.dataset.otmHid = "1";
                    btn.style.display = "none";
                } else if (btn.dataset.otmHid) {
                    delete btn.dataset.otmHid;
                    btn.style.display = "";
                }
            }
        });
    },
});
