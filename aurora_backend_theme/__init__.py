from . import controllers


def post_init_hook(env):
    """Open the dashboard after login for internal users without their own home action."""
    action = env.ref('aurora_backend_theme.action_aurora_home')
    env['res.users'].with_context(active_test=False).search(
        [('share', '=', False), ('action_id', '=', False)]).write({'action_id': action.id})


    from .controllers.main import _TZ_ALIASES
    env.cr.execute("SELECT name FROM pg_timezone_names")
    known = {r[0] for r in env.cr.fetchall()}
    for old, new in _TZ_ALIASES.items():
        if old not in known and new in known:
            env['res.users'].with_context(active_test=False).search([('tz', '=', old)]).write({'tz': new})


def uninstall_hook(env):
    action = env.ref('aurora_backend_theme.action_aurora_home', raise_if_not_found=False)
    if action:
        env['res.users'].with_context(active_test=False).search(
            [('action_id', '=', action.id)]).write({'action_id': False})
