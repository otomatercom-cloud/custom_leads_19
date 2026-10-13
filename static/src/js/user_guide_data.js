/** @odoo-module **/
// Content of the in-app user guide. Plain data: edit the text here, no other code needs to change.
// Item = { t: title, path: where to find it, who: roles, what: short explanation, steps: [..],
//          opts: [[name, what it does, tip?], ..], tips: [..] }

export const FLOW = [
    ["Lead arrives", "Meta, WhatsApp, website, incoming call or import"],
    ["Assigned", "Pool round robin gives it to the next officer who is present"],
    ["Called", "Officer calls from Odoo; every call is logged with its duration"],
    ["Quality set", "Hot, Warm, Cold, RNR and so on after each conversation"],
    ["Follow-up", "Next call is scheduled and reminded"],
    ["Admission", "Counselling, fee and batch, lead is converted"],
];

export const GUIDE = [
    {
        id: "start", icon: "◎", title: "Start here",
        intro: "This guide explains every menu of Leads Management, what each option does and how to use it. Pick a topic on the left or search for any word.",
        items: [
            {
                t: "How a lead travels through the system", path: "Whole module", who: ["Everyone"],
                what: "Every enquiry becomes one lead. The system gives it to an admission officer, tracks every call and follow-up, and reports on speed and results. Most of the steps below happen automatically; officers only have to call and update the lead.",
                steps: [
                    "A lead is created automatically from Meta, WhatsApp, an incoming call or an import, or manually with Create.",
                    "The assignment rule gives it to an officer. The officer sees an URGENT popup for new leads.",
                    "The officer calls from the lead. The call is logged with status and duration.",
                    "After the call the officer sets the Lead Quality and, if needed, schedules a follow-up.",
                    "Leads that nobody calls are moved to another officer by the pool rules.",
                    "When the student joins, the lead is marked Admission and counting stops.",
                ],
                tips: ["Managers: start with Lead Reports and Response Performance. Officers: start with Call next."],
            },
            {
                t: "Who sees what", path: "Lead Management Settings > Access", who: ["Managers"],
                what: "Menus and records depend on the roles given in User Permissions. Officers see their own leads. Team leads see their team. Managers and Super Admins see everything and reach the settings.",
                opts: [
                    ["Super Admin", "Everything, including Settings, imports and permissions."],
                    ["Manager", "All leads, reports, assignment rules, coaching and merge tools."],
                    ["Team Lead", "The team's leads and reports, call reviews, pool screens."],
                    ["Admission Officer / Tele Caller", "Own leads, follow-ups, call next, own call reviews."],
                    ["Digital Team / Digital Head / Branch Head", "Role based access for marketing and branch work."],
                    ["Crash Head / Crash User", "Crash course lead handling."],
                    ["Re-Attempt User / Team Lead / Manager", "The three levels of the Re-Attempt approval flow."],
                ],
            },
        ],
    },
    {
        id: "whatsnew", icon: "★", title: "What's new",
        intro: "The latest changes to Leads Management, newest first. Each item says where to find it.",
        items: [
            {
                t: "Telegram updates for managers", path: "Settings > Telegram updates for managers", who: ["Manager", "Director"],
                what: "Three Telegram messages a day, at the hours you choose: morning, afternoon and evening. Each shows the leads created today so far and yesterday with Meta leads counted separately, and the admission officers' attendance (who signed in on time with the time, who was late, who has not signed in, who is on leave; the late time is set in Settings). The evening message also has the daily report: assigned, first call within 15, 30, 60 and 120 minutes, RNR, top performers and admissions.",
                steps: [
                    "Settings > Telegram Follow-Up Alerts: enter the Bot Token (see How to connect Telegram below).",
                    "Every manager who should get the updates opens the bot, presses Start and has a Chat ID on the user form (Call Settings tab).",
                    "Settings > Telegram updates for managers: switch on, set the three hours, tick Also send to team leads if needed.",
                    "Press Save & send the evening report to me to test.",
                ],
                tips: ["Meta leads are the leads whose source name contains Meta.", "Attendance comes from the Attendance app. Officers on approved leave are listed as On leave.", "The older 7 pm summary can be switched off under Evening summary for managers if you only want the new evening report."],
            },
            {
                t: "Top-up pool: more leads when an officer finishes", path: "Leads Management > Top-up Pool, Settings > Top-up pool", who: ["Manager", "Team Lead", "Admission Officer"],
                what: "When an admission officer has called everything for today, more leads are added to their list automatically. No team lead is needed. Switch it on or off in Settings.",
                steps: [
                    "Put leads in the pool: tick Top-up pool on a lead, select leads in the list and use Action > Add to Top-up pool, or mark a Lead Source with Feeds the top-up pool (Configuration > Lead Sources).",
                    "Pool leads that have no owner are not given out by the normal assignment. See them in Leads Management > Top-up Pool.",
                    "Settings > Top-up pool: switch on and set the numbers. Every 5 minutes the system checks the officers.",
                    "An officer who finished gets a popup and the new leads appear in their list.",
                ],
                opts: [
                    ["Finished means", "Today's queue is all called. With no queue, no new lead is left uncalled. Follow-ups due today also count."],
                    ["Calls made today before the first top-up", "Stops an officer from getting leads without calling. Default 20."],
                    ["Leads given each time / per day", "Default 20 each time, 60 a day for one officer."],
                    ["Minutes between two top-ups", "Default 15."],
                    ["Only officers who signed in today", "Needs attendance. Default on."],
                ],
                tips: ["If many officers finish together, the officer with the fewest top-ups goes first.", "Abroad and Junk leads never go into a top-up.", "When the pool is empty the managers get a popup once a day."],
            },
            {
                t: "Daily report on WhatsApp", path: "Settings > Daily report on WhatsApp", who: ["Manager", "Director"],
                what: "One short report every evening on WhatsApp: leads created, assigned, first call within 15, 30, 60 and 120 minutes, RNR, top performers and admissions. Switch it on in Settings.",
                steps: [
                    "Settings > Lead Management > Daily report on WhatsApp: tick the switch.",
                    "Enter the Phone number ID and Access token of the WhatsApp Business number (Meta WhatsApp Cloud API).",
                    "Enter the director and team lead numbers with country code, separated by commas.",
                    "Enter the name of an approved Utility template with two variables. Example text: Daily lead report for {{1}}: {{2}}",
                    "Press Save & send report now to test. The report then goes every evening at the chosen hour.",
                ],
                tips: ["WhatsApp lets a business start a chat only with an approved template, so a template name is needed. Without one the report reaches only numbers that wrote to your number in the last 24 hours.", "First call time is counted from the moment the lead was created."],
            },
            {
                t: "AI call analysis", path: "Settings > AI call analysis, Leads Management > AI Call Analysis", who: ["Manager", "Team Lead"],
                what: "Call recordings are transcribed and reviewed by AI. Each analysed call gets a summary, the student's real interest (Hot, Warm, Cold ...), an officer score from 1 to 10, the problems found and whether the lead quality matches the conversation. Switch it on or off in Settings.",
                steps: [
                    "Settings > Lead Management > AI call analysis: tick the switch and enter the speech-to-text key (OpenAI) and the AI key (Anthropic or OpenAI). Save.",
                    "Every 10 minutes connected calls with a recording are analysed. Open Leads Management > AI Call Analysis to see the results.",
                    "Use the filters Needs review, Score 4 or less and Interest: Hot. Switch to the pivot to compare officers by average score.",
                    "To analyse one call at once open it in the lead's Call History and press Analyse with AI.",
                ],
                opts: [
                    ["Only calls longer than", "Short calls are skipped. Default 30 seconds."],
                    ["Maximum calls analysed per day", "Stops the cost. Default 100."],
                    ["Only calls from the last (days)", "Old recordings are not analysed. Default 2 days."],
                    ["Needs review", "Officer score 4 or less, or the quality set by the officer does not match the call."],
                ],
                tips: ["The recording audio is sent to the AI companies you chose and is charged by call minutes.", "The call must have a recording. If a call has none, upload it in Call History."],
            },
            {
                t: "All Leads menu", path: "Leads Management > All Leads", who: ["Everyone"],
                what: "Every lead in one list: all qualities, including Admission Done, Junk and Abroad, which are hidden from the Leads menu. You still see only the leads your role allows.",
                tips: ["Use the Lead Quality filter or group by Lead Quality to find one kind of lead."],
            },
            {
                t: "Abroad leads", path: "Leads Management > Abroad", who: ["Everyone", "Managers"],
                what: "Leads from abroad answer on WhatsApp, not on the phone, so they must not follow the 3-call Ringing Not Responding rule. Tick Abroad Lead on the lead and it moves to its own Abroad menu.",
                steps: [
                    "Open the lead and tick Abroad Lead (Assignment section), then Save. Or select leads in the list and use Action > Mark as Abroad.",
                    "The lead leaves the Leads menu and shows in Leads Management > Abroad.",
                    "To bring it back, untick Abroad Lead or use Action > Move back from Abroad.",
                ],
                opts: [
                    ["Not applied to Abroad leads", "Automatic Ringing Not Responding after unanswered calls, the minimum-calls check for RNR, all pool reassign rules, and the RNR-after-noon popup."],
                    ["Still applied", "The URGENT popup for a new lead."],
                ],
            },
            {
                t: "Admission (Odoo 17) button", path: "Lead form > header", who: ["Admission Officer", "Manager"],
                what: "Admission is still done in Odoo 17. The button sends the lead with its details to Odoo 17 and opens it there.",
                steps: [
                    "Open the lead and press Admission (Odoo 17). Confirm.",
                    "The lead is created in Odoo 17 (or the existing one is found by phone number) and opens there.",
                ],
                tips: ["Switch the button on or off in Lead Management Settings > Odoo 17 admission.", "If Odoo 17 refuses the lead, the reason is shown (for example a missing batch, branch or course)."],
            },
            {
                t: "Cross-check with Odoo 17", path: "Leads Management > Odoo 17 > Cross-check with Odoo 17", who: ["Super Admin"],
                what: "Compares Odoo 19 leads created in a date range with Odoo 17 and adds what Odoo 19 is missing: responses, call logs, follow-ups, quality history, assignment history, empty fields and, if ticked, chatter. Nothing is deleted.",
                steps: [
                    "Choose From and To dates.",
                    "Choose what to do with Lead Quality and Admission Officer: take Odoo 17's value always, only when Odoo 19 is still New or has no officer, or leave as it is.",
                    "Press Preview to see the numbers without any change.",
                    "Press Cross-check & Add Missing Data. If it says some leads were not reached, press it again.",
                ],
                tips: ["Leads that came through the Odoo 17 import or sync are included; they are matched by their Odoo 17 id and phone number.", "Always means Odoo 17 wins even if the lead was worked in Odoo 19. Try a small date range first."],
            },
            {
                t: "Incoming calls and lead owner", path: "Automatic", who: ["Everyone"],
                what: "A lead with no owner goes to the officer who talks to the customer.",
                steps: [
                    "Incoming call answered by an officer: that officer gets the lead (if it is a new Incoming Call lead or has no owner).",
                    "Call missed, then an officer calls back and the call connects: the lead goes to that officer.",
                    "A lead that already has an owner is not taken away.",
                    "Leads created by an incoming call are never auto-reassigned by the pool rules.",
                ],
                tips: ["If a lead stays unassigned after a connected call, the officer's user must have the Voxbay or Bonvoice agent number and an employee record."],
            },
            {
                t: "Ringing Not Responding popup after noon", path: "Popup, Settings > Urgent popup", who: ["Admission Officer"],
                what: "A new lead gets an URGENT popup. It hides once the officer has called it. If the lead is still New or First Attempt after noon (hour can be changed in Settings) a second popup, RNR call needed, asks for another call.",
                tips: ["Several popups stack as small cards. Click one to open it and see its buttons.", "A popup also closes after the call is made."],
            },
            {
                t: "Back to the same place after a call", path: "Lead > Call", who: ["Admission Officer"],
                what: "After a call you return to the lead you were on, with the list position kept (for example 5 / 80), so you can press Next instead of starting the list again.",
            },
            {
                t: "Leads per campaign", path: "Leads > select > Add to Call Campaign", who: ["Manager", "Team Lead"],
                what: "Split a big selection into several campaigns of a fixed size. Enter Leads per Campaign and the wizard shows how many campaigns will be made.",
            },
            {
                t: "Junk menu and newest-first list", path: "Leads Management > Junk, Leads", who: ["Everyone"],
                what: "Junk leads (wrong number, not an enquiry) show only in Leads Management > Junk, not in the main Leads menu. The Leads list now shows the newest lead first.",
            },
            {
                t: "Call Report: officer filter and unique counts", path: "Leads Management > Reports > Call Report", who: ["Team Lead", "Manager"],
                what: "Filter the report by admission officer. Two new columns count Unique Leads called and Unique Connected, so repeat calls to the same lead are counted once.",
                tips: ["Pending = assigned leads minus unique leads called."],
            },
        ],
    },
    {
        id: "daily", icon: "☎", title: "Daily work",
        intro: "The Leads Management menu is what officers use every day.",
        items: [
            {
                t: "Dashboard", path: "Leads Management > Dashboard", who: ["Team Lead", "Manager"],
                what: "Counts of leads per stage category: Funnel, Prospects, RNR / DNP, Admission Done, Re-Try, Alumni and Junk. ",
                steps: ["Open Dashboard.", "Read the numbers per stage.", "Open the matching leads from the Leads menu to work on them."],
            },
            {
                t: "Leads", path: "Leads Management > Leads", who: ["Everyone"],
                what: "The main list of leads. Switch between list and kanban. Search, group and filter like any Odoo list.",
                steps: [
                    "Type in the search box or use the filters to narrow the list.",
                    "Use the filter row under the column headers to filter by one column.",
                    "Use the column picker at the right of the header to show or hide columns.",
                    "Open a lead to see calls, follow-ups, history and chatter.",
                    "Press Call on a lead. A call timer opens and the call is logged with its duration.",
                    "Change Lead Quality after every conversation. Admission Done leads leave this list.",
                ],
                opts: [
                    ["Lead Quality", "New, First Attempt, Hot, Warm, Cold, Follow Up, Call Later, May Be Later, Ringing Not Responding, Not Reachable, Language Barrier, Crash Lead, Waiting for Admission, Admission and closed values.", "Always set it after a call: reports and priority use it."],
                    ["Calls", "How many calls were made to this lead."],
                    ["Call Duration", "Total talk time."],
                    ["Assigned After / Called After", "How long the lead waited to be assigned and to get its first call."],
                    ["Follow-ups / Done / Due", "Follow-ups scheduled, completed and overdue."],
                    ["Priority (hidden by default)", "Call priority score. Switch it on in the column picker."],
                ],
                tips: ["Ringing Not Responding is blocked until the lead has the minimum number of calls set by the manager.", "Phone numbers are masked in the list; open the lead to call."],
            },
            {
                t: "Call next", path: "Leads Management > Call next", who: ["Admission Officer", "Tele Caller"],
                what: "Your own leads sorted by priority, best first. Work from the top of this list instead of choosing leads yourself.",
                steps: [
                    "Open Call next. It shows only your leads.",
                    "Start with the top lead (red rows are urgent: never called and high score).",
                    "Call, set the quality, schedule a follow-up if needed.",
                    "Come back to the list for the next lead.",
                ],
                opts: [
                    ["Priority %", "0 to 100. Higher means call sooner. Calculated every 15 minutes."],
                    ["How it is calculated", "Points for the lead's quality, how new it is, how few calls it has, its source and course, and a due follow-up. Managers set the numbers in Call priority points."],
                ],
            },
            {
                t: "Follow-Ups and Today's Follow-Ups", path: "Leads Management > Follow-Ups / Today's Follow-Ups", who: ["Everyone"],
                what: "Calls promised to students. Today's Follow-Ups shows what is due today. Overdue ones are marked.",
                steps: [
                    "On a lead press Follow Up and choose date, time and remark.",
                    "Open Today's Follow-Ups each morning.",
                    "After the call mark the follow-up Done or reschedule it.",
                ],
                tips: ["Telegram: you get a message when a follow-up is scheduled, a reminder before it is due, an alert when it is 30 minutes late and a morning list at 9:00."],
            },
            {
                t: "Counselling", path: "Leads Management > Counselling", who: ["Admission Officer", "Counsellor"],
                what: "Records every counselling session: appointment, walk-in or phone/video, the student's requirement, course recommended, outcome, next follow-up and parent details.",
                steps: ["Open Counselling or press Counselling on a lead.", "Fill date, counsellor, requirement, recommendation and outcome.", "Save. Counsellor Performance reports use these records."],
            },
            {
                t: "Re-Attempt Management", path: "Leads Management > Re-Attempt Management", who: ["Re-Attempt User", "Team Lead", "Manager"],
                what: "A controlled way to work an old lead again. A request is raised, reviewed and then assigned to an officer.",
                opts: [
                    ["Dashboard", "Totals of requests by status."],
                    ["Pending Review", "Requests waiting for approval."],
                    ["Approved / Assigned / Rejected", "Requests by status."],
                    ["All Re-Attempts", "Every request."],
                    ["My Re-Attempt Leads", "Leads assigned to you through this flow."],
                ],
                steps: ["Raise a re-attempt request for the old lead.", "The reviewer approves or rejects it in Pending Review.", "An approved lead is assigned to an officer and shows in My Re-Attempt Leads."],
            },
            {
                t: "Admission", path: "Leads Management > Admission", who: ["Admission Officer", "Manager"],
                what: "Admission Leads lists converted leads. Incoming Calls and Outgoing Calls list every call in each direction.",
                opts: [
                    ["Admission Leads", "Leads that became admissions."],
                    ["Incoming Calls", "Calls received, with caller, status, duration and recording."],
                    ["Outgoing Calls", "Calls made by officers."],
                ],
            },
            {
                t: "Call Center", path: "Leads Management > Call Center", who: ["Team Lead", "Manager", "Officer"],
                what: "Call campaigns: a prepared list of leads that an officer works through one by one, with the day's progress.",
                steps: ["Open Call Center. Your daily campaign is prepared for you.", "Open the next lead in the campaign and call it.", "Update the result and move on. Progress against the daily goal is shown."],
                tips: ["The daily call goal is set by the admin in Settings."],
            },
        ],
    },
    {
        id: "settings", icon: "⚙", title: "Settings page",
        intro: "Lead Management Settings > Settings. One page for the numbers and switches that control the module. Only Super Admins see it. Press Save after changing anything.",
        items: [
            {
                t: "Click to call (Voxbay and Bonvoice)", path: "Settings > Voxbay / Bonvoice", who: ["Super Admin"],
                what: "Connect the cloud telephony provider so officers can call from Odoo and calls are logged automatically.",
                opts: [
                    ["Voxbay UID, UPIN, Caller ID (DID)", "Account details given by Voxbay."],
                    ["Auto-Create Lead (Incoming)", "A call from an unknown number creates a lead automatically."],
                    ["Auto-Create Lead (Outgoing)", "Dialling an unknown number creates a lead."],
                    ["Bonvoice username, password, Leg A and Leg B caller IDs, API URL", "Account details for Bonvoice auto calling."],
                ],
            },
            {
                t: "Call button", path: "Settings > Call button", who: ["Manager", "Super Admin"],
                what: "Decides what the Call button on a lead does.",
                opts: [
                    ["Automatic", "Bonvoice or Voxbay if the officer has an agent / extension number, otherwise the phone app."],
                    ["Softphone or phone app", "Opens MicroSIP, Zoiper or the phone's dialler with the number and starts the call timer. The duration is saved on the call log."],
                    ["Voxbay / Bonvoice", "Calls through the cloud service, which also records the call."],
                    ["Phone app link", "tel: works with most phones and softphones. Use sip: if MicroSIP or Zoiper is the handler for sip links."],
                ],
                tips: ["On Windows, set MicroSIP as the default app for tel: or sip: links the first time the browser asks."],
            },
            {
                t: "Meta lead ads", path: "Settings > Meta", who: ["Super Admin"],
                what: "Connects Facebook and Instagram lead forms so leads arrive in Odoo automatically.",
                opts: [["Meta Verify Token", "The same token you enter in the Meta webhook setup."], ["Meta Page Access Token", "Lets Odoo read the lead details from Meta."]],
            },
            {
                t: "Popups and admission rules", path: "Settings > Leads", who: ["Super Admin"],
                what: "Switches that change what officers see.",
                opts: [
                    ["Enable Follow-Up Popup", "Shows today's follow-ups when a lead screen is opened."],
                    ["Urgent New-Lead Popup", "Shows an URGENT call-now card when a New lead is given to an officer. It returns every few minutes until the quality changes."],
                    ["Urgent popup only for these sources", "Pick Meta (or any sources) so the popup appears only for their leads. Empty = every source. Waiting popups of other sources are closed."],
                    ["Only recent leads", "Days back a lead may have arrived. 1 = yesterday and today (default), 0 = today only. The popup also shows only on the day the lead is assigned."],
                    ["Enable Call Timer Popup", "Opens a timer while a call is going on."],
                    ["Require Batch and Fee for Admission", "Officers must pick batch and fee structure before a lead can be marked Admission."],
                    ["Daily Call Goal", "The number of calls each officer should make per day. Shown on the dashboard and in the target report."],
                ],
            },
            {
                t: "Lead rules", path: "Settings > Lead rules", who: ["Manager", "Super Admin"],
                what: "Numbers that were fixed in the system are now yours to change. They apply to everyone.",
                opts: [
                    ["Called fast within (hours)", "A lead is counted as called fast when its first call comes within this time. Default 1.", "Used by Response Performance."],
                    ["Calls needed before Ringing Not Responding", "A lead cannot be set to RNR until it has this many calls. Default 3. Also the number of unanswered calls after which a lead becomes RNR automatically."],
                    ["Short call is under (seconds)", "Connected calls below this length appear in the Short calls report. Default 30."],
                    ["Coaching pass score (%)", "Officers whose average review score is lower are shown as Needs help. Default 70."],
                ],
            },
            {
                t: "Call priority", path: "Settings > Call priority", who: ["Manager"],
                what: "Decides which leads appear first in Call next. Quality has its own table; five other factors share the rest of the 100 points.",
                opts: [
                    ["Points per lead quality", "Opens the table. Give Hot, Warm, Cold and every other quality its own points. Biggest number is called first."],
                    ["New lead (default 15)", "Extra points for a lead that just arrived. Falls away over a week."],
                    ["Not called yet (default 10)", "Full points for a lead with no calls, fewer with every call."],
                    ["Lead source (default 8)", "Sources that turn into admissions more often get more."],
                    ["Course (default 4)", "Courses with better admission rate get more."],
                    ["Follow-up due (default 3)", "Added when a follow-up is due today or overdue."],
                ],
                tips: ["Scores refresh every 15 minutes. Use Recalculate scores now in the points table for an instant refresh."],
            },
            {
                t: "WhatsApp after a missed call", path: "Settings > WhatsApp after a missed call", who: ["Manager"],
                what: "When an outgoing call is not answered, a short WhatsApp message is queued for the lead, once per lead per day.",
                opts: [
                    ["Send automatically", "Switch on or off."],
                    ["Message", "The text. You can use {name}, {officer}, {course}, {institute}."],
                    ["Sending hours", "Messages outside these hours wait for the next morning window."],
                ],
                tips: ["Needs a WhatsApp sender to be connected. Until then messages stay Pending and are retried for 6 hours."],
            },
            {
                t: "Evening summary for managers", path: "Settings > Evening summary", who: ["Manager"],
                what: "Every evening at 7 pm managers get a short report: new leads, calls, uncalled leads, missed follow-ups and admissions per officer.",
                opts: [
                    ["Send every evening at 7 pm", "Switch on or off."],
                    ["Telegram / Email", "Choose where it is sent. Managers need a Telegram chat id or an email address."],
                    ["Send a test now", "Sends the summary immediately to check it."],
                ],
            },
            {
                t: "User guide", path: "Settings > User guide", who: ["Super Admin"],
                what: "Switch this on to show the Lead User Guide menu to every user. Switch it off to hide the guide again.",
            },
        ],
    },
    {
        id: "assignment", icon: "⇄", title: "Assignment",
        intro: "How new leads reach officers and how they move when nobody calls them. Lead Management Settings > Assignment.",
        items: [
            {
                t: "Lead Assignment Rules", path: "Lead Management Settings > Assignment > Lead Assignment Rules", who: ["Manager"],
                what: "A rule decides who gets each new lead. The first active rule (by sequence) that accepts the lead is used.",
                opts: [
                    ["Auto - All Active Teams (Round Robin)", "Leads are shared across all active teams in turn."],
                    ["Selected Teams (Bucket)", "Only chosen teams. Bucket size = how many leads one team receives before the next team."],
                    ["Source Based", "Each lead source goes to the teams you set in Source Assignment Rules."],
                    ["Pool Round Robin", "Leads go one by one to officers who are present. Described in the next card."],
                ],
                steps: ["Open Lead Assignment Rules and create or open a rule.", "Choose the Assignment Type and fill its options.", "Keep Active ticked. Use sequence to order several rules."],
            },
            {
                t: "Pool Round Robin: who receives leads", path: "Rule > Pool", who: ["Manager"],
                what: "The pool hands each new lead to the next eligible officer in a fixed rotation, so everyone gets the same number.",
                opts: [
                    ["Pool", "Officers signed in today (attendance), or a Manual pool of officers you tick on the Assignment Pool screen."],
                    ["Manual pool: also require sign-in today", "Skip pool officers who have not signed in."],
                    ["Stop pool when all officers are signed out", "Only officers signed in and not signed out receive leads. If nobody is in, leads wait."],
                    ["Only these lead sources", "Pick one or many sources (for example Meta). Leave empty for all. Sources not picked go to the next rule."],
                    ["Assign only in working hours", "Pool starts, Pool ends and Time zone. Leads that arrive outside wait and are given out when the pool opens."],
                    ["Pick up unassigned leads from last (days)", "How far back waiting leads are collected when the pool opens."],
                    ["Pool right now / Waiting leads / Last assigned officer", "A live preview: who is in the pool, how many leads wait and who got the last lead."],
                ],
            },
            {
                t: "Pool Round Robin: automatic reassignment", path: "Rule > Pool", who: ["Manager"],
                what: "Rules that take a lead from an officer who is not working it and give it to the next one. The officer who loses it and the one who gets it both see a popup, and the lead's chatter records the reason.",
                opts: [
                    ["Reassign if not called quickly", "A New lead with no call at all after the set minutes (default 15) moves to another officer. Checked every 2 minutes, only during pool hours."],
                    ["Call within (minutes)", "The number of minutes for the rule above."],
                    ["Reassign leads not called enough", "A New or First Attempt lead that did not get the required calls on the day it was assigned moves to another officer the next day."],
                    ["Calls required on the day", "Default 2."],
                    ["Reassign when quality changed", "Off; if an officer changes a New lead's quality without calling it; or whenever a New lead's quality is changed. The lead moves to the next officer."],
                    ["Auto RNR after unanswered calls", "A New or First Attempt lead whose calls were all unanswered becomes Ringing Not Responding by itself once it reaches the minimum calls."],
                    ["Max automatic reassignments per lead", "Default 2. After that the lead stays with the current officer."],
                ],
                tips: ["Admission, lost and officer-worked leads are never moved by these rules.", "Popups appear only while the officer is logged in; the chatter note is always added."],
            },
            {
                t: "Source Assignment Rules", path: "Lead Management Settings > Assignment > Source Assignment Rules", who: ["Manager"],
                what: "For Source Based rules: which teams receive leads of which source, shared in turn.",
                steps: ["Create a rule, choose the lead source.", "Add the teams that should receive it.", "Leads of that source now rotate between those teams."],
            },
            {
                t: "Assignment Pool", path: "Lead Management Settings > Assignment > Assignment Pool", who: ["Manager", "Team Lead"],
                what: "The list of officers with a switch In pool, today's sign-in status and how many leads each got today. Use it to take someone out of rotation for the day.",
                steps: ["Open Assignment Pool.", "Tick or untick In pool for an officer.", "Leads continue with the next officer at once."],
            },
            {
                t: "Assign Waiting Leads Now", path: "Lead Management Settings > Assignment > Assign Waiting Leads Now", who: ["Manager", "Team Lead"],
                what: "Runs the pool immediately for leads that are still waiting, without waiting for the automatic run.",
            },
            {
                t: "Assignment History", path: "Lead Management Settings > Assignment > Assignment History", who: ["Manager"],
                what: "Every assignment and reassignment: lead, from, to, date and reason. Use it to answer 'why did this lead move?'.",
            },
            {
                t: "Call priority points", path: "Lead Management Settings > Assignment > Call priority points", who: ["Manager"],
                what: "An editable table with points per lead quality for the Call next list.",
                steps: ["Open the table.", "Change the points of any quality directly in the list.", "Press Recalculate scores now, or wait up to 15 minutes."],
                tips: ["Admission, wrong number and not interested leads always score 0."],
            },
        ],
    },
    {
        id: "master", icon: "▤", title: "Master data and access",
        intro: "The lists that the rest of the system uses.",
        items: [
            {
                t: "Teams", path: "Lead Management Settings > Master Data > Teams", who: ["Manager"],
                what: "Create teams, choose the team lead and add members. A lead's team follows its owner's team.",
                steps: ["Create a team.", "Add team leads and members (admission officers).", "Tick In pool for members who should receive leads."],
            },
            {
                t: "Lead Sources, Courses, Source Campaigns", path: "Lead Management Settings > Master Data", who: ["Manager"],
                what: "The lists used on every lead.",
                opts: [
                    ["Lead Sources", "Meta, Whatsapp, Referral, Walk In, Incoming Call Leads and so on."],
                    ["Courses", "Courses a student can be interested in."],
                    ["Source Campaigns", "A campaign under a source, for example one Meta ad campaign. Reports can be split by campaign."],
                ],
            },
            {
                t: "User Permissions and Bulk User Permissions", path: "Lead Management Settings > Access", who: ["Super Admin"],
                what: "Give each user their roles in one screen. Bulk changes many users at once.",
                steps: ["Open User Permissions and choose the user.", "Tick the roles (Manager, Team Lead, Admission Officer and others).", "Save. The menus change at the next refresh."],
            },
        ],
    },
    {
        id: "tools", icon: "✦", title: "Tools",
        intro: "Extra tools for quality, clean data and imports. Lead Management Settings > Tools.",
        items: [
            {
                t: "Coaching Checklist", path: "Lead Management Settings > Tools > Coaching Checklist", who: ["Manager"],
                what: "The questions team leads answer when they review a recorded call, for example greeting, course explained, next step set.",
                steps: ["Add, rename or reorder checklist items.", "Archive items you no longer use."],
            },
            {
                t: "Merge duplicate leads", path: "Lead Management Settings > Tools > Merge duplicate leads", who: ["Manager"],
                what: "Finds leads with the same phone number (last 10 digits) and merges each group into one. Calls, follow-ups, history and chatter are moved to the lead that is kept.",
                steps: [
                    "Open the tool; duplicate groups are listed.",
                    "Check the lead marked as the one to keep (admission first, then most calls, then oldest).",
                    "Untick groups you do not want to merge.",
                    "Press Merge. Everything is recorded in the Merge log.",
                ],
                tips: ["Merging deletes the duplicate record after moving its data. Check a few groups first."],
            },
            {
                t: "Merge log", path: "Lead Management Settings > Tools > Merge log", who: ["Manager"],
                what: "Who merged which leads and when, for audit.",
            },
            {
                t: "WhatsApp after missed call", path: "Lead Management Settings > Tools", who: ["Manager"],
                what: "The queue of missed-call messages with status Pending, Sent, Failed or Skipped.",
            },
            {
                t: "Import from Odoo 17", path: "Lead Management Settings > Tools > Import Leads / Import Logs / Sync Queue", who: ["Super Admin"],
                what: "Brings leads, calls, follow-ups and chatter from the old Odoo 17 system.",
                opts: [
                    ["Import Leads", "Choose the date range and campaigns, then start. Large imports continue in the background."],
                    ["Import Logs", "One line per import run: selected, created, skipped and failed."],
                    ["Sync Queue", "Records waiting to be synced."],
                ],
                tips: ["Run only one import at a time."],
            },
        ],
    },
    {
        id: "reports", icon: "▥", title: "Reports and coaching",
        intro: "Lead Reports & Coaching is the main menu for managers and team leads.",
        items: [
            {
                t: "Lead Reports", path: "Lead Reports & Coaching > Reports > Lead Reports", who: ["Manager", "Team Lead"],
                what: "About 40 ready reports in one screen with date range, source, team, officer and course filters, a chart, CSV download and print.",
                steps: [
                    "Pick a report on the left or search for it.",
                    "Choose the date range (Today, 7 days, 30 days, This month, This year or custom).",
                    "Narrow by source, team, officer or course if needed.",
                    "Read the chart and table. Use CSV to download or Print.",
                ],
                opts: [
                    ["Lead intake", "Leads by source, by campaign, intake trend, re-attempt requests, import logs."],
                    ["Speed and response", "Response speed by officer, not called yet by waiting time, not assigned leads."],
                    ["Admission officers", "Officer scorecard, daily call target vs actual, idle officers, attendance vs calls."],
                    ["Teams", "Team comparison."],
                    ["Pipeline and quality", "Stage funnel, quality distribution, quality changes, RNR leads, days since last call."],
                    ["Follow-ups", "By officer, today and tomorrow, missed follow-ups."],
                    ["Counselling and admissions", "Counselling summary, conversion by officer, admissions by course, course demand, lost reasons."],
                    ["Assignment and pool", "Assignment history, auto-reassigned leads, pool fairness."],
                    ["Call details and duration", "Call log detail, duration by officer and by lead, connected vs not connected, peak call hours, short calls, calls per lead by quality, recording coverage, incoming vs outgoing."],
                    ["Coaching", "Coaching scorecard, checklist results, recorded calls not reviewed."],
                    ["Management", "Weekly summary."],
                ],
            },
            {
                t: "Stage Analysis and Counsellor Performance", path: "Lead Reports & Coaching > Reports", who: ["Manager", "Team Lead"],
                what: "Stage Analysis shows how leads are spread across stages. Counsellor Performance shows counselling sessions and outcomes by counsellor.",
            },
            {
                t: "Response Performance", path: "Lead Reports & Coaching > Calls > Response Performance", who: ["Manager", "Team Lead"],
                what: "How fast leads are assigned and called: averages per day, week, month and year, and by source, team and officer. 'Called fast' uses the hours set in Lead rules.",
            },
            {
                t: "Lead Response Time", path: "Lead Reports & Coaching > Calls > Lead Response Time", who: ["Manager", "Team Lead"],
                what: "A list of every lead with its assign delay, call delay and follow-up counts. Sort, filter and group it like any list.",
            },
            {
                t: "Call Report and Call Logs", path: "Lead Reports & Coaching > Calls", who: ["Manager", "Team Lead"],
                what: "Call Report is the call dashboard: totals, connected calls and talk time by officer. Call Logs is the full list of calls with status, duration and recording.",
            },
            {
                t: "Coaching: reviewing calls", path: "Lead Reports & Coaching > Coaching", who: ["Team Lead", "Manager", "Officer"],
                what: "Team leads listen to recorded calls and score them against the checklist. Officers see their own finished reviews.",
                opts: [
                    ["Calls to review", "Connected, recorded calls that have no review yet."],
                    ["Call reviews", "All reviews with score and result."],
                    ["My call reviews", "Officers: your own finished reviews."],
                ],
                steps: [
                    "Open Calls to review and choose a call, or press Review on any call log.",
                    "Play the recording.",
                    "Answer each checklist item: Yes, Partial, No or Not applicable.",
                    "Add comments and press Done. Every item must be answered.",
                ],
                tips: ["Score: Yes = 1, Partial = half, No = 0, shown as a percentage. An officer below the pass score appears as Needs help in the Coaching scorecard."],
            },
        ],
    },
    {
        id: "auto", icon: "↻", title: "What runs by itself",
        intro: "Automatic jobs. You do not have to start them, but it helps to know what they do.",
        items: [
            {
                t: "Automatic jobs at a glance", path: "Settings > Technical > Scheduled Actions", who: ["Manager", "Super Admin"],
                what: "These keep leads moving without anyone watching.",
                opts: [
                    ["Pool assignment", "Gives waiting leads to the next officer whenever the pool is open."],
                    ["Not called in time", "Every 2 minutes: moves a New lead that has had no call after the set minutes."],
                    ["Not called enough", "Every 30 minutes: moves leads that missed the required calls on their first day."],
                    ["Auto RNR", "At the moment a call is logged: sets RNR after the minimum number of unanswered calls."],
                    ["Call priority", "Every 15 minutes: refreshes the Call next scores."],
                    ["Telegram follow-up alerts", "Instant, before due, 30 minutes late and a 9:00 morning list."],
                    ["Urgent popup", "Shown when a New lead is given to an officer, repeated until its quality changes."],
                    ["Missed-call WhatsApp", "Queued when an outgoing call is not answered; sent in the allowed hours."],
                    ["Evening summary", "7 pm to managers by Telegram and email."],
                ],
            },
        ],
    },
    {
        id: "help", icon: "?", title: "Questions and answers",
        intro: "The most common questions, with the place to look.",
        items: [
            {
                t: "Why is a new lead not assigned?", path: "Lead Management Settings > Assignment", who: ["Manager"],
                what: "Check these in order.",
                steps: [
                    "Is the pool open? Look at Pool starts and Pool ends on the rule.",
                    "Is any officer signed in? With attendance pool, nobody present means leads wait.",
                    "Is the lead's source in Only these lead sources? If not, the next rule must accept it.",
                    "Is the rule Active and first in sequence?",
                    "Press Assign Waiting Leads Now. Read Pool right now on the rule.",
                ],
            },
            {
                t: "Why did a lead move to another officer?", path: "Lead > Chatter, Assignment History", who: ["Everyone"],
                what: "Open the lead. The chatter shows 'Auto-reassigned from A to B' with the reason: not called within the set minutes, not enough calls on the day, or quality changed without a call.",
            },
            {
                t: "Why can I not set Ringing Not Responding?", path: "Lead", who: ["Officer"],
                what: "The lead needs the minimum number of calls (default 3). Call it again and the quality can then be changed. If every call was unanswered it changes automatically.",
            },
            {
                t: "Why is a lead's priority high although I called it?", path: "Call next", who: ["Officer"],
                what: "Priority comes from the quality, source, course, freshness, calls and follow-up. A Hot lead stays high even after calls. Change its quality or ask the manager to change the points.",
            },
            {
                t: "I changed a setting but nothing changed", path: "Settings", who: ["Manager"],
                what: "Press Save on the Settings page. Call priority scores refresh within 15 minutes, or use Recalculate scores now. Menus change after the browser is refreshed.",
            },
        ],
    },
];
