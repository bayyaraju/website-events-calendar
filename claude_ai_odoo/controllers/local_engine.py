# -*- coding: utf-8 -*-
"""Local answers: handle frequent requests directly in Odoo, without calling the
Anthropic API (zero tokens, instant).  Everything runs as the current user, so Odoo
access rights and record rules apply exactly as in the normal UI."""
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields

READ_METHODS = {'search_read', 'search_count', 'read', 'name_search', 'fields_get', 'read_group'}

# Plain words -> (model, extra domain, fields)
SYNONYMS = [
    (r'customers?|clients?', 'res.partner', [('customer_rank', '>', 0)], ['name', 'email', 'phone', 'city']),
    (r'vendors?|suppliers?', 'res.partner', [('supplier_rank', '>', 0)], ['name', 'email', 'phone', 'city']),
    (r'contacts?|partners?', 'res.partner', [], ['name', 'email', 'phone', 'city']),
    (r'products?|items?', 'product.product', [], ['display_name', 'default_code', 'list_price']),
    (r'(customer )?invoices?', 'account.move', [('move_type', '=', 'out_invoice')], ['name', 'partner_id', 'invoice_date', 'amount_total', 'payment_state']),
    (r'(vendor )?bills?', 'account.move', [('move_type', '=', 'in_invoice')], ['name', 'partner_id', 'invoice_date', 'amount_total', 'payment_state']),
    (r'sales? orders?|sales|quotations?', 'sale.order', [], ['name', 'partner_id', 'date_order', 'amount_total', 'state']),
    (r'purchase orders?|purchases?|pos', 'purchase.order', [], ['name', 'partner_id', 'date_order', 'amount_total', 'state']),
    (r'employees?|staff', 'hr.employee', [], ['name', 'department_id', 'job_title', 'work_email']),
    (r'departments?', 'hr.department', [], ['name', 'manager_id']),
    (r'users?', 'res.users', [], ['name', 'login']),
    (r'companies|company', 'res.company', [], ['name', 'email', 'phone']),
    (r'leads?|opportunit(y|ies)', 'crm.lead', [], ['name', 'partner_id', 'expected_revenue', 'stage_id']),
    (r'tasks?', 'project.task', [], ['name', 'project_id', 'stage_id', 'date_deadline']),
    (r'projects?', 'project.project', [], ['name', 'partner_id']),
    (r'events?', 'event.event', [], ['name', 'date_begin', 'seats_reserved']),
    (r'deliver(y|ies)|transfers?|pickings?', 'stock.picking', [], ['name', 'partner_id', 'scheduled_date', 'state']),
]


def normalize(text):
    text = (text or '').lower().strip()
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def cache_key(text):
    return hashlib.sha1(normalize(text).encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
class LocalEngine:

    def __init__(self, env, run_op, build_excel, auto_chart, install_module):
        self.env = env
        self.run_op = run_op            # controller _execute_op (access-checked, savepoint)
        self.build_excel = build_excel
        self.auto_chart = auto_chart
        self.install_module = install_module

    # ------------------------------------------------------------------ utils
    def has(self, model):
        return model in self.env

    def valid_fields(self, model, flds):
        known = self.env[model]._fields
        return [f for f in flds if f in known]

    def reply(self, text, **kw):
        res = {'message': text, 'source': 'local', 'tokens_used': 0}
        res.update(kw)
        return res

    def missing(self, app):
        return self.reply(f'ℹ️ The **{app}** app is not installed in this database. '
                          f'Ask me *"install {app.lower()} module"* to add it.')

    def today_range(self):
        start = datetime.combine(date.today(), time.min)
        return fields.Datetime.to_string(start), fields.Datetime.to_string(start + timedelta(days=1))

    def month_start(self, months_back=0):
        d = date.today().replace(day=1) - relativedelta(months=months_back)
        return fields.Datetime.to_string(datetime.combine(d, time.min))

    def query(self, title, model, domain, flds, order=None, limit=200, chart=None, summary_field=None):
        flds = self.valid_fields(model, flds)
        op = {'model': model, 'method': 'search_read', 'args': [domain],
              'kwargs': {'fields': flds, 'limit': limit, 'order': order}}
        rows, err = self.run_op(self.env, op)
        if err:
            return self.reply(f'⚠️ {err}')
        n = len(rows)
        text = f'⚡ **{title}** — {n} record{"s" if n != 1 else ""}'
        if summary_field and rows and summary_field in rows[0]:
            total = sum((r.get(summary_field) or 0) for r in rows)
            text += f', total **{total:,.2f}**'
        text += '.' if n else '. Nothing found.'
        chart_spec = self.auto_chart(rows, chart, title, title) if (chart and rows) else None
        return self.reply(text, odoo_operation=op, op_result=rows, chart_spec=chart_spec)

    def grouped_chart(self, title, model, domain, groupby, measure, chart_type, limit=None, order=None):
        Model = self.env[model]
        Model.check_access('read')
        groups = Model._read_group(domain, [groupby], [f'{measure}:sum'], order=order, limit=limit)
        labels, data = [], []
        for key, value in groups:
            if hasattr(key, 'display_name'):
                label = key.display_name or '—'
            elif isinstance(key, (date, datetime)):
                label = key.strftime('%b %Y')
            else:
                label = str(key or '—')
            labels.append(label)
            data.append(round(value or 0, 2))
        if not labels:
            return self.reply(f'⚡ **{title}** — no data for this period.')
        if chart_type != 'line':
            pairs = sorted(zip(labels, data), key=lambda x: -x[1])[:limit or 20]
            labels, data = [p[0] for p in pairs], [p[1] for p in pairs]
        spec = {'type': chart_type, 'title': title, 'labels': labels,
                'datasets': [{'label': measure.replace('_', ' ').title(), 'data': data}]}
        rows = [{'label': l, 'value': v} for l, v in zip(labels, data)]
        return self.reply(f'⚡ **{title}** — {len(labels)} groups, total **{sum(data):,.2f}**.',
                          chart_spec=spec, op_result=rows)

    # ------------------------------------------------------- quick actions
    def quick(self, key):
        h = getattr(self, f'q_{key}', None)
        return h() if h else None

    def q_today_sales(self):
        if not self.has('sale.order'):
            return self.missing('Sales')
        s, e = self.today_range()
        return self.query("Today's Sales", 'sale.order', [('date_order', '>=', s), ('date_order', '<', e)],
                          ['name', 'partner_id', 'amount_total', 'state'], 'date_order desc',
                          summary_field='amount_total')

    def q_revenue_pie(self):
        if not self.has('sale.order'):
            return self.missing('Sales')
        return self.grouped_chart('Revenue by Customer (this month)', 'sale.order',
                                  [('state', '=', 'sale'), ('date_order', '>=', self.month_start())],
                                  'partner_id', 'amount_total', 'pie', limit=10)

    def q_unpaid_invoices(self):
        if not self.has('account.move'):
            return self.missing('Invoicing')
        return self.query('Unpaid Invoices', 'account.move',
                          [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                           ('payment_state', 'in', ('not_paid', 'partial'))],
                          ['name', 'partner_id', 'amount_residual', 'invoice_date_due'],
                          'invoice_date_due asc', summary_field='amount_residual')

    def q_monthly_excel(self):
        if not self.has('sale.order'):
            return self.missing('Sales')
        flds = self.valid_fields('sale.order', ['name', 'partner_id', 'date_order', 'user_id', 'amount_total', 'state'])
        spec = {'filename': f'sales_{date.today():%Y_%m}.xlsx', 'sheets': [{
            'name': f'Sales {date.today():%B %Y}', 'model': 'sale.order', 'fields': flds,
            'field_labels': [self.env['sale.order']._fields[f].string for f in flds],
            'domain': [('date_order', '>=', self.month_start())], 'order': 'date_order desc'}]}
        try:
            b64 = self.build_excel(self.env, spec)
        except Exception as e:
            return self.reply(f'⚠️ Excel could not be built: {e}')
        return self.reply('⚡ **Monthly Excel Report** is ready — click *Download*.',
                          excel_b64=b64, excel_filename=spec['filename'])

    def q_top_products(self):
        if not self.has('sale.order.line'):
            return self.missing('Sales')
        start = fields.Datetime.to_string(datetime(date.today().year, 1, 1))
        return self.grouped_chart('Top 10 Products by Revenue (this year)', 'sale.order.line',
                                  [('order_id.state', '=', 'sale'), ('order_id.date_order', '>=', start)],
                                  'product_id', 'price_subtotal', 'bar', limit=10,
                                  order='price_subtotal:sum desc')

    def q_stock_levels(self):
        if not self.has('stock.quant'):
            return self.missing('Inventory')
        dom = [('is_storable', '=', True)] if 'is_storable' in self.env['product.product']._fields else [('type', '=', 'product')]
        res = self.query('Stock Levels', 'product.product', dom,
                         ['display_name', 'qty_available', 'virtual_available'], 'default_code, id')
        rows = res.get('op_result')
        if isinstance(rows, list):  # qty_available is computed: sort in Python
            rows.sort(key=lambda r: -(r.get('qty_available') or 0))
        return res

    def q_employees(self):
        if not self.has('hr.employee'):
            return self.missing('Employees')
        return self.query('Employees', 'hr.employee', [], ['name', 'department_id', 'job_title'], 'name')

    def q_revenue_trend(self):
        if not self.has('sale.order'):
            return self.missing('Sales')
        return self.grouped_chart('Monthly Revenue (last 6 months)', 'sale.order',
                                  [('state', '=', 'sale'), ('date_order', '>=', self.month_start(5))],
                                  'date_order:month', 'amount_total', 'line', order='date_order:month asc')

    def q_browse_modules(self):
        # read-only listing with the user's own rights (ir.module.module is not exposed
        # to generic assistant operations)
        rows = self.env['ir.module.module'].search_read(
            [('state', '=', 'uninstalled'), ('application', '=', True)],
            ['shortdesc', 'name', 'summary'], order='sequence, shortdesc', limit=60)
        return self.reply(f'⚡ **Apps available to install** — {len(rows)} apps. '
                          f'Ask e.g. *"install crm module"* to install one.', op_result=rows)

    def q_pending_pos(self):
        if not self.has('purchase.order'):
            return self.missing('Purchase')
        return self.query('Pending Purchase Orders', 'purchase.order',
                          [('state', 'in', ('draft', 'sent', 'to approve'))],
                          ['name', 'partner_id', 'amount_total', 'state'], 'date_order desc',
                          summary_field='amount_total')

    # ------------------------------------------------------- free text
    def resolve_model(self, phrase):
        phrase = phrase.strip()
        for rx, model, dom, flds in SYNONYMS:
            if re.fullmatch(rx, phrase) and self.has(model):
                return model, dom, flds
        # fall back to technical name or model description
        cand = phrase[:-1] if phrase.endswith('s') else phrase
        IrModel = self.env['ir.model'].sudo()
        rec = IrModel.search([('model', '=', phrase.replace(' ', '.'))], limit=1) or \
            IrModel.search([('name', '=ilike', cand)], limit=1) or \
            IrModel.search([('name', '=ilike', phrase)], limit=1)
        if rec and rec.model in self.env and not rec.transient:
            return rec.model, [], ['display_name']
        return None

    def free_text(self, text):
        t = normalize(text)
        if not t:
            return None
        if re.fullmatch(r'(hi|hello|hey|help|what can you do|thanks|thank you|ok|okay)', t):
            return self.reply(
                '👋 Hi! Ask me about your Odoo data, e.g. *"show unpaid invoices"*, '
                '*"how many customers"*, *"install crm module"* – or use the quick actions on the '
                'left (answered locally, free). Anything more complex goes to Claude.')
        m = re.fullmatch(r'(please )?install (the )?(.+?)( app| module| application)?', t)
        if m:
            return self.install(m.group(3))
        m = re.fullmatch(r'(how many|count|number of|total number of) (the )?(.+?)( are there| do (we|i) have| exist)?', t)
        if m:
            found = self.resolve_model(m.group(3))
            if found:
                model, dom, _f = found
                op = {'model': model, 'method': 'search_count', 'args': [dom], 'kwargs': {}}
                n, err = self.run_op(self.env, op)
                if err:
                    return self.reply(f'⚠️ {err}')
                return self.reply(f'⚡ There {"is" if n == 1 else "are"} **{n:,}** {m.group(3)}.',
                                  odoo_operation=op, op_result=n)
        m = re.fullmatch(r'(show|list|display|get|give me|see)( me)?( all| the| my)? (.+?)( list)?', t)
        if m:
            found = self.resolve_model(m.group(4))
            if found:
                model, dom, flds = found
                return self.query(m.group(4).title(), model, dom, flds, limit=100)
        return None

    def install(self, phrase):
        Mod = self.env['ir.module.module'].sudo()
        tech = phrase.strip().replace(' ', '_')
        mod = Mod.search([('name', '=', tech)], limit=1) or \
            Mod.search([('shortdesc', '=ilike', phrase.strip())], limit=1) or \
            Mod.search([('shortdesc', 'ilike', phrase.strip()), ('application', '=', True)], limit=1)
        if not mod:
            return None  # let Claude figure out what the user means
        ok, msg = self.install_module(self.env, mod.name)
        return self.reply(f'📦 **{mod.shortdesc or mod.name}** (`{mod.name}`)',
                          install_result={'success': ok, 'message': msg},
                          refresh_needed='reload' if ok and 'already' not in msg else False)


# ─────────────────────────────────────────────────────────────────────────────
def cache_lookup(env, text, ttl_days):
    Cache = env['claude.query.cache'].sudo()
    since = fields.Datetime.now() - timedelta(days=max(ttl_days or 1, 1))
    return Cache.search([('key', '=', cache_key(text)), ('write_date', '>=', since)], limit=1)


def cache_store(env, text, title, op, chart_type, excel_spec):
    if not op and not excel_spec:
        return
    if op and op.get('method') not in READ_METHODS:
        return
    Cache = env['claude.query.cache'].sudo()
    key = cache_key(text)
    vals = {'key': key, 'question': text[:500], 'title': (title or '')[:200],
            'op_json': json.dumps(op) if op else False,
            'chart_type': chart_type or False,
            'excel_json': json.dumps(excel_spec) if excel_spec else False}
    rec = Cache.search([('key', '=', key)], limit=1)
    rec.write(vals) if rec else Cache.create(vals)
