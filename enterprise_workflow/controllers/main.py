# -*- coding: utf-8 -*-
"""
Enterprise Workflow Engine — REST/Webhook API
=============================================

Endpoints
---------
GET  /wf/api/instance/<id>                  — instance details
GET  /wf/api/instance/<id>/transitions      — available transitions
POST /wf/api/instance/<id>/transition       — execute a transition
GET  /wf/api/definition/<id>/designer       — canvas data for designer
POST /wf/api/definition/<id>/designer/save  — save canvas positions
POST /wf/webhook/<wh_id>/<token>            — external webhook trigger
"""
import json
import logging

from odoo import http, _
from odoo.http import request
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)


class WorkflowApiController(http.Controller):

    # ── Instance ──────────────────────────────────────────────────────────────
    @http.route('/wf/api/instance/<int:instance_id>',
                type='jsonrpc', auth='user', methods=['GET'])
    def get_instance(self, instance_id, **kw):
        inst = request.env['wf.instance'].browse(instance_id)
        if not inst.exists():
            return {'error': 'Not found'}
        return {
            'id': inst.id, 'name': inst.name,
            'definition': inst.definition_id.name,
            'state': inst.state,
            'current_stage': inst.current_stage_id.name,
            'started_at': inst.started_at.isoformat() if inst.started_at else None,
            'duration_hours': inst.duration_hours,
            'res_model': inst.res_model, 'res_id': inst.res_id,
        }

    @http.route('/wf/api/instance/<int:instance_id>/transitions',
                type='jsonrpc', auth='user', methods=['GET'])
    def get_transitions(self, instance_id, **kw):
        inst = request.env['wf.instance'].browse(instance_id)
        if not inst.exists():
            return {'error': 'Not found'}
        transitions = inst.current_stage_id.get_available_transitions(inst)
        return {'transitions': [{
            'id': t.id, 'name': t.name,
            'button_label': t.button_label or t.name,
            'button_style': t.button_style,
            'require_comment': t.require_comment,
            'confirm_message': t.confirm_message,
        } for t in transitions]}

    @http.route('/wf/api/instance/<int:instance_id>/transition',
                type='jsonrpc', auth='user', methods=['POST'])
    def execute_transition(self, instance_id, **kw):
        try:
            payload = request.jsonrequest
            inst = request.env['wf.instance'].browse(instance_id)
            if not inst.exists():
                return {'error': 'Not found', 'success': False}
            inst.take_transition(payload.get('transition_id'),
                                 comment=payload.get('comment'))
            return {'success': True,
                    'new_stage': inst.current_stage_id.name,
                    'state': inst.state}
        except (UserError, AccessError) as e:
            return {'error': str(e), 'success': False}
        except Exception as e:
            _logger.exception('Transition API error')
            return {'error': 'Internal error', 'success': False}

    # ── Designer ──────────────────────────────────────────────────────────────
    @http.route('/wf/api/definition/<int:def_id>/designer',
                type='jsonrpc', auth='user', methods=['GET'])
    def get_designer_data(self, def_id, **kw):
        defn = request.env['wf.definition'].browse(def_id)
        if not defn.exists():
            return {'error': 'Not found'}
        return {
            'id': defn.id, 'name': defn.name, 'state': defn.state,
            'stages': [{
                'id': s.id, 'name': s.name, 'code': s.code,
                'type': s.stage_type, 'pos_x': s.pos_x, 'pos_y': s.pos_y,
                'sla_hours': s.sla_hours, 'color': s.color,
            } for s in defn.stage_ids],
            'transitions': [{
                'id': t.id, 'name': t.name,
                'from_stage_id': t.from_stage_id.id,
                'to_stage_id':   t.to_stage_id.id,
                'trigger_type':  t.trigger_type,
                'button_label':  t.button_label,
                'button_style':  t.button_style,
                'condition_type': t.condition_type,
            } for t in defn.transition_ids],
            'canvas_data': defn.canvas_data or '{}',
        }

    @http.route('/wf/api/definition/<int:def_id>/designer/save',
                type='jsonrpc', auth='user', methods=['POST'])
    def save_designer(self, def_id, **kw):
        try:
            defn = request.env['wf.definition'].browse(def_id)
            if not defn.exists():
                return {'error': 'Not found', 'success': False}
            payload = request.jsonrequest
            for stage_id, pos in (payload.get('positions') or {}).items():
                s = request.env['wf.stage'].browse(int(stage_id))
                if s.exists():
                    s.write({'pos_x': pos.get('x', 0), 'pos_y': pos.get('y', 0)})
            defn.canvas_data = json.dumps(payload.get('canvas_data', {}))
            return {'success': True}
        except Exception as e:
            return {'error': str(e), 'success': False}

    # ── Webhook ───────────────────────────────────────────────────────────────
    @http.route('/wf/webhook/<int:wh_id>/<string:token>',
                type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def webhook(self, wh_id, token, **kw):
        """
        External systems call this endpoint to trigger a workflow.
        Body: { "<record_id_field>": <id>, ... }
        """
        try:
            wh = request.env['wf.webhook'].sudo().search([
                ('id', '=', wh_id), ('token', '=', token), ('active', '=', True),
            ], limit=1)
            if not wh:
                return {'success': False, 'error': 'Invalid webhook or token'}
            payload = request.jsonrequest or {}
            rec_id  = payload.get(wh.record_id_field or 'id')
            if not rec_id:
                return {'success': False, 'error': 'Record ID not found in payload'}
            record = request.env[wh.definition_id.model_name].sudo().browse(int(rec_id))
            if not record.exists():
                return {'success': False, 'error': f'Record {rec_id} not found'}
            instance = wh.definition_id.trigger_for_record(record)
            if instance:
                return {'success': True,
                        'instance_id': instance.id,
                        'instance_name': instance.name}
            return {'success': False,
                    'message': 'Workflow not triggered (condition not met or already running)'}
        except Exception as e:
            _logger.exception('Webhook error')
            return {'success': False, 'error': str(e)}


class WorkflowWebhookModel(http.Controller):
    pass


# ── Webhook model (simple) ────────────────────────────────────────────────────
# Registered separately so it doesn't require a circular import
