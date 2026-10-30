import logging
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


_TZ_ALIASES = {'Asia/Calcutta': 'Asia/Kolkata', 'Asia/Saigon': 'Asia/Ho_Chi_Minh', 'Asia/Katmandu': 'Asia/Kathmandu',
               'Asia/Rangoon': 'Asia/Yangon', 'Asia/Dacca': 'Asia/Dhaka', 'Europe/Kiev': 'Europe/Kyiv',
               'US/Eastern': 'America/New_York', 'US/Central': 'America/Chicago',
               'US/Mountain': 'America/Denver', 'US/Pacific': 'America/Los_Angeles'}


def _pg_env(env):
    """Use a timezone PostgreSQL knows (old aliases like Asia/Calcutta break date grouping)."""
    tz = env.context.get('tz') or env.user.tz
    if not tz:
        return env
    def known(name):
        env.cr.execute("SELECT 1 FROM pg_timezone_names WHERE name = %s", [name])
        return bool(env.cr.fetchone())
    if known(tz):
        return env
    alias = _TZ_ALIASES.get(tz)
    return env(context=dict(env.context, tz=alias if alias and known(alias) else 'UTC'))


def _heal_tz(env):
    """Odoo itself (pivot, kanban grouping, reports...) fails with 'time zone "Asia/Calcutta" not
    recognized' when PostgreSQL lacks old timezone aliases: switch the user to the same zone's
    current name (e.g. Asia/Kolkata)."""
    tz = env.user.tz
    alias = _TZ_ALIASES.get(tz or '')
    if not alias:
        return
    env.cr.execute("SELECT name FROM pg_timezone_names WHERE name IN %s", [(tz, alias)])
    names = {r[0] for r in env.cr.fetchall()}
    if tz not in names and alias in names:
        env.user.sudo().tz = alias


def _dt(d):
    return fields.Datetime.to_string(datetime.combine(d, time.min))


class AuroraDashboard(http.Controller):
    """All figures are read with the current user's access rights; every block is optional
    (hidden when its app is not installed or the user has no access)."""

    @http.route('/aurora/dashboard', type='jsonrpc', auth='user')
    def dashboard(self, period='month', year=None):
        env = _pg_env(request.env)
        today = date.today()
        year = int(year or today.year)
        out = {'currency': env.company.currency_id.symbol or '', 'year': year, 'period': period}
        for key, fn in (('kpis', self._kpis), ('sales', self._sales), ('invoices', self._invoices),
                        ('products', lambda e, t: self._products(e, t, period)),
                        ('purchases', self._purchases), ('projects', self._projects),
                        ('activities', self._activities),
                        ('revexp', lambda e, t: self._revexp(e, t, year)),
                        ('tasks', self._tasks), ('orders', self._orders)):
            try:
                with env.cr.savepoint():
                    out[key] = fn(env, today)
            except Exception as e:  # missing app / access rights -> block hidden
                _logger.debug('Aurora block %s skipped: %s', key, e)
                out[key] = None
        return out

    # ------------------------------------------------------------------ helpers
    def _has(self, env, model):
        return model in env and env[model].has_access('read')

    def _tile(self, env, label, model, domain, icon, tone):
        return {'label': label, 'value': env[model].search_count(domain), 'model': model,
                'domain': domain, 'icon': icon, 'tone': tone}

    def _monthly(self, env, model, domain, date_field, measure, start, months):
        groups = env[model]._read_group(domain + [(date_field, '>=', _dt(start)),
                                                  (date_field, '<', _dt(start + relativedelta(months=months)))],
                                        [f'{date_field}:month'], [f'{measure}:sum'])
        by = {(k.year, k.month): v for k, v in groups if k}
        res = []
        for i in range(months):
            d = start + relativedelta(months=i)
            res.append({'label': MONTHS[d.month - 1], 'value': round(abs(by.get((d.year, d.month), 0) or 0), 2),
                        'from': _dt(d), 'to': _dt(d + relativedelta(months=1))})
        return res

    # ------------------------------------------------------------------ blocks
    def _kpis(self, env, today):
        uid, partner = env.uid, env.user.partner_id
        k = []
        if self._has(env, 'project.task'):
            k.append(self._tile(env, 'My Tasks', 'project.task',
                                [('user_ids', 'in', uid), ('state', 'not in', ['1_done', '1_canceled'])], 'tasks', 'violet'))
        if self._has(env, 'calendar.event'):
            k.append(self._tile(env, 'Meetings Today', 'calendar.event',
                                [('partner_ids', 'in', partner.id), ('start', '>=', _dt(today)),
                                 ('start', '<', _dt(today + timedelta(days=1)))], 'calendar', 'blue'))
        unread = env['mail.notification'].sudo().search_count(
            [('res_partner_id', '=', partner.id), ('is_read', '=', False)])
        k.append({'label': 'Unread Messages', 'value': unread, 'icon': 'mail', 'tone': 'pink', 'discuss': True})
        if self._has(env, 'purchase.order'):
            k.append(self._tile(env, 'Approvals', 'purchase.order', [('state', '=', 'to approve')], 'approve', 'amber'))
        return k

    def _sales(self, env, today):
        if not self._has(env, 'sale.order'):
            return None
        dom = [('state', '=', 'sale')]
        start = today.replace(day=1) - relativedelta(months=11)
        series = self._monthly(env, 'sale.order', dom, 'date_order', 'amount_untaxed', start, 12)
        cur, prev = series[-1]['value'], series[-2]['value']
        return {'total': cur, 'change': round((cur - prev) / prev * 100, 1) if prev else None,
                'series': series, 'model': 'sale.order', 'domain': dom, 'field': 'date_order'}

    def _invoices(self, env, today):
        if not self._has(env, 'account.move'):
            return None
        base = [('move_type', '=', 'out_invoice')]
        t = _dt(today)[:10]
        return [
            self._tile(env, 'Paid', 'account.move', base + [('state', '=', 'posted'), ('payment_state', 'in', ['paid', 'in_payment'])], 'check', 'green'),
            self._tile(env, 'Due', 'account.move', base + [('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial']), ('invoice_date_due', '>=', t)], 'clock', 'amber'),
            self._tile(env, 'Overdue', 'account.move', base + [('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial']), ('invoice_date_due', '<', t)], 'alert', 'red'),
            self._tile(env, 'Draft', 'account.move', base + [('state', '=', 'draft')], 'draft', 'blue'),
        ]

    def _products(self, env, today, period):
        if not self._has(env, 'sale.order.line'):
            return None
        start = {'month': today.replace(day=1), 'quarter': date(today.year, (today.month - 1) // 3 * 3 + 1, 1),
                 'year': date(today.year, 1, 1)}.get(period, today.replace(day=1))
        dom = [('order_id.state', '=', 'sale'), ('order_id.date_order', '>=', _dt(start)), ('product_id', '!=', False)]
        groups = env['sale.order.line']._read_group(dom, ['product_id'], ['price_subtotal:sum'],
                                                     order='price_subtotal:sum desc')
        total = sum(v for _k, v in groups) or 0
        items = [{'label': p.display_name, 'value': round(v, 2), 'domain': dom + [('product_id', '=', p.id)]}
                 for p, v in groups[:4]]
        rest = total - sum(i['value'] for i in items)
        if rest > 0.005:
            items.append({'label': 'Others', 'value': round(rest, 2),
                          'domain': dom + [('product_id', 'not in', [p.id for p, _v in groups[:4]])]})
        return {'total': round(total, 2), 'items': items, 'model': 'sale.order.line'}

    def _purchases(self, env, today):
        if not self._has(env, 'purchase.order'):
            return None
        po = 'purchase.order'
        tiles = [self._tile(env, 'To Approve', po, [('state', '=', 'to approve')], 'approve', 'violet'),
                 self._tile(env, 'RFQ Sent', po, [('state', '=', 'sent')], 'send', 'blue'),
                 self._tile(env, 'Confirmed', po, [('state', '=', 'purchase')], 'cart', 'green')]
        if 'receipt_status' in env[po]._fields:
            tiles.append(self._tile(env, 'Delivered', po, [('state', '=', 'purchase'), ('receipt_status', '=', 'full')], 'truck', 'amber'))
        return tiles

    def _projects(self, env, today):
        if not self._has(env, 'project.project'):
            return None
        Task = env['project.task']
        groups = Task._read_group([('project_id', '!=', False)], ['project_id'], ['__count'],
                                  order='__count desc', limit=4)
        res = []
        for proj, count in groups:
            done = Task.search_count([('project_id', '=', proj.id), ('state', '=', '1_done')])
            res.append({'id': proj.id, 'label': proj.display_name, 'value': round(done / count * 100) if count else 0,
                        'done': done, 'count': count})
        return res

    def _activities(self, env, today):
        acts = env['mail.activity'].search([('user_id', '=', env.uid)], order='date_deadline asc', limit=5)
        return [{'id': a.id, 'title': a.summary or a.activity_type_id.name or 'Activity',
                 'record': a.res_name or '', 'model': a.res_model, 'res_id': a.res_id,
                 'date': fields.Date.to_string(a.date_deadline), 'state': a.state,
                 'icon': a.activity_type_id.icon or 'fa-tasks',
                 'user_id': a.user_id.id, 'user': a.user_id.name} for a in acts]

    def _revexp(self, env, today, year):
        if not self._has(env, 'account.move'):
            return None
        start = date(year, 1, 1)
        base = [('state', '=', 'posted')]
        rev = self._monthly(env, 'account.move', base + [('move_type', '=', 'out_invoice')], 'invoice_date', 'amount_untaxed_signed', start, 12)
        exp = self._monthly(env, 'account.move', base + [('move_type', '=', 'in_invoice')], 'invoice_date', 'amount_untaxed_signed', start, 12)
        return {'labels': [m['label'] for m in rev], 'rev': [m['value'] for m in rev], 'exp': [m['value'] for m in exp],
                'ranges': [[m['from'][:10], m['to'][:10]] for m in rev],
                'years': list(range(today.year - 3, today.year + 1))}

    def _tasks(self, env, today):
        if not self._has(env, 'project.task'):
            return None
        T, base = 'project.task', [('user_ids', 'in', env.uid)]
        open_ = base + [('state', 'not in', ['1_done', '1_canceled'])]
        wk_end = today + timedelta(days=6 - today.weekday() + 1)
        mo_end = today.replace(day=1) + relativedelta(months=1)
        t1 = _dt(today + timedelta(days=1))
        return [self._tile(env, 'Today', T, open_ + [('date_deadline', '<', t1)], 'check', 'blue'),
                self._tile(env, 'This Week', T, open_ + [('date_deadline', '<', _dt(wk_end))], 'clock', 'red'),
                self._tile(env, 'This Month', T, open_ + [('date_deadline', '<', _dt(mo_end))], 'list', 'violet'),
                self._tile(env, 'Completed', T, base + [('state', '=', '1_done')], 'done', 'green')]

    def _orders(self, env, today):
        if not self._has(env, 'sale.order'):
            return None
        sel = dict(env['sale.order']._fields['state']._description_selection(env))
        return [{'id': o.id, 'name': o.name, 'customer': o.partner_id.display_name,
                 'date': fields.Date.to_string(o.date_order.date()) if o.date_order else '',
                 'amount': o.amount_total, 'state': o.state, 'state_label': sel.get(o.state, o.state)}
                for o in env['sale.order'].search([], order='date_order desc, id desc', limit=5)]


class AuroraBrand(http.Controller):

    @http.route('/aurora/brand', type='jsonrpc', auth='user')
    def brand(self):
        """Theme colours follow the company: its report colours, else colours read from its logo."""
        _heal_tz(request.env)
        company = request.env.company
        primary, secondary = company.primary_color, company.secondary_color
        if not primary and company.logo:
            try:
                primary, secondary = request.env['base.document.layout'].extract_image_primary_secondary_colors(company.logo)
            except Exception:  # unreadable logo -> default palette
                primary = secondary = None
        return {'id': company.id, 'name': company.name, 'has_logo': bool(company.logo),
                'primary': primary or '#6d28d9', 'secondary': secondary or '#f0abfc'}
