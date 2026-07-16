from . import source
from . import leads
from . import allocation
from . import connection
from . import lead_admission_wizard
from . import leads_confirm_wizard
from . import leads_funnel_wizard
from . import leads_schedule_wizard
from . import res_company
from . import res_config_settings
from . import res_users
from . import voxbay_call_wizard

from . import kanban_quick_wizards
from . import lead_daily_queue
from . import manual_queue_wizard
from . import lead_reattempt
from . import lead_reattempt_bulk
from . import leads_reattempt_extend
from . import lead_team
from . import lead_user_permission
from . import lead_assignment_engine
from . import lead_assignment_integration
from . import bulk_assign_team_wizard
from . import call_campaign
from . import call_report
from . import campaign_generate_wizard

try:
    from . import student_inherit
except Exception:
    pass
