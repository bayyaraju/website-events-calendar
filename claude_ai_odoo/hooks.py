# -*- coding: utf-8 -*-
import logging
_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Create the default config record on first install."""
    Config = env['claude.config']
    config = Config.sudo().search([], limit=1)
    if not config:
        config = Config.sudo().create({
            'name': 'Default Configuration',
            'active': True,
            'model_name': 'claude-sonnet-4-5',
            'max_tokens': 8096,
            'temperature': 0.3,
            'request_timeout': 60,
            'require_confirmation': False,
            'log_all_actions': True,
        })
        _logger.info('Claude AI: default config created (id=%s)', config.id)
    elif not Config.sudo().search([('active', '=', True)], limit=1):
        # Ensure at least one record is active
        config.sudo().write({'active': True})
        _logger.info('Claude AI: activated config id=%s', config.id)
