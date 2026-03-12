# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from odoo import api, models, fields


class WooDashboard(models.AbstractModel):
    """Provides aggregated analytics data for the WooCommerce dashboard.
    AbstractModel = no DB table, accessible via RPC."""
    _name = 'woo.dashboard'
    _description = 'WooCommerce Analytics Dashboard'

    @api.model
    def get_instances(self):
        instances = self.env['woo.instance'].search([('active', '=', True)])
        return [{'id': i.id, 'name': i.name, 'state': i.state} for i in instances]

    @api.model
    def get_dashboard_data(self, instance_id=None):
        base = [('instance_id', '=', instance_id)] if instance_id else []

        # KPIs
        total_orders   = self.env['woo.sale.order'].search_count(base)
        total_products = self.env['woo.product.template'].search_count(base)
        total_customers = self.env['res.partner'].search_count(
            [('is_woo_customer', '=', True)] +
            ([('woo_instance_id', '=', instance_id)] if instance_id else [])
        )
        total_coupons = self.env['woo.coupon'].search_count(base)

        orders = self.env['woo.sale.order'].search(base)
        total_revenue = sum(orders.mapped('woo_total'))
        avg_order_value = (total_revenue / total_orders) if total_orders else 0.0

        # Orders by status
        statuses = ['pending', 'processing', 'on-hold', 'completed',
                    'cancelled', 'refunded', 'failed']
        orders_by_status = []
        for s in statuses:
            cnt = self.env['woo.sale.order'].search_count(base + [('woo_order_status', '=', s)])
            if cnt:
                orders_by_status.append({'label': s.title().replace('-', ' '),
                                         'value': cnt, 'status': s})

        # 12-month revenue + order trend
        today = datetime.today()
        revenue_trend = []
        for i in range(11, -1, -1):
            ms = (today - timedelta(days=i * 30)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            me = (ms + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
            mo = self.env['woo.sale.order'].search(
                base + [('synced_date', '>=', ms.strftime('%Y-%m-%d %H:%M:%S')),
                        ('synced_date', '<=', me.strftime('%Y-%m-%d %H:%M:%S'))])
            revenue_trend.append({
                'month': ms.strftime('%b %Y'),
                'revenue': round(sum(mo.mapped('woo_total')), 2),
                'orders': len(mo),
            })

        # Top products — include image, sale price, status, category, type
        top_products = []
        for p in self.env['woo.product.template'].search(base, order='woo_stock_quantity desc', limit=20):
            cats = ', '.join(p.woo_category_ids.mapped('name')) if p.woo_category_ids else ''
            top_products.append({
                'name': (p.name or '')[:40],
                'sku': p.woo_sku or '',
                'stock': p.woo_stock_quantity,
                'stock_status': p.woo_stock_status or 'instock',
                'price': p.woo_regular_price,
                'sale_price': p.woo_sale_price,
                'type': p.woo_type or 'simple',
                'status': p.woo_status or 'publish',
                'sync_state': p.sync_state or 'pending',
                'image_url': getattr(p, 'woo_image_url', '') or '',
                'categories': cats,
                'last_synced': p.last_synced.strftime('%d %b %Y') if p.last_synced else '',
                'woo_id': p.woo_id,
            })

        # Stock status
        stock_status = {}
        for ss in ['instock', 'outofstock', 'onbackorder']:
            stock_status[ss] = self.env['woo.product.template'].search_count(
                base + [('woo_stock_status', '=', ss)])

        # Logs last 7 days
        week_ago = (datetime.today() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        log_base = ([('instance_id', '=', instance_id)] if instance_id else []) + \
                   [('create_date', '>=', week_ago)]
        log_levels = {}
        for lv in ['info', 'success', 'warning', 'error']:
            log_levels[lv] = self.env['woo.log'].search_count(log_base + [('level', '=', lv)])

        # Queue
        queue_summary = {}
        for st in ['draft', 'processing', 'done', 'failed']:
            queue_summary[st] = self.env['woo.queue.line'].search_count(
                base + [('state', '=', st)])

        # Recent orders
        recent_orders = []
        for o in self.env['woo.sale.order'].search(base, limit=10, order='synced_date desc'):
            recent_orders.append({
                'woo_id': o.woo_order_id,
                'number': o.woo_order_number or str(o.woo_order_id),
                'status': o.woo_order_status or '',
                'total': o.woo_total,
                'currency': o.woo_currency or 'USD',
                'payment': o.payment_method_title or '',
                'date': o.synced_date.strftime('%d %b %Y') if o.synced_date else '',
            })

        # Payment methods (Odoo 17+ returns list of tuples)
        raw = self.env['woo.sale.order']._read_group(
            base + [('payment_method_title', '!=', False)],
            groupby=['payment_method_title'],
            aggregates=['__count'])
        payment_methods = [
            {'method': r[0], 'count': r[1]}
            for r in raw if r[0]
        ]

        # Last syncs
        last_syncs = {}
        if instance_id:
            inst = self.env['woo.instance'].browse(instance_id)
            fmt = lambda d: d.strftime('%d %b %Y %H:%M') if d else 'Never'
            last_syncs = {
                'orders': fmt(inst.last_order_sync),
                'products': fmt(inst.last_product_sync),
                'stock': fmt(inst.last_stock_sync),
                'instance_state': inst.state,
                'instance_name': inst.name,
            }

        # Coupons detail
        today = fields.Date.today()
        coupons_list = []
        coupon_type_counts = {'percent': 0, 'fixed_cart': 0, 'fixed_product': 0}
        total_usage = 0
        expired_count = 0
        active_count = 0
        unlimited_count = 0

        for c in self.env['woo.coupon'].search(base, order='usage_count desc'):
            is_expired = c.expiry_date and c.expiry_date < today
            usage_pct = 0
            if c.usage_limit and c.usage_limit > 0:
                usage_pct = min(100, round((c.usage_count / c.usage_limit) * 100))
            else:
                unlimited_count += 1

            if is_expired:
                expired_count += 1
                status = 'expired'
            elif c.usage_limit and c.usage_count >= c.usage_limit:
                expired_count += 1
                status = 'used_up'
            else:
                active_count += 1
                status = 'active'

            coupon_type_counts[c.discount_type or 'percent'] = coupon_type_counts.get(c.discount_type or 'percent', 0) + 1
            total_usage += c.usage_count or 0

            discount_label = ''
            if c.discount_type == 'percent':
                discount_label = str(round(c.amount)) + '%'
            elif c.discount_type in ('fixed_cart', 'fixed_product'):
                discount_label = '$' + str(round(c.amount, 2))

            coupons_list.append({
                'code': c.name or '',
                'woo_id': c.woo_id,
                'discount_type': c.discount_type or 'percent',
                'amount': c.amount,
                'discount_label': discount_label,
                'usage_count': c.usage_count or 0,
                'usage_limit': c.usage_limit or 0,
                'usage_pct': usage_pct,
                'expiry_date': c.expiry_date.strftime('%d %b %Y') if c.expiry_date else 'No Expiry',
                'status': status,
                'is_expired': bool(is_expired),
            })

        return {
            'kpis': {
                'total_orders': total_orders,
                'total_products': total_products,
                'total_customers': total_customers,
                'total_coupons': total_coupons,
                'total_revenue': round(total_revenue, 2),
                'avg_order_value': round(avg_order_value, 2),
            },
            'orders_by_status': orders_by_status,
            'revenue_trend': revenue_trend,
            'top_products': top_products,
            'log_levels': log_levels,
            'queue_summary': queue_summary,
            'stock_status': stock_status,
            'recent_orders': recent_orders,
            'payment_methods': payment_methods,
            'last_syncs': last_syncs,
            'coupons': coupons_list,
            'coupon_stats': {
                'total': len(coupons_list),
                'active': active_count,
                'expired': expired_count,
                'unlimited': unlimited_count,
                'total_usage': total_usage,
                'by_type': coupon_type_counts,
            },
        }
