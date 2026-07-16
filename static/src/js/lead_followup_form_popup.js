/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { onMounted } from "@odoo/owl";

let _actionService = null;
let _orm = null;
let _popupLoading = false;

function escapeHtml(text) {
    return String(text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

async function checkAndShowTodayFollowups(orm) {
    if (_popupLoading) {
        return;
    }
    _popupLoading = true;
    try {
        // Check if follow-up popup is enabled (reads ir.config_parameter)
        const result = await orm.call("leads.config.helper", "get_followup_popup_enabled", [], {});
        if (!result) {
            return;
        }
        const followups = await orm.call("lead.followup", "get_today_followups", [], {});
        if (Array.isArray(followups) && followups.length > 0) {
            showFollowupPopup(followups);
        }
    } catch (err) {
        console.warn("[Lead Follow-up] Popup error:", err);
    } finally {
        _popupLoading = false;
    }
}

function setupLeadFollowupPopup(component, orm, actionService) {
    _orm = orm;
    _actionService = actionService;
    onMounted(() => {
        checkAndShowTodayFollowups(orm);
    });
}

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.props.resModel !== "leads.logic") {
            return;
        }
        const orm = useService("orm");
        const action = useService("action");
        setupLeadFollowupPopup(this, orm, action);
    },
});

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.props.resModel !== "leads.logic") {
            return;
        }
        const orm = useService("orm");
        const action = useService("action");
        setupLeadFollowupPopup(this, orm, action);
    },
});

window._openLeadFollowup = function (leadId) {
    if (!_actionService || !leadId) {
        return;
    }
    _actionService.doAction({
        type: "ir.actions.act_window",
        res_model: "leads.logic",
        res_id: leadId,
        views: [[false, "form"]],
        target: "current",
    });
    const popup = document.getElementById("lead_followup_today_popup");
    if (popup) {
        popup.remove();
    }
};

window._markFollowupDone = async function (followupId, btnEl) {
    if (!_orm || !followupId) {
        return;
    }

    btnEl.disabled = true;
    btnEl.textContent = "⏳";

    try {
        await _orm.call("lead.followup", "action_mark_done", [[followupId]]);

        const row = document.getElementById(`fu_row_${followupId}`);
        if (row) {
            row.style.transition = "opacity 0.3s, transform 0.3s";
            row.style.opacity = "0";
            row.style.transform = "translateX(30px)";
            setTimeout(() => {
                row.remove();
                const tbody = document.querySelector("#lead_followup_today_popup tbody");
                const remaining = tbody ? tbody.querySelectorAll("tr").length : 0;
                const badge = document.getElementById("fu_count_badge");
                if (badge) {
                    badge.textContent = remaining;
                }
                if (remaining === 0) {
                    const popup = document.getElementById("lead_followup_today_popup");
                    if (popup) {
                        popup.style.transition = "opacity 0.3s";
                        popup.style.opacity = "0";
                        setTimeout(() => popup.remove(), 300);
                    }
                }
            }, 300);
        }
    } catch (err) {
        console.error("[Follow-up Done] Error:", err);
        btnEl.disabled = false;
        btnEl.textContent = "✅ Done";
    }
};

function formatFollowupTime(datetimeStr) {
    if (!datetimeStr) {
        return "--:--";
    }
    try {
        const normalized = datetimeStr.includes("T")
            ? datetimeStr
            : datetimeStr.replace(" ", "T");
        const dt = new Date(normalized);
        if (Number.isNaN(dt.getTime())) {
            return datetimeStr.substring(11, 16) || "--:--";
        }
        return dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
        return datetimeStr.substring(11, 16) || "--:--";
    }
}

function showFollowupPopup(followups) {
    const existing = document.getElementById("lead_followup_today_popup");
    if (existing) {
        existing.remove();
    }

    const rows = followups.map((fu) => {
        const leadName = escapeHtml(fu.lead_name || "Unknown Lead");
        const leadId = fu.lead_id || 0;
        const time = formatFollowupTime(fu.next_followup_date);
        const remarks = escapeHtml(fu.remarks);
        const phone = escapeHtml(fu.phone_number);

        return `
            <tr id="fu_row_${fu.id}" style="border-bottom:1px solid #f3eef3;">
                <td style="padding:9px 10px;">
                    <button onclick="window._openLeadFollowup(${leadId})" title="Open Lead"
                        style="background:none;border:none;color:#875a7b;font-weight:600;font-size:13px;
                               cursor:pointer;padding:0;text-align:left;text-decoration:underline dotted;">
                        📋 ${leadName}
                    </button>
                </td>
                <td style="padding:9px 10px;white-space:nowrap;">
                    <span style="background:#fff3e0;color:#e65c00;border-radius:12px;padding:2px 10px;
                                 font-weight:700;font-size:12px;">⏰ ${time}</span>
                </td>
                <td style="padding:9px 10px;">
                    ${phone
                        ? `<a href="tel:${phone}" style="color:#555;text-decoration:none;font-size:12px;">📞 ${phone}</a>`
                        : `<span style="color:#bbb;font-size:12px;">—</span>`}
                </td>
                <td style="padding:9px 10px;color:#888;font-size:12px;max-width:140px;
                           overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${remarks}">
                    ${remarks || "—"}
                </td>
                <td style="padding:9px 10px;text-align:center;">
                    <button id="fu_done_btn_${fu.id}" onclick="window._markFollowupDone(${fu.id}, this)"
                        style="background:#e8f5e9;color:#2e7d32;border:1.5px solid #a5d6a7;border-radius:8px;
                               padding:4px 12px;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;">
                        ✅ Done
                    </button>
                </td>
            </tr>`;
    }).join("");

    const popup = document.createElement("div");
    popup.id = "lead_followup_today_popup";
    popup.innerHTML = `
        <div style="position:fixed;bottom:24px;right:24px;z-index:9999;width:700px;max-width:95vw;
                    background:#fff;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,0.18);
                    font-family:sans-serif;overflow:hidden;">
            <div style="background:linear-gradient(135deg,#875a7b,#c0392b);padding:13px 18px;
                        display:flex;justify-content:space-between;align-items:center;">
                <div style="color:#fff;font-size:15px;font-weight:700;">
                    🔔 Today's Follow-Ups
                    <span id="fu_count_badge" style="background:#fff;color:#c0392b;border-radius:12px;
                                                     padding:1px 10px;font-size:12px;font-weight:800;margin-left:8px;">
                        ${followups.length}
                    </span>
                </div>
                <button id="fu_popup_close" style="background:transparent;border:none;color:#fff;
                                                    font-size:20px;cursor:pointer;line-height:1;">✕</button>
            </div>
            <div style="max-height:320px;overflow-y:auto;">
                <table style="width:100%;border-collapse:collapse;">
                    <thead>
                        <tr style="background:#faf5fa;border-bottom:2px solid #f0e6f0;position:sticky;top:0;">
                            <th style="padding:8px 10px;text-align:left;color:#875a7b;font-size:12px;">Lead</th>
                            <th style="padding:8px 10px;text-align:left;color:#875a7b;font-size:12px;">Time</th>
                            <th style="padding:8px 10px;text-align:left;color:#875a7b;font-size:12px;">Phone</th>
                            <th style="padding:8px 10px;text-align:left;color:#875a7b;font-size:12px;">Remarks</th>
                            <th style="padding:8px 10px;text-align:center;color:#875a7b;font-size:12px;">Action</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            <div style="padding:9px 16px;background:#faf5fa;display:flex;justify-content:space-between;
                        align-items:center;font-size:12px;color:#aaa;border-top:1px solid #f0e6f0;">
                <span>📅 Today's scheduled follow-ups</span>
                <button id="fu_popup_dismiss" style="background:#875a7b;color:#fff;border:none;border-radius:8px;
                                                      padding:5px 14px;font-size:12px;cursor:pointer;font-weight:600;">
                    Dismiss
                </button>
            </div>
        </div>`;

    document.body.appendChild(popup);
    document.getElementById("fu_popup_close").addEventListener("click", () => popup.remove());
    document.getElementById("fu_popup_dismiss").addEventListener("click", () => popup.remove());
}
