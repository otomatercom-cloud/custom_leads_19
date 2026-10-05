# Leads Management – Demo Guide

## 1. Load the demo (once, on a demo/training DB only)
Settings → Leads → **Demo Data** → *Load Demo Data*.  *Remove Demo Data* deletes exactly what was created.

## 2. Demo logins  (password for all: `Demo@1234`)
| Role | Login |
|---|---|
| Super Admin | demo.superadmin@demo.otomater.com |
| Manager | demo.manager@demo.otomater.com |
| Branch Head | demo.branchhead@demo.otomater.com |
| Digital Head / Digital Team | demo.digitalhead@… / demo.digitalteam@… |
| Team Lead Kochi / Calicut | demo.tl_kochi@… / demo.tl_calicut@… |
| Admission Officers | demo.ao1@… … demo.ao6@… (1-3 Kochi, 4-6 Calicut) |
| Tele Callers | demo.tele1@… , demo.tele2@… |
| Crash Head / Crash User | demo.crashhead@… / demo.crashuser@… |

Teams: **Demo Team - Kochi** (Anil Kumar + 3 officers), **Demo Team - Calicut** (Divya Nair + 3 officers).
Data: 40 leads (spread over 20 days, 4 sources, campaigns, all qualities), calls, responses, follow-ups (overdue / today / tomorrow), 4 re-attempts, and an *inactive* round-robin rule.

## 3. Demo script (≈15 min)
1. **Officer view** – log in as `ao1`: only own leads; open a lead, show call log, responses, change quality to Hot, schedule a follow-up.
2. **Follow-ups** – note overdue / today follow-ups popup for `ao1`.
3. **Team Lead** – log in as `tl_kochi`: sees all Kochi officers' leads; reassign one lead to `ao2`.
4. **Re-attempt** – log in as `ao4` / `manager`: open Re-Attempts, review a pending duplicate, approve/reject.
5. **Auto assignment** – as manager enable *Demo - Round Robin* rule, create a new lead with no owner → it is auto-assigned across both teams.
6. **Digital team** – `digitalteam`: create a lead with source *Demo - Meta Ads* + campaign; show source/campaign reports.
7. **Permissions** – `superadmin`: Settings → User Permissions, tick several users at once, save.
8. **Reports** – as manager: call report, lead pipeline by quality, per-officer counts.
9. **Cleanup** – Settings → Leads → *Remove Demo Data*.

Never load demo data on a live database.
