"""Lead Quality list update: remap removed values before the selection changes.
already_joined -> logic_students, not_attended -> not_responding."""


def migrate(cr, version):
    cr.execute("""
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND column_name IN ('lead_quality', 'new_quality')
    """)
    for table, col in cr.fetchall():
        for old, new in (('already_joined', 'logic_students'),
                         ('not_attended', 'not_responding')):
            cr.execute('UPDATE "%s" SET "%s" = %%s WHERE "%s" = %%s' % (table, col, col), (new, old))
