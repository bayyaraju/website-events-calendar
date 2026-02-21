# -*- coding: utf-8 -*-
import json, time, logging, traceback, re, io, base64, collections
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Core helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_active_key(env):
    config = env['claude.config'].sudo().get_active_config()
    env.cr.execute('SELECT api_key FROM claude_config WHERE id = %s', (config.id,))
    row = env.cr.fetchone()
    return (row[0] or '').strip() if row else '', config

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

def _auto_build_chart(records, chart_type, user_msg, title=''):
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
    for rec in records:
        lbl = get_label(rec)
        agg[lbl] = agg.get(lbl, 0) + get_value(rec)

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

    return {
        'type': chart_type or 'bar',
        'title': title,
        'labels': labels,
        'datasets': [{'label': (value_key or 'count').replace('_',' ').title(), 'data': values}]
    }

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
- Be conversational; guide users on Odoo workflows when asked
- Format currency with commas; never show raw JSON in prose
- Always show results after CRUD operations
{base_prompt}"""

# ─────────────────────────────────────────────────────────────────────────────
# ORM executor
# ─────────────────────────────────────────────────────────────────────────────

def _execute_op(env, op):
    model_name = op.get('model','')
    method     = op.get('method','')
    args       = op.get('args', [])
    kwargs     = op.get('kwargs', {})
    blocked    = ['_sql','execute_kw','_cr','base_automation']
    if any(b in method for b in blocked):
        return None, f'Method "{method}" is blocked.'
    if model_name not in env:
        return None, f'Model "{model_name}" not found.'
    try:
        obj = env[model_name].sudo()
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
            fn = getattr(obj, method, None)
            if fn is None: return None, f'Method "{method}" not found on {model_name}.'
            result = fn(*args, **kwargs)
        return result, None
    except Exception as e:
        return None, str(e)

# ─────────────────────────────────────────────────────────────────────────────
# Excel builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_excel(env, spec):
    try: import openpyxl
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable,'-m','pip','install','openpyxl','-q'], timeout=60)
        import openpyxl
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
            recs = env[model].sudo().search_read(dom, flds, limit=lim, order=order)

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
    try:
        created = env[model_name].sudo().create(records)
        return {'created': len(created), 'ids': created.ids}, None
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
        _, config = _get_active_key(env)
        session = env['claude.session'].search(
            [('user_id','=',env.uid),('state','=','active')], order='id desc', limit=1)
        if not session:
            session = env['claude.session'].create({'config_id':config.id,'user_id':env.uid})
        return {'session_id': session.id, 'ok': True}

    @http.route('/claude_ai/config', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def get_config(self, **kw):
        try:
            api_key, config = _get_active_key(request.env)
            return {'model_name': config.model_name, 'has_api_key': bool(api_key)}
        except Exception as e:
            return {'error': str(e)}

    @http.route('/claude_ai/chat', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def chat(self, session_id, user_message, attachments=None, **kw):
        env = request.env
        t0  = time.time()

        session = env['claude.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': True, 'message': 'Session not found.'}

        api_key, config = _get_active_key(env)
        if not api_key:
            return {'error': True, 'message': 'API key not configured. Go to Claude AI → Configuration.'}

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
        model  = config.model_name or 'claude-sonnet-4-5'
        max_t  = max(config.max_tokens or 8096, 1)
        try:
            client   = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model, max_tokens=max_t,
                system=system, messages=session.get_history())
            ai_text    = response.content[0].text if response.content else ''
            tokens_used = response.usage.input_tokens + response.usage.output_tokens
        except Exception as e:
            _logger.error('Claude API error: %s', traceback.format_exc())
            return {'error': True, 'message': f'Claude API error: {e}'}

        session.add_message('assistant', ai_text)
        session.sudo().write({'total_tokens': session.total_tokens + tokens_used})
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
            if method in write_methods and config.require_confirmation:
                needs_confirm = True
            else:
                res, err = _execute_op(env, odoo_op)
                op_result = res if not err else {'error': err}

        # ── Auto-build chart from real query results ───────────────────────
        # This is the CORE FIX: whenever we have a chart request + real data,
        # we aggregate the actual records into labels/datasets ourselves.
        if chart_spec and isinstance(op_result, list) and op_result:
            chart_type  = chart_spec.get('type') or chart_intent or 'bar'
            chart_title = chart_spec.get('title','')
            built = _auto_build_chart(op_result, chart_type, user_message, chart_title)
            if built:
                chart_spec = built
                _logger.info('Auto-built %s chart with %d data points', chart_type, len(built.get('labels',[])))
            else:
                chart_spec = None  # don't render empty chart

        # ── Module install ─────────────────────────────────────────────────
        if mod_spec and not needs_confirm:
            ok, msg = _install_module(env, mod_spec.get('module_name',''))
            install_result = {'success': ok, 'message': msg}

        # ── Batch import ───────────────────────────────────────────────────
        if batch_spec and not needs_confirm:
            if parsed_att_rows and not batch_spec.get('records'):
                batch_spec['records'] = parsed_att_rows
            res, err = _batch_create(env, batch_spec)
            batch_result = res if not err else {'error': err}

        # ── Excel ──────────────────────────────────────────────────────────
        excel_b64 = excel_fn = None
        if excel_spec:
            try:
                excel_b64 = _build_excel(env, excel_spec)
                excel_fn  = excel_spec.get('filename','report.xlsx')
            except Exception as ex:
                _logger.error('Excel build failed: %s', ex)

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
        }

    @http.route('/claude_ai/execute', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def execute(self, operation, **kw):
        result, error = _execute_op(request.env, operation)
        if error: return {'success': False, 'error': error}
        return {'success': True, 'result': _safe_json(result)}

    @http.route('/claude_ai/install_module', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def install_module(self, module_name, **kw):
        ok, msg = _install_module(request.env, module_name)
        return {'success': ok, 'message': msg}

    @http.route('/claude_ai/clear', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def clear_session(self, session_id, **kw):
        session = request.env['claude.session'].sudo().browse(session_id)
        if session.exists(): session.action_clear()
        _, config = _get_active_key(request.env)
        new_s = request.env['claude.session'].create({'config_id':config.id,'user_id':request.env.uid})
        return {'ok': True, 'new_session_id': new_s.id}
