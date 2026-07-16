{
    'name': 'Leads Management',
    'version': '19.0.1.4.4',
    'summary': 'Custom Leads Management Module',
    'description': """
        Standalone Leads Management module for Odoo 19.
        Manages leads lifecycle, assignments, follow-ups, call tracking,
        course interest tracking, and sales funnel stages.
        No dependency on openeducat or any third-party education module.

        v1.1.0 – Lead Assignment Engine:
          - Configurable assignment rules (all_teams / selected_teams / source_based)
          - Round-Robin team & member assignment with DB-safe concurrency
          - Bucket-based assignment for selected teams
          - Source-based assignment with multi-team round-robin
          - include_team_leads toggle
          - Extended assignment history with audit trail
          - Manual reassignment audit
    """,
    'author': 'Ajesh',
    'website': 'https://www.otomater.com',
    'category': 'Sales/CRM',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'hr',
        'website',
        'student_details_19',
        
    ],
    'data': [
        'security/groups.xml',
        'security/reattempt_groups.xml',
        'security/ir.model.access.csv',
        'security/rules.xml',
        'data/reattempt_sequence.xml',
        'views/source.xml',
        'views/course_inter.xml',
        'views/leads.xml',
        'views/lead_reattempt_views.xml',
        'views/leads_reattempt_inherit.xml',
        'views/reattempt_dashboard.xml',
        'views/lead_dashboard.xml',
        'views/connection.xml',
        'views/allocation.xml',
        'views/leads_confirm_wizard_view.xml',
        'views/leads_funnel_wizard_view.xml',
        'views/leads_schedule_wizard_view.xml',
        'views/lead_followup_wizard_view.xml',
        'views/lead_followup_views.xml',
        'views/kanban_quick_wizard_views.xml',
        'views/lead_admission_wizard_view.xml',
        'views/voxbay_call_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_users_views.xml',
        'views/lead_daily_queue_views.xml',
        'views/manual_queue_wizard_view.xml',
        'views/lead_team_views.xml',
        'views/lead_user_permission_views.xml',
        'views/lead_assignment_views.xml',
        'views/bulk_assign_team_wizard_view.xml',
        'views/call_campaign_views.xml',
        'views/call_report_views.xml',
        'data/actions.xml',
        'data/followup_cron.xml',
        'data/daily_queue_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'custom_leads_19/static/src/css/leads.css',
            'custom_leads_19/static/src/css/call_campaign.css',
            'custom_leads_19/static/src/css/progress_bar.css',
            'custom_leads_19/static/src/css/lead_dashboard.css',
            'custom_leads_19/static/src/css/reattempt_dashboard.css',
            'custom_leads_19/static/src/js/lead_funnel_list.js',
            'custom_leads_19/static/src/js/lead_followup_form_popup.js',
            'custom_leads_19/static/src/css/lead_call_timer.css',
            'custom_leads_19/static/src/js/lead_call_timer.js',
            'custom_leads_19/static/src/js/lead_direct_call.js',
            'custom_leads_19/static/src/js/call_campaign_runner.js',
            'custom_leads_19/static/src/js/call_campaign_dashboard.js',
            'custom_leads_19/static/src/xml/lead_direct_call.xml',
            'custom_leads_19/static/src/xml/call_campaign_runner.xml',
            'custom_leads_19/static/src/xml/call_campaign_dashboard.xml',
            'custom_leads_19/static/src/xml/lead_call_timer.xml',
            'custom_leads_19/static/src/js/lead_stage_dashboard.js',
            'custom_leads_19/static/src/xml/lead_stage_dashboard.xml',
            'custom_leads_19/static/src/js/queue_dashboard.js',
            'custom_leads_19/static/src/xml/queue_dashboard.xml',
            'custom_leads_19/static/src/js/reattempt_dashboard.js',
            'custom_leads_19/static/src/xml/reattempt_dashboard.xml',
            'custom_leads_19/static/src/css/call_report_dashboard.css',
            'custom_leads_19/static/src/js/call_report_dashboard.js',
            'custom_leads_19/static/src/xml/call_report_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
