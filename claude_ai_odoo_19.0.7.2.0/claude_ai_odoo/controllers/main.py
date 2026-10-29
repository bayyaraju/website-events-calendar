# -*- coding: utf-8 -*-
import json, time, logging, traceback, re, io, base64, collections
from odoo import http, fields
from odoo.exceptions import AccessError
from odoo.http import request

from .local_engine import LocalEngine, cache_lookup, cache_store, normalize, grouped_spec, PERIODS, GRANULARITIES

_logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Core helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_active_key(env):
    config = env['claude.config'].sudo().get_active_config()
    env.cr.execute('SELECT api_key FROM claude_config WHERE id = %s', (config.id,))
    row = env.cr.fetchone()
    return (row[0] or '').strip() if row else '', config

# Models that refuse the `temperature` parameter (filled at runtime on first refusal)
_NO_TEMPERATURE_MODELS = set()

GROUP_USER  = 'claude_ai_odoo.group_claude_user'
GROUP_ADMIN = 'claude_ai_odoo.group_claude_admin'
# Never callable through the assistant, whatever the model
BLOCKED_METHODS = {
    'sudo', 'with_user', 'with_env', 'with_context', 'with_company', 'browse', 'env',
    'execute_kw', 'invalidate_cache', 'init', 'button_immediate_install',
    'button_immediate_uninstall', 'button_immediate_upgrade', 'button_uninstall',
}
BLOCKED_MODELS = {'ir.config_parameter', 'ir.rule', 'ir.model.access', 'res.users.apikeys',
                  'ir.cron', 'ir.actions.server', 'base.automation', 'ir.module.module'}


def _check_user(env, admin=False):
    """Only members of the Claude AI groups may use the assistant."""
    group = GROUP_ADMIN if admin else GROUP_USER
    if not env.user.has_group(group) and not env.is_superuser():
        raise AccessError('You need the "%s" access right to use this feature.'
                          % ('Claude AI / Administrator' if admin else 'Claude AI / User'))


def _own_session(env, session_id):
    """Return the session only if it belongs to the current user."""
    session = env['claude.session'].sudo().browse(int(session_id or 0)).exists()
    if not session or session.user_id.id != env.uid:
        return env['claude.session']
    return session


def _extract_block(text, tag):
    m = re.search(rf'```{tag}\s*([\s\S]+?)\s*```', text)
    if m:
        try: return json.loads(m.group(1))
        except: pass
    return None

def _safe_json(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)): return obj
    if isinstance(obj, dict): return {k: _safe_json(v) for k,v in obj.items()}
    if isinstance(obj, (list, tuple)): return [_safe_json(i) for i in obj]
    if hasattr(obj, '_name'): return [{'id': r.id} for r in obj]
    return str(obj)

# ─────────────────────────────────────────────────────────────────────────────
# Smart chart builder — converts query results into chart_spec automatically
# ─────────────────────────────────────────────────────────────────────────────

def _detect_chart_intent(user_msg):
    """Return (chart_type, label_field_hint, value_field_hint) from the user message, or None."""
    msg = user_msg.lower()
    chart_type = None
    if re.search(r'\b(pie|donut|doughnut)\b', msg): chart_type = 'pie'
    elif re.search(r'\b(line|trend|over time|monthly|weekly|daily)\b', msg): chart_type = 'line'
    elif re.search(r'\b(bar|column|histogram|compare|comparison)\b', msg): chart_type = 'bar'
    elif re.search(r'\bchart\b|\bgraph\b|\bvisuali', msg): chart_type = 'bar'
    return chart_type

def _auto_build_chart(records, chart_type, user_msg, title='', model=None, domain=None):
    """
    Build a chart_spec from raw search_read results.
    Automatically picks the best label column and value column.
    Groups and aggregates duplicates.
    """
    if not records or not isinstance(records, list):
        return None

    # Find label column (first string/char-like field, prefer partner_id / name / product_id)
    sample = records[0]
    all_keys = [k for k in sample.keys() if k != 'id']

    label_pref  = ['partner_id','product_id','categ_id','name','user_id','department_id','country_id','location_id','state']
    value_pref  = ['amount_total','amount_residual','qty_available','quantity','list_price','price_unit','product_qty','revenue']

    label_key = None
    for p in label_pref:
        if p in all_keys:
            label_key = p; break
    if not label_key:
        # pick first non-numeric field
        for k in all_keys:
            v = sample.get(k)
            if isinstance(v, (list, str)) and not isinstance(v, bool):
                label_key = k; break
    if not label_key and all_keys:
        label_key = all_keys[0]

    value_key = None
    for p in value_pref:
        if p in all_keys:
            value_key = p; break
    if not value_key:
        for k in all_keys:
            v = sample.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                value_key = k; break
    if not value_key:
        # fall back to count
        value_key = None

    # Extract label strings
    def get_label(rec):
        v = rec.get(label_key, '')
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return str(v[1])
        return str(v or 'Unknown')

    def get_value(rec):
        if value_key is None:
            return 1  # count mode
        v = rec.get(value_key, 0)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            v = v[1]
        try: return float(v or 0)
        except: return 0

    # Aggregate (sum values per label)
    agg = collections.OrderedDict()
    keys = {}
    for rec in records:
        lbl = get_label(rec)
        agg[lbl] = agg.get(lbl, 0) + get_value(rec)
        raw = rec.get(label_key)
        keys.setdefault(lbl, raw[0] if isinstance(raw, (list, tuple)) and len(raw) == 2 else raw)

    # Sort by value desc, take top 20 for charts
    sorted_items = sorted(agg.items(), key=lambda x: -x[1])[:20]
    labels = [item[0] for item in sorted_items]
    values = [round(item[1], 2) for item in sorted_items]

    if not labels:
        return None

    # Build title
    if not title:
        vname = (value_key or 'count').replace('_',' ').title()
        lname = (label_key or '').replace('_',' ').replace(' id','').title()
        title = f'{vname} by {lname}'

    spec = {
        'type': chart_type or 'bar',
        'title': title,
        'labels': labels,
        'datasets': [{'label': (value_key or 'count').replace('_',' ').title(), 'data': values}]
    }
    if model and label_key and label_key != 'name':
        # lets the UI open the underlying records when a bar / slice is clicked
        spec['keys'] = [keys.get(l) for l in labels]
        spec['drill'] = {'model': model, 'domain': domain or [], 'field': label_key}
    return spec

# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

def _build_system_prompt(env, base_prompt=''):
    user    = env.user
    company = env.company
    mods    = env['ir.module.module'].sudo().search([('state','=','installed')], order='name').mapped('name')
    models  = env['ir.model'].sudo().search([('transient','=',False)], order='model').read(['model','name'])
    avail   = env['ir.module.module'].sudo().search([('state','in',['uninstalled','to install'])], order='name').read(['name','shortdesc'])

    return f"""You are Claude, an AI assistant with DIRECT ACCESS to a live Odoo database.

STYLE — STRICT:
- ACT, don't ask. If the request is clear, emit the block(s) right away.
- Prose: max 2 short sentences. No plans, no "I will check", no recaps, no apologies, no option lists.
- Ask a question ONLY if a required value is truly missing. Never ask the user for record IDs.
- Results of earlier operations are in the history as "(Server result: …)" — trust them, never re-check.

MULTI-STEP TASKS (e.g. "create invoice for S00022"):
- Need data first (an ID, a state)? Emit a read odoo_op with "continue": true — the server runs it and
  sends you the result immediately; then emit the action in your next reply.
  ```odoo_op
  {{"model":"sale.order","method":"search_read","args":[[["name","=","S00022"]]],"kwargs":{{"fields":["id","state","invoice_status"]}},"continue":true}}
  ```
- Record actions use "ids": {{"model":"sale.order","method":"action_confirm","ids":[7]}}
  Invoice a confirmed sale order: {{"model":"sale.order","method":"create_invoice","ids":[7]}}
  Post an invoice: {{"model":"account.move","method":"action_post","ids":[9]}}

DATETIME: {fields.Datetime.now()}
COMPANY: {company.name} | CURRENCY: {company.currency_id.name}
USER: {user.name} ({user.login})
INSTALLED MODULES: {', '.join(mods[:80])}

══════════════════════════════════════════════════
CRITICAL CHART RULE — READ THIS CAREFULLY:
══════════════════════════════════════════════════
When the user asks for a CHART, you MUST emit BOTH blocks in the SAME response:
1. An ```odoo_op``` block to fetch the data (the server will execute it)
2. A ```chart_spec``` block with PLACEHOLDER data matching the expected shape

The server will automatically replace the chart_spec data with REAL aggregated data
from the odoo_op result. So your chart_spec just needs the correct type and title.

CHART REQUEST EXAMPLE — "Show a pie chart of revenue by customer":
```odoo_op
{{"model":"account.move","method":"search_read","args":[[["move_type","=","out_invoice"],["state","=","posted"]]],"kwargs":{{"fields":["partner_id","amount_total"],"limit":500}}}}
```
```chart_spec
{{"type":"pie","title":"Revenue by Customer"}}
```

ANOTHER EXAMPLE — "Bar chart of stock by product":
```odoo_op
{{"model":"stock.quant","method":"search_read","args":[[["location_id.usage","=","internal"]]],"kwargs":{{"fields":["product_id","quantity"],"limit":200}}}}
```
```chart_spec
{{"type":"bar","title":"Stock Levels by Product"}}
```

NOTE: The chart_spec does NOT need labels or datasets — the server builds those from real data.
You only need to provide "type" and "title". The server handles everything else.
══════════════════════════════════════════════════

BLOCK FORMATS:

Query data only (no chart):
```odoo_op
{{"model":"sale.order","method":"search_read","args":[[["state","=","sale"]]],"kwargs":{{"fields":["name","partner_id","amount_total","date_order"],"limit":80,"order":"date_order desc"}}}}
```

Excel report:
```excel_report
{{"filename":"sales_report.xlsx","sheets":[{{"name":"Sales","model":"sale.order","domain":[["state","in",["sale","done"]]],"fields":["name","partner_id","amount_total","state","date_order"],"field_labels":["Order","Customer","Total","Status","Date"],"limit":5000}}]}}
```

Create record:
```odoo_op
{{"model":"res.partner","method":"create","args":[{{"name":"John Doe","email":"john@example.com","customer_rank":1}}],"kwargs":{{}}}}
```

Install module:
```module_install
{{"module_name":"sale_management"}}
```

Batch import:
```batch_create
{{"model":"res.partner","records":[{{"name":"Alice","email":"alice@co.com"}}]}}
```

KEY MODELS:
- account.move: name,partner_id,amount_total,invoice_date,payment_state,state,move_type
- sale.order: name,partner_id,amount_total,state,date_order,user_id
- purchase.order: name,partner_id,amount_total,state,date_order
- product.product: name,list_price,qty_available,categ_id,default_code
- product.template: name,list_price,categ_id,type (valid values: 'consu','service','storable' — NEVER use 'product')
- res.partner: name,email,phone,city,customer_rank,supplier_rank (NO 'model' field — never include 'model' in fields list)
- hr.employee: name,department_id,job_id,work_email,active
- stock.quant: product_id,location_id,quantity
- res.users: name,login,email,active

ALL MODELS ({len(models)} total — sample):
{chr(10).join(f"  {m['model']}: {m['name']}" for m in models[:60])}

INSTALLABLE MODULES (sample):
{chr(10).join(f"  {m['name']}: {m.get('shortdesc','')}" for m in avail[:30])}

CRUD OPERATIONS — DETAILED GUIDE:
══════════════════════════════════════════════════
CREATE a record:
```odoo_op
{{"model":"res.partner","method":"create","args":[{{"name":"Acme Corp","email":"info@acme.com","customer_rank":1}}],"kwargs":{{}}}}
```

UPDATE / EDIT a record (IDs in args[0], vals in args[1]):
```odoo_op
{{"model":"res.partner","method":"write","args":[[42],{{"phone":"+1-555-9999"}}],"kwargs":{{}}}}
```

DELETE a record:
```odoo_op
{{"model":"sale.order","method":"unlink","args":[[7]],"kwargs":{{}}}}
```

INTERACTIVE FORM — emit crud_form for guided create/edit:
```crud_form
{{"action":"create","model":"res.partner","title":"New Customer","fields":[{{"name":"name","label":"Customer Name","type":"char","required":true}},{{"name":"email","label":"Email","type":"char"}},{{"name":"phone","label":"Phone","type":"char"}},{{"name":"customer_rank","label":"Is Customer","type":"integer","default":1}}]}}
```
For editing with current values use action=write and include id + value in each field.

CRUD RULES:
- When user says edit/update/change without values → search_read first, then crud_form
- After any create/write/unlink → follow-up search_read to show updated state
- For delete: describe what will be deleted before emitting unlink
══════════════════════════════════════════════════

RULES:
- ALWAYS emit odoo_op for any data request — never say "I will query" without the block
- For chart requests: emit odoo_op + chart_spec together in ONE response
- Never put placeholder data in chart_spec datasets — server fills them
- For interactive CRUD: use crud_form; for direct ops with known values: use odoo_op
- Be brief and direct; one short sentence before/after blocks is enough
- Format currency with commas; never show raw JSON in prose
- Always show results after CRUD operations
{base_prompt}"""

# ─────────────────────────────────────────────────────────────────────────────
# ORM executor
# ─────────────────────────────────────────────────────────────────────────────

def _execute_op(env, op):
    """Run an operation proposed by Claude AS THE CURRENT USER (Odoo access rights and
    record rules apply). Private/technical methods and security models are refused."""
    if not isinstance(op, dict):
        return None, 'Invalid operation.'
    model_name = op.get('model','')
    method     = op.get('method','') or ''
    args       = op.get('args', []) or []
    kwargs     = op.get('kwargs', {}) or {}
    blocked    = ['_sql','execute_kw','_cr','base_automation']
    if (any(b in method for b in blocked) or method.startswith('_')
            or method in BLOCKED_METHODS):
        return None, f'Method "{method}" is blocked.'
    if model_name not in env:
        return None, f'Model "{model_name}" not found.'
    if model_name in BLOCKED_MODELS:
        return None, f'Model "{model_name}" cannot be accessed through the assistant.'
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        return None, 'Invalid arguments.'
    try:
        obj = env[model_name]   # current user: access rights & record rules are enforced
        if method == 'search_read':
            domain = args[0] if args else []
            req_fields = kwargs.get('fields', [])
            # Filter out fields that don't exist on this model (e.g. 'model' on res.partner)
            if req_fields:
                valid_fnames = set(obj.fields_get().keys())
                req_fields = [f for f in req_fields if f in valid_fnames]
            result = obj.search_read(domain,
                req_fields,
                limit=kwargs.get('limit',200),
                offset=kwargs.get('offset',0),
                order=kwargs.get('order'))
        elif method == 'search_count':
            result = obj.search_count(args[0] if args else [])
        elif method == 'read':
            ids  = args[0] if args else []
            flds = args[1] if len(args)>1 else kwargs.get('fields',[])
            result = obj.browse(ids).read(flds)
        elif method == 'create':
            vals = args[0] if args else kwargs
            # Strip any keys that are not valid field names on this model
            valid_fnames = set(obj.fields_get().keys())
            vals = {k: v for k, v in vals.items() if k in valid_fnames}
            rec = obj.create(vals)
            result = {'id': rec.id, 'name': getattr(rec, 'name', str(rec.id))}
        elif method == 'write':
            ids  = args[0] if args else []
            vals = args[1] if len(args)>1 else kwargs
            # Strip any keys that are not valid field names on this model
            valid_fnames = set(obj.fields_get().keys())
            vals = {k: v for k, v in vals.items() if k in valid_fnames}
            result = obj.browse(ids).write(vals)
        elif method == 'unlink':
            ids    = args[0] if args else []
            result = obj.browse(ids).unlink()
        elif method == 'fields_get':
            result = obj.fields_get(kwargs.get('allfields'),
                kwargs.get('attributes',['string','type','help']))
        elif method == 'name_search':
            result = obj.name_search(
                args[0] if args else '',
                args[1] if len(args)>1 else [],
                limit=kwargs.get('limit',20))
        else:
            ids = op.get('ids')
            if ids:
                obj = obj.browse([int(i) for i in (ids if isinstance(ids, list) else [ids])]).exists()
                if not obj:
                    return None, f'No {model_name} record with id(s) {ids}.'
            alias = ACTION_ALIASES.get((model_name, method))
            if alias:
                result = alias(obj)
            else:
                fn = getattr(obj, method, None)
                if fn is None: return None, f'Method "{method}" not found on {model_name}.'
                result = fn(*args, **kwargs)
            if hasattr(result, '_name'):
                result = [{'id': r.id, 'name': r.display_name} for r in result[:50]]
            elif isinstance(result, dict) and str(result.get('type', '')).startswith('ir.actions'):
                result = {'done': True, 'action': result.get('name') or result.get('res_model')}
            elif result is None:
                result = {'done': True}
        return result, None
    except AccessError as e:
        return None, f'Access denied: {e}'
    except Exception as e:
        return None, str(e)


def _invoice_orders(orders):
    """Create draft invoices for confirmed sale orders (standard Odoo flow)."""
    orders = orders.filtered(lambda o: o.state == 'sale' and o.invoice_status == 'to invoice')
    if not orders:
        raise ValueError('Nothing to invoice: the order must be confirmed and "To Invoice".')
    return orders._create_invoices()


# Business actions Claude may run on records although the ORM method is "private".
ACTION_ALIASES = {
    ('sale.order', 'create_invoice'): _invoice_orders,
}

READ_ONLY_METHODS = {'search_read', 'search_count', 'read', 'name_search', 'fields_get', 'read_group'}


def _result_note(res, limit=1500):
    """Compact JSON of an operation result, stored in the conversation so Claude
    always knows what actually happened (no re-checking, no guessing)."""
    try:
        txt = json.dumps(_safe_json(res), default=str, separators=(',', ':'))
    except Exception:
        txt = str(res)
    return txt if len(txt) <= limit else txt[:limit] + '…(truncated)'


class _OpError(Exception):
    pass


def _in_savepoint(env, fn, *a):
    """Run fn in a DB savepoint: a failed operation is rolled back alone and never
    breaks the rest of the request (chat history, token counters...)."""
    try:
        with env.cr.savepoint():
            res, err = fn(env, *a)
            if err:
                raise _OpError(err)
        return res, None
    except _OpError as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)



# Old IANA aliases that some PostgreSQL builds (system tzdata without "backward"
# links) do not know – grouping by date would otherwise fail with
# 'time zone "Asia/Calcutta" not recognized'.
_TZ_ALIASES = {
    'Asia/Calcutta': 'Asia/Kolkata', 'Asia/Saigon': 'Asia/Ho_Chi_Minh',
    'Asia/Katmandu': 'Asia/Kathmandu', 'Asia/Rangoon': 'Asia/Yangon',
    'Asia/Dacca': 'Asia/Dhaka', 'Europe/Kiev': 'Europe/Kyiv',
    'America/Buenos_Aires': 'America/Argentina/Buenos_Aires',
    'Pacific/Truk': 'Pacific/Chuuk', 'Pacific/Ponape': 'Pacific/Pohnpei',
    'US/Eastern': 'America/New_York', 'US/Central': 'America/Chicago',
    'US/Mountain': 'America/Denver', 'US/Pacific': 'America/Los_Angeles',
}
_PG_TZ_OK = {}


def _pg_tz_env(env):
    """Return env whose context tz is one PostgreSQL understands."""
    tz = env.context.get('tz') or env.user.tz
    if not tz:
        return env
    if tz not in _PG_TZ_OK:
        def known(name):
            env.cr.execute("SELECT 1 FROM pg_timezone_names WHERE name = %s", [name])
            return bool(env.cr.fetchone())
        fixed = tz if known(tz) else next(
            (a for a in (_TZ_ALIASES.get(tz),) if a and known(a)), 'UTC')
        _PG_TZ_OK[tz] = fixed
    fixed = _PG_TZ_OK[tz]
    return env if fixed == tz and env.context.get('tz') == tz else env(context=dict(env.context, tz=fixed))

_execute_op_raw = _execute_op


def _execute_op(env, op):
    return _in_savepoint(_pg_tz_env(env), _execute_op_raw, op)

# ─────────────────────────────────────────────────────────────────────────────
# Excel builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_excel(env, spec):
    try: import openpyxl
    except ImportError:
        raise RuntimeError('Python package "openpyxl" is not installed on the server (pip install openpyxl).')
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.chart import BarChart, Reference

    wb = openpyxl.Workbook(); wb.remove(wb.active)
    hf   = Font(bold=True, color='FFFFFF', size=11, name='Calibri')
    hfil = PatternFill('solid', fgColor='4F46E5')
    ha   = Alignment(horizontal='center', vertical='center', wrap_text=True)
    thin = Side(style='thin', color='D1D5DB')
    brd  = Border(left=thin,right=thin,top=thin,bottom=thin)
    alt  = PatternFill('solid', fgColor='EEF2FF')
    tf   = Font(bold=True, size=14, color='1E1B4B', name='Calibri')
    sf   = Font(size=10, color='6B7280', name='Calibri', italic=True)

    for sh_spec in spec.get('sheets', []):
        ws    = wb.create_sheet(title=str(sh_spec.get('name','Sheet'))[:31])
        model = sh_spec.get('model','')
        flds  = sh_spec.get('fields', [])
        lbls  = sh_spec.get('field_labels', flds)
        dom   = sh_spec.get('domain', [])
        lim   = sh_spec.get('limit', 10000)
        order = sh_spec.get('order')
        recs  = []
        if model and model in env:
            recs = env[model].search_read(dom, flds, limit=lim, order=order)

        ncols = max(len(flds), 1)
        last_col = get_column_letter(ncols)

        # Title
        ws.merge_cells(f'A1:{last_col}1')
        c = ws['A1']; c.value = sh_spec.get('name', model)
        c.font = tf; c.alignment = Alignment(horizontal='center',vertical='center')
        c.fill = PatternFill('solid', fgColor='EDE9FE'); ws.row_dimensions[1].height = 28

        # Subtitle
        ws.merge_cells(f'A2:{last_col}2')
        c = ws['A2']
        c.value = f'Generated: {fields.Datetime.now().strftime("%d %b %Y %H:%M")} | {len(recs)} records'
        c.font = sf; c.alignment = Alignment(horizontal='center'); ws.row_dimensions[2].height = 18

        # Headers
        ws.row_dimensions[3].height = 22
        for ci, lbl in enumerate(lbls, 1):
            c = ws.cell(row=3, column=ci, value=lbl)
            c.font=hf; c.fill=hfil; c.alignment=ha; c.border=brd

        # Data
        for ri, rec in enumerate(recs, 4):
            for ci, fn in enumerate(flds, 1):
                v = rec.get(fn)
                if isinstance(v,(list,tuple)) and len(v)==2: v=v[1]
                elif v is False: v=''
                c = ws.cell(row=ri, column=ci, value=v)
                c.border=brd; c.alignment=Alignment(vertical='center')
                if ri%2==0: c.fill=alt

        # Column widths + autofilter + freeze
        for ci in range(1, ncols+1):
            vals_s = [ws.cell(r,ci).value for r in range(3,min(53,len(recs)+4))]
            ml = max((len(str(v)) for v in vals_s if v is not None), default=8)
            ws.column_dimensions[get_column_letter(ci)].width = min(ml+4,48)
        ws.freeze_panes = 'A4'
        if flds: ws.auto_filter.ref = f'A3:{last_col}3'

        # Summary
        ws.cell(row=len(recs)+5, column=1, value=f'Total: {len(recs)} records').font = Font(italic=True,color='6B7280',size=9)

        # Embed mini bar chart (up to 50 rows, first numeric column)
        num_col = next((ci for ci,fn in enumerate(flds,1) if recs and isinstance(recs[0].get(fn),(int,float))), None)
        if num_col and 2 <= len(recs) <= 50:
            try:
                ch = BarChart(); ch.type='col'; ch.style=10; ch.height=12; ch.width=20
                ch.title = sh_spec.get('name','')
                ref = Reference(ws,min_col=num_col,max_col=num_col,min_row=3,max_row=len(recs)+3)
                ch.add_data(ref,titles_from_data=True); ws.add_chart(ch,f'{get_column_letter(ncols+2)}4')
            except: pass

    buf=io.BytesIO(); wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode()

# ─────────────────────────────────────────────────────────────────────────────
# Module installer
# ─────────────────────────────────────────────────────────────────────────────

def _install_module(env, module_name):
    if not (env.user.has_group('base.group_system') and env.user.has_group(GROUP_ADMIN)):
        return False, 'Only Claude AI administrators with Settings access can install modules.'
    mod = env['ir.module.module'].sudo().search([('name','=',module_name)], limit=1)
    if not mod: return False, f'Module "{module_name}" not found.'
    if mod.state == 'installed': return True, f'Module "{module_name}" is already installed.'
    try:
        mod.button_immediate_install()
        return True, f'Module "{module_name}" installed successfully.'
    except Exception as e:
        return False, f'Install failed: {e}'

# ─────────────────────────────────────────────────────────────────────────────
# Batch create (import)
# ─────────────────────────────────────────────────────────────────────────────

def _batch_create(env, spec):
    model_name = spec.get('model','')
    records    = spec.get('records', [])
    if model_name not in env: return None, f'Model "{model_name}" not found.'
    if model_name in BLOCKED_MODELS:
        return None, f'Model "{model_name}" cannot be imported through the assistant.'
    if not isinstance(records, list) or not records:
        return None, 'Nothing to import.'
    try:
        valid = set(env[model_name].fields_get().keys())
        records = [{k: v for k, v in r.items() if k in valid} for r in records if isinstance(r, dict)]
        created = env[model_name].create(records)
        return {'created': len(created), 'ids': created.ids}, None
    except AccessError as e:
        return None, f'Access denied: {e}'
    except Exception as e:
        return None, str(e)

# ─────────────────────────────────────────────────────────────────────────────
# Attachment parser
# ─────────────────────────────────────────────────────────────────────────────

def _parse_attachment(b64, filename):
    try:
        raw = base64.b64decode(b64)
        fn  = (filename or '').lower()
        if fn.endswith('.csv') or fn.endswith('.txt'):
            import csv
            text   = raw.decode('utf-8-sig', errors='replace')
            reader = csv.DictReader(io.StringIO(text))
            return [dict(r) for r in reader]
        elif fn.endswith(('.xlsx','.xls')):
            try: import openpyxl
            except ImportError:
                import subprocess, sys
                subprocess.run([sys.executable,'-m','pip','install','openpyxl','-q'],timeout=60)
                import openpyxl
            wb   = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
            ws   = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows: return []
            hdrs = [str(h or '').strip() for h in rows[0]]
            return [dict(zip(hdrs,[str(v or '') for v in row])) for row in rows[1:] if any(v for v in row)]
    except Exception as e:
        _logger.warning('Attachment parse failed: %s', e)
    return []

# ─────────────────────────────────────────────────────────────────────────────
# Controller
# ─────────────────────────────────────────────────────────────────────────────

class ClaudeController(http.Controller):

    @http.route('/claude_ai/session', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def get_session(self, **kw):
        env = request.env
        _check_user(env)
        _, config = _get_active_key(env)
        session = env['claude.session'].search(
            [('user_id','=',env.uid),('state','=','active')], order='id desc', limit=1)
        if not session:
            session = env['claude.session'].create({'config_id':config.id,'user_id':env.uid})
        return {'session_id': session.id, 'ok': True}

    @http.route('/claude_ai/config', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def get_config(self, **kw):
        try:
            _check_user(request.env)
            api_key, config = _get_active_key(request.env)
            return {'model_name': config._effective_model(), 'has_api_key': bool(api_key),
                    'is_admin': request.env.user.has_group(GROUP_ADMIN),
                    'local_mode': config.local_mode,
                    'savings': config.sudo().savings_summary()}
        except Exception as e:
            return {'error': str(e)}

    @http.route('/claude_ai/chat', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def chat(self, session_id, user_message, attachments=None, quick_key=None, **kw):
        env = request.env
        t0  = time.time()

        try:
            _check_user(env)
        except AccessError as e:
            return {'error': True, 'message': str(e)}
        session = _own_session(env, session_id)
        if not session:
            return {'error': True, 'message': 'Session not found.'}
        if not (user_message or '').strip() and not attachments:
            return {'error': True, 'message': 'Empty message.'}

        api_key, config = _get_active_key(env)

        # ── 1. Free answers first: local engine, then answer cache ─────────
        force_ai = bool(re.match(r'^\s*(!|ai:)', user_message or '', re.I))
        if force_ai:
            user_message = re.sub(r'^\s*(!|ai:)\s*', '', user_message, flags=re.I)
        if not force_ai and not attachments:
            local = self._answer_without_api(env, config, session, user_message, quick_key)
            if local:
                return local
        if not api_key:
            return {'error': True, 'message': 'API key not configured. Go to Claude AI → Configuration. '
                                              '(Quick actions and simple questions still work without a key.)'}

        try:
            import anthropic
        except ImportError:
            return {'error': True, 'message': 'Package "anthropic" not installed. Run: pip install anthropic'}

        # ── Attachment handling ────────────────────────────────────────────
        att_context      = ''
        parsed_att_rows  = None
        parsed_att_name  = ''
        if attachments:
            for att in (attachments or []):
                rows = _parse_attachment(att.get('data',''), att.get('filename',''))
                if rows:
                    parsed_att_rows = rows
                    parsed_att_name = att.get('filename','file')
                    preview = rows[:5]
                    cols    = ', '.join(rows[0].keys()) if rows else 'none'
                    att_context += f'\n\n[ATTACHMENT: {parsed_att_name} — {len(rows)} rows]\nColumns: {cols}\nSample:\n'
                    for r in preview:
                        att_context += '  ' + ' | '.join(f'{k}={v}' for k,v in r.items()) + '\n'
                    att_context += f'\nIf user wants to import, emit batch_create with ALL {len(rows)} records.'

        full_msg = user_message + att_context
        session.add_message('user', full_msg)
        env['claude.message'].sudo().create({'session_id':session.id,'role':'user','content':user_message})

        # ── Call Claude ────────────────────────────────────────────────────
        system = _build_system_prompt(env, config.system_prompt or '')
        model  = config._effective_model()
        max_t  = max(config.max_tokens or 8096, 1)
        client = anthropic.Anthropic(api_key=api_key,
                                     timeout=float(config.request_timeout or 60),
                                     max_retries=2)

        def ask():
            req = dict(
                model=model, max_tokens=max_t,
                # Prompt caching: the large system prompt is re-used between turns
                system=[{'type': 'text', 'text': system,
                         'cache_control': {'type': 'ephemeral'}}] if config.use_prompt_cache else system,
                messages=session.get_api_history())
            if (config.temperature is not False and config.temperature is not None
                    and model not in _NO_TEMPERATURE_MODELS):
                req['temperature'] = max(0.0, min(1.0, config.temperature))
            try:
                response = client.messages.create(**req)
            except anthropic.BadRequestError as e:
                # Newer models reject sampling parameters: retry once without them.
                if 'temperature' in req and 'temperature' in str(e).lower():
                    _NO_TEMPERATURE_MODELS.add(model)
                    req.pop('temperature')
                    _logger.info('Claude: model %s does not accept temperature; retrying without it', model)
                    response = client.messages.create(**req)
                else:
                    raise
            text = ''.join(getattr(b, 'text', '') for b in (response.content or [])
                           if getattr(b, 'type', '') == 'text')
            u = response.usage
            n = (u.input_tokens or 0) + (u.output_tokens or 0) + \
                (getattr(u, 'cache_creation_input_tokens', 0) or 0) + \
                (getattr(u, 'cache_read_input_tokens', 0) or 0)
            return text, n

        try:
            ai_text, tokens_used = ask()
            # Multi-step: Claude asked for data first ("continue": true) -> run the read
            # and hand the result straight back, so the task finishes in ONE user turn.
            for _round in range(4):
                step = _extract_block(ai_text, 'odoo_op')
                if not (isinstance(step, dict) and step.get('continue')
                        and step.get('method') in READ_ONLY_METHODS):
                    break
                res, err = _execute_op(env, step)
                session.add_message('assistant', ai_text)
                session.add_message('user', '(Server result: %s)\nContinue the task now.'
                                    % _result_note({'error': err} if err else res))
                more, n = ask()
                ai_text, tokens_used = more, tokens_used + n
        except Exception as e:
            _logger.error('Claude API error: %s', traceback.format_exc())
            session.drop_last_user_message()
            return {'error': True, 'message': f'Claude API error: {e}'}

        session.sudo().write({'total_tokens': session.total_tokens + tokens_used})
        config.sudo()._bump('stat_api_calls')
        config.sudo()._bump('stat_api_tokens', tokens_used)
        msg_rec = env['claude.message'].sudo().create({
            'session_id': session.id, 'role': 'assistant',
            'content': ai_text, 'tokens': tokens_used})

        # ── Extract blocks ─────────────────────────────────────────────────
        odoo_op    = _extract_block(ai_text, 'odoo_op')
        excel_spec = _extract_block(ai_text, 'excel_report')
        chart_spec = _extract_block(ai_text, 'chart_spec')
        mod_spec   = _extract_block(ai_text, 'module_install')
        batch_spec = _extract_block(ai_text, 'batch_create')
        crud_form  = _extract_block(ai_text, 'crud_form')

        # ── Detect chart intent even if no chart_spec emitted ─────────────
        # This is the KEY FIX: if the user asked for a chart but Claude only emitted
        # an odoo_op without a chart_spec, we still build the chart from the results.
        chart_intent = _detect_chart_intent(user_message)
        if chart_intent and not chart_spec:
            # Force chart_spec so auto-build will trigger after query executes
            chart_spec = {'type': chart_intent, 'title': ''}

        # ── Execute odoo_op ────────────────────────────────────────────────
        write_methods  = ('create','write','unlink')
        needs_confirm  = False
        op_result      = None
        install_result = None
        batch_result   = None

        if odoo_op:
            method = odoo_op.get('method','')
            if (method in write_methods and config.require_confirmation) or \
                    (method == 'unlink' and config.confirm_deletes):
                needs_confirm = True
            else:
                res, err = _execute_op(env, odoo_op)
                op_result = res if not err else {'error': err}

        hist = ai_text
        if odoo_op and not needs_confirm:
            hist += '\n\n(Server result: %s)' % _result_note(op_result)
        elif needs_confirm:
            hist += '\n\n(Server: waiting for the user to confirm this operation.)'
        session.add_message('assistant', hist)

        # ── Auto-build chart from real query results ───────────────────────
        # This is the CORE FIX: whenever we have a chart request + real data,
        # we aggregate the actual records into labels/datasets ourselves.
        if chart_spec and isinstance(op_result, list) and op_result:
            chart_type  = chart_spec.get('type') or chart_intent or 'bar'
            chart_title = chart_spec.get('title','')
            built = _auto_build_chart(op_result, chart_type, user_message, chart_title,
                                     model=odoo_op.get('model') if odoo_op else None,
                                     domain=((odoo_op or {}).get('args') or [[]])[0])
            if built:
                chart_spec = built
                _logger.info('Auto-built %s chart with %d data points', chart_type, len(built.get('labels',[])))
            else:
                chart_spec = None  # don't render empty chart

        # ── Module install ─────────────────────────────────────────────────
        if mod_spec and not needs_confirm:  # admin check inside _install_module
            ok, msg = _install_module(env, mod_spec.get('module_name',''))
            install_result = {'success': ok, 'message': msg}

        # ── Batch import ───────────────────────────────────────────────────
        if batch_spec and not needs_confirm:
            if parsed_att_rows and not batch_spec.get('records'):
                batch_spec['records'] = parsed_att_rows
            res, err = _in_savepoint(env, _batch_create, batch_spec)
            batch_result = res if not err else {'error': err}

        # ── Excel ──────────────────────────────────────────────────────────
        excel_b64 = excel_fn = None
        if excel_spec:
            try:
                excel_b64 = _build_excel(env, excel_spec)
                excel_fn  = excel_spec.get('filename','report.xlsx')
            except Exception as ex:
                _logger.error('Excel build failed: %s', ex)

        # ── Refresh hints for the UI ───────────────────────────────────────
        refresh_needed = False
        if odoo_op and not needs_confirm and odoo_op.get('method') not in READ_ONLY_METHODS \
                and not (isinstance(op_result, dict) and op_result.get('error')):
            refresh_needed = 'soft'
        if batch_result and not batch_result.get('error'):
            refresh_needed = 'soft'
        if install_result and install_result.get('success') and 'already' not in install_result.get('message', ''):
            refresh_needed = 'reload'

        # ── Remember read-only answers: next time the same question is free ─
        if config.cache_enabled and not needs_confirm and not mod_spec and not batch_spec \
                and not crud_form and not attachments and not refresh_needed \
                and not (isinstance(op_result, dict) and op_result.get('error')):
            try:
                title = re.sub(r'[#*_`>|]', '', ai_text.strip().split('\n')[0]).strip()[:120]
                cache_store(env, user_message, title, odoo_op,
                            (chart_spec or {}).get('type') if chart_spec else None, excel_spec)
            except Exception:
                _logger.warning('Claude cache store failed', exc_info=True)

        elapsed = int((time.time()-t0)*1000)
        _logger.info('Claude: %dms, %d tokens', elapsed, tokens_used)

        return {
            'message':            ai_text,
            'message_id':         msg_rec.id,
            'tokens_used':        tokens_used,
            'total_tokens':       session.total_tokens,
            'needs_confirmation': needs_confirm,
            'odoo_operation':     odoo_op,
            'op_result':          _safe_json(op_result),
            'excel_b64':          excel_b64,
            'excel_filename':     excel_fn,
            'chart_spec':         chart_spec,
            'install_result':     install_result,
            'batch_result':       batch_result,
            'crud_form':          crud_form,
            'source':             'ai',
            'refresh_needed':     refresh_needed,
            'savings':            config.sudo().savings_summary(),
        }

    def _answer_without_api(self, env, config, session, user_message, quick_key=None):
        """Answer from the local engine or the answer cache. Returns a chat response or None."""
        env = _pg_tz_env(env)
        engine = LocalEngine(env, _execute_op, _build_excel, _auto_build_chart, _install_module)
        engine.invoice_orders = _invoice_orders
        res = None
        try:
            with env.cr.savepoint():   # a failed local query must not abort the request
                if quick_key:
                    res = engine.quick(quick_key)
                if res is None and config.local_mode:
                    res = engine.free_text(user_message)
                if res is None and config.cache_enabled:
                    hit = cache_lookup(env, user_message, config.cache_ttl_days)
                    if hit:
                        op = json.loads(hit.op_json) if hit.op_json else None
                        op_result = chart_spec = excel_b64 = excel_fn = None
                        if op:
                            op_result, err = _execute_op(env, op)
                            if err:
                                op = None
                        if hit.excel_json:
                            spec = json.loads(hit.excel_json)
                            excel_b64, excel_fn = _build_excel(env, spec), spec.get('filename', 'report.xlsx')
                        if op or excel_b64:
                            if hit.chart_type and isinstance(op_result, list) and op_result:
                                chart_spec = _auto_build_chart(op_result, hit.chart_type, user_message, hit.title or '',
                                                               model=op.get('model'), domain=(op.get('args') or [[]])[0])
                            hit.sudo().write({'hits': hit.hits + 1})
                            res = {'message': f'♻️ **{(hit.title or "Answer").strip()}**\n\nFresh data from your database '
                                              f'(same question answered before – no AI call needed).',
                                   'source': 'cache', 'tokens_used': 0, 'odoo_operation': op,
                                   'op_result': op_result, 'chart_spec': chart_spec,
                                   'excel_b64': excel_b64, 'excel_filename': excel_fn}
        except Exception as e:
            _logger.warning('Local answer failed, falling back to Claude: %s', e)
            res = None
        if not res:
            return None
        # keep the conversation coherent for later Claude calls
        session.add_message('user', user_message)
        note = res.get('message', '')
        if res.get('op_result') is not None:
            note += '\n\n(Server result: %s)' % _result_note(res.get('op_result'))
        session.add_message('assistant', note)
        env['claude.message'].sudo().create({'session_id': session.id, 'role': 'user', 'content': user_message})
        msg = env['claude.message'].sudo().create({'session_id': session.id, 'role': 'assistant',
                                                     'content': res.get('message', ''), 'tokens': 0})
        config.sudo()._bump('stat_cache' if res.get('source') == 'cache' else 'stat_local')
        res.setdefault('odoo_operation', None)
        res['op_result'] = _safe_json(res.get('op_result'))
        res.update({'message_id': msg.id, 'total_tokens': session.total_tokens,
                    'needs_confirmation': False,
                    'refresh_needed': res.get('refresh_needed', False),
                    'savings': config.sudo().savings_summary()})
        return res

    @http.route('/claude_ai/chart_data', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def chart_data(self, src=None, period=None, granularity=None, chart_type=None, **kw):
        """Re-aggregate an interactive chart (period / granularity switch). Runs with the
        current user's access rights; model, fields and options are validated."""
        env = request.env
        try:
            _check_user(env)
            src = src or {}
            model = src.get('model')
            if model not in env or model in BLOCKED_MODELS:
                raise ValueError('Model not available.')
            fields_ = env[model]._fields
            groupby, measure = str(src.get('groupby') or ''), str(src.get('measure') or '')
            gfield, _s, gran = groupby.partition(':')
            if gfield not in fields_ or (measure != '__count' and (measure not in fields_
                    or fields_[measure].type not in ('integer', 'float', 'monetary'))):
                raise ValueError('Invalid chart fields.')
            if granularity:
                if granularity not in GRANULARITIES or not gran:
                    raise ValueError('Invalid granularity.')
                groupby = f'{gfield}:{granularity}'
            period = period or src.get('period')
            if period and period not in PERIODS:
                raise ValueError('Invalid period.')
            date_field = src.get('date_field')
            if date_field and date_field.split('.')[0] not in fields_:
                raise ValueError('Invalid date field.')
            domain = src.get('domain') or []
            if not isinstance(domain, list):
                raise ValueError('Invalid domain.')
            limit = src.get('limit')
            limit = int(limit) if limit else None
            order = src.get('order')
            if order and not re.fullmatch(r'[\w.:]+( (asc|desc))?', str(order)):
                order = None
            if order and order.startswith(gfield + ':'):
                order = f'{groupby} asc'
            ctype = chart_type if chart_type in ('bar', 'line', 'pie', 'doughnut') else 'bar'
            spec, rows = grouped_spec(_pg_tz_env(env), model, domain, groupby, measure, ctype,
                                      src.get('title') or 'Chart', limit=limit, order=order,
                                      date_field=date_field, period=period)
            return {'spec': spec, 'rows': rows}
        except Exception as e:
            return {'error': str(e)}

    @http.route('/claude_ai/execute', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def execute(self, operation, **kw):
        try:
            _check_user(request.env)
        except AccessError as e:
            return {'success': False, 'error': str(e)}
        result, error = _execute_op(request.env, operation)
        if error: return {'success': False, 'error': error}
        method = (operation or {}).get('method', '')
        return {'success': True, 'result': _safe_json(result),
                'refresh_needed': 'soft' if method in ('create', 'write', 'unlink') else False}

    @http.route('/claude_ai/install_module', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def install_module(self, module_name, **kw):
        ok, msg = _install_module(request.env, module_name)
        return {'success': ok, 'message': msg}

    @http.route('/claude_ai/clear', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def clear_session(self, session_id, **kw):
        _check_user(request.env)
        session = _own_session(request.env, session_id)
        if session: session.sudo().action_clear()
        _, config = _get_active_key(request.env)
        new_s = request.env['claude.session'].create({'config_id':config.id,'user_id':request.env.uid})
        return {'ok': True, 'new_session_id': new_s.id}
