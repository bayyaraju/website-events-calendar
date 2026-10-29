# Claude AI Assistant for Odoo 19

An Odoo 19 module that integrates Anthropic's Claude AI directly into your backend — enabling natural language queries, CRUD operations, chart generation, and Excel exports on your live database.

---

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Assign User Access](#assign-user-access)
- [Using the Assistant](#using-the-assistant)
- [Troubleshooting](#troubleshooting)

---

## Requirements

- Odoo 19.0
- Python 3.10+
- An Anthropic API key — get one at [console.anthropic.com](https://console.anthropic.com)

---

## Installation

### Step 1 — Copy the module

Place the `claude_ai_odoo` folder into your Odoo custom addons directory.

```bash
cp -r claude_ai_odoo/ /path/to/your/custom_addons/
```

Make sure your `odoo.conf` includes that path in `addons_path`:

```ini
addons_path = /path/to/odoo/addons, /path/to/your/custom_addons
```

### Step 2 — Clear pycache

```bash
find /path/to/your/custom_addons/claude_ai_odoo -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
```

### Step 3 — Restart Odoo

```bash
# If running as a service
sudo systemctl restart odoo

# If running manually
python odoo-bin -c odoo.conf
```

### Step 4 — Install the module

1. Log into Odoo as Administrator
2. Go to **Apps** (top menu)
3. Search for **Claude AI**
4. Click **Install**

---

## Assign User Access (After Install)

Before you can see the Claude AI menu, your user must be added to a Claude AI group. Do this immediately after install.

### Option 1 — Odoo UI (easiest, no restart needed)

1. Go to **Settings → Users & Companies → Users**
2. Open your user
3. Scroll down to the **"Other"** or **"Technical"** section
4. Find **"Claude AI / Administrator"** and check it
5. Click **Save**

Then **refresh your browser** — the **Claude AI** menu will appear in the top navigation bar.

---

## Assign User Access (Before Configuration)

> ⚠️ **Do this immediately after install**, before trying to open Claude AI.
> The menu and chat widget will not appear until your user is added to a Claude AI group.

### Option 1 — Odoo UI (easiest, no restart needed)

1. Go to **Settings → Users & Companies → Users**
2. Open your user
3. Scroll down to the **"Other"** or **"Technical"** section
4. Find **"Claude AI / Administrator"** and check it
5. Click **Save**

Then **refresh your browser** — the **Claude AI** menu will appear in the top navigation bar.

---

## Configuration

### Step 1 — Open Configuration

Go to **Claude AI → Configuration** in the top menu.

### Step 2 — Enter your API key

1. Click **New** or open the existing **Default Configuration** record
2. Paste your Anthropic API key in the **API Key** field (format: `sk-ant-api03-...`)
3. Set the **Model Name** — recommended: `claude-sonnet-4-5`
4. Click **Save**

### Step 3 — Test the connection

Click the **Test Connection** button. The status bar will turn green with ✅ **Connected** if your key is valid.

### Step 4 — Optional settings

| Setting | Default | Description |
|---|---|---|
| Max Tokens | 8096 | Maximum tokens per response |
| Temperature | 0.3 | Lower = more precise, higher = more creative |
| Request Timeout | 60s | Seconds before the request times out |
| Require Confirmation | Off | If on, write/delete operations need manual approval |
| Log All Actions | On | Saves all AI interactions to Sessions |

---

## Assign User Access

The module ships with two security groups. **Users must be added manually after install.**

### Groups

| Group | Access |
|---|---|
| **Claude AI / User** | Can use the AI chat assistant |
| **Claude AI / Administrator** | Full access including Configuration and Sessions |

### Option 1 — Odoo UI (easiest, no restart needed)

1. Go to **Settings → Users & Companies → Users**
2. Open your user
3. Scroll down to the **"Other"** or **"Technical"** section
4. Find **"Claude AI / Administrator"** and check it
5. Click **Save**

### Option 2 — Via Odoo Shell

```bash
cd /path/to/odoo-19.0
python odoo-bin shell -c odoo.conf -d your_database_name
```

Then in the Python shell:

```python
# Grant admin user full Claude AI access
admin = env.ref('base.user_admin')
group = env.ref('claude_ai_odoo.group_claude_admin')
admin.write({'groups_id': [(4, group.id)]})
env.cr.commit()
```

### Option 3 — Grant access to all internal users

```python
all_users = env['res.users'].search([('share', '=', False)])
group = env.ref('claude_ai_odoo.group_claude_user')
all_users.write({'groups_id': [(4, group.id)]})
env.cr.commit()
```

After assigning groups, **refresh the browser**. The **Claude AI** menu will appear in the top navigation bar.

---

## Using the Assistant

Navigate to **Claude AI → AI Assistant**.

### Chat Interface

Type any natural language question about your Odoo data and press **Enter** or click the send button.

**Example prompts:**

```
Show today's sales orders with customer names and totals
List all unpaid invoices with amount and due date
Create a pie chart of revenue by customer this month
Generate an Excel report of monthly sales
Show current stock levels for all products
Create a new customer called Acme Corp
```

### Quick Actions (left sidebar)

Pre-built buttons for the most common queries — click any to run instantly.

### Quick Create (left sidebar)

One-click forms to create Customers, Products, Invoices, and Employees.

### File Attachments

Click the 📎 button to attach a **CSV or Excel file** for bulk import. Claude will parse the file and create records automatically.

### Charts

Ask for any chart type — pie, bar, or line. Charts render inline and can be expanded to fullscreen or downloaded as SVG.

### Excel Reports

Ask to *"generate an Excel report"* for any data set. A download card will appear in the chat — click it to save the file.

---

## Troubleshooting

### Claude AI menu not visible after install

Your user is not in a Claude AI group. Follow the [Assign User Access](#assign-user-access) steps above.

### "API key missing" message in chat

Go to **Claude AI → Configuration**, enter your API key, save, and test the connection.

### Module fails to install with `post_init_hook` error

Your `__init__.py` is missing the hooks import. Edit the file:

```python
# claude_ai_odoo/__init__.py
from . import models, controllers, hooks
```

Then clear pycache and restart Odoo:

```bash
find /path/to/claude_ai_odoo -name '__pycache__' -type d -exec rm -rf {} +
sudo systemctl restart odoo
```

### Chat returns no response or times out

- Check that your API key is valid at [console.anthropic.com](https://console.anthropic.com)
- Increase the **Request Timeout** in Configuration
- Check Odoo server logs for detailed error messages:
  ```bash
  tail -f /var/log/odoo/odoo.log | grep claude
  ```

### Sessions

Go to **Claude AI → Sessions** (admin only) to review all past conversations, token usage per user, and clear individual session histories.

---

## Support

For issues contact: raj.odoo2026@gmail.com
## What's new in 19.0.6.0.0
- **Latest Claude models**: Opus 5.5, Sonnet 5.5 (default), Haiku 4.5, Fable 5.1 + *Custom Model ID* field for future models (old 4.5 values kept for existing configs).
- **Prompt caching** (on by default): the large Odoo schema prompt is cached between messages – lower cost, faster replies.
- **Security hardening**: every operation runs as the logged-in user (Odoo access rights & record rules apply, no more `sudo`); private/technical methods and security models (`ir.config_parameter`, `ir.rule`, `ir.cron`, …) are blocked; only *Claude AI* group members can use the chat; users can only open their own sessions; module install restricted to Claude admins with Settings rights.
- **Always Confirm Deletes** (on by default): deletions proposed by Claude always need a click.
- **Failed operations are isolated** in a DB savepoint – an error no longer breaks the chat request.
- **Temperature and Timeout settings are now applied** to the API call; automatic retries on temporary API errors.
- **More robust conversation history**: always valid for the API (starts with a user turn, roles alternate); a failed call no longer leaves a broken history.
- Settings administrators automatically get *Claude AI / Administrator* (menus visible right after install); all configurations visible in the Configuration list.

## 19.0.6.0.1
- Fix: newer Claude models (e.g. Sonnet 5.5) reject the `temperature` parameter (`400 – temperature is deprecated for this model`). The request is now retried automatically without it, and the model is remembered so later messages skip it.

---

## 💰 New in 19.0.7.0.0 — Pay for AI only when you need it

> **Up to 90 % of everyday requests are answered by Odoo itself — 0 tokens, $0, instant.**

| | How it saves money |
|---|---|
| ⚡ **Local answers** | The 10 Quick Actions and simple questions are handled directly by Odoo, no API call: *Today's Sales, Revenue Pie Chart, Unpaid Invoices, Monthly Excel Report, Top Products Chart, Stock Levels, Employees, Revenue Trend, Browse Modules, Pending POs*, plus free text such as *"show customers"*, *"list vendors"*, *"how many invoices"*, *"count sales orders"*, *"install crm module"*, *"hello/help"*. **Works even without an API key.** |
| ♻️ **Re-used answers (cache)** | When Claude answers a read-only question, its query is remembered. Asking the same question again re-runs the query **locally on fresh data** — no API call. Configurable lifetime; *Claude AI → Answer Cache* to review/clear. Write operations, installs and imports are never cached. |
| 🧠 **Prompt caching** | When Claude *is* needed, the large Odoo schema prompt is cached between messages → cheaper and faster follow-ups. |
| 📊 **Savings dashboard** | *Saved without AI* panel in the chat sidebar + statistics in *Configuration*: requests answered locally / re-used / by Claude, tokens used, **tokens saved** and **money saved** (estimate based on *Blended Price per 1M Tokens*). |
| 🏷️ **Source badge** | Every reply shows where it came from: ⚡ *Answered locally · 0 tokens*, ♻️ *Re-used answer · 0 tokens*, 🤖 *Claude AI · N tokens*. |

**Force Claude:** start a message with `!` (e.g. `!show customers`) to skip the local engine and the cache.

### Typical savings

| Request | Before | Now |
|---|---|---|
| Quick Action (e.g. Revenue Pie Chart) | ~3,000+ tokens | **0 tokens**, < 1 s |
| "How many customers?" | ~3,000 tokens | **0 tokens** |
| Same complex question asked again | full price every time | **0 tokens** (fresh data) |
| Follow-up messages to Claude | full prompt re-sent | prompt caching → cheaper |

*(Estimates – real numbers depend on your usage; see the statistics in Configuration.)*

### Loaders and refresh
- Loader text while waiting: **"Fetching from Odoo…"** for quick actions, **"Claude is working on it…"** when the AI takes longer, **"Executing…"** spinner on confirmed operations.
- After records are created/updated/deleted or imported, a **🔄 Refresh** button refreshes the open views.
- After an app is installed, a **🔄 Reload Odoo** button reloads the page so the new menus appear.

### Settings (Claude AI → Configuration → *Cost Saving*)
| Field | Default | |
|---|---|---|
| Answer Locally When Possible | ✅ | local engine on/off |
| Re-use Previous Answers | ✅ | answer cache on/off |
| Cache Lifetime (days) | 30 | |
| Blended Price per 1M Tokens (USD) | 6.00 | only for the savings estimate |
| Statistics | – | Requests without API (%), Answered Locally, Answered from Cache, Claude API Calls, Tokens Used/Saved, Money Saved; buttons *Clear Answer Cache*, *Reset Statistics* |

### Security of local answers
Local answers and cached queries run **as the logged-in user** (access rights and record rules apply), exactly like the Claude path. Module installation still requires *Claude AI / Administrator* + Settings rights.

### Screenshots
- `static/description/local-pie-chart.png` – pie chart answered locally, 0 tokens, savings panel
- `static/description/local-top-products.png` – top products chart computed by Odoo
- `static/description/local-install-refresh.png` – local app install with *Reload Odoo* prompt
- `static/description/local-unpaid-invoices.png` – unpaid invoices list answered locally
- `static/description/config-cost-saving.png` – cost-saving settings and statistics

### Tested
Fresh install and upgrade from 19.0.6.0.1 on Odoo 19 (no errors/warnings); all 10 quick actions, free-text patterns, cache hit on a repeated question, forced AI (`!`), savings statistics and the chat UI (no console errors) verified on a demo database with Sales, Purchase, Inventory, Invoicing and Employees.

## 19.0.7.0.1 — fix
- Fixed `time zone "Asia/Calcutta" not recognized` on PostgreSQL servers whose tzdata lacks old timezone aliases: date grouping (Revenue Trend, monthly charts) now maps the alias to its canonical name (e.g. Asia/Kolkata) or falls back to UTC.
- The local engine now runs inside a savepoint, so a failed local query falls back to Claude cleanly instead of breaking the request (`current transaction is aborted`).

## ⚡ 19.0.7.1.0 — Crisp answers, fewer tokens
- New professional App Store page (index.html), animated banner (banner.gif) and fresh screenshots.
- **Acts instead of asking**: strict short-answer style (max 2 sentences, no plans, no "I'll check", no re-asking).
- **Multi-step in one turn**: Claude can request data first (`"continue": true`); the server runs it and returns the result immediately, then Claude performs the action – e.g. *"create invoice for S00022"* finishes in a single message.
- **Claude sees real results**: every operation's result is kept in the conversation, so it never re-checks or invents numbers.
- **Record actions**: `{"model":"sale.order","method":"action_confirm","ids":[7]}`; safe alias `create_invoice` for confirmed sale orders.
- **New free local commands (0 tokens)**: *confirm S00022*, *create invoice for S00022*, *post invoice for S00022* (sale & purchase orders).
- Only the last 14 messages are sent to the API → lower cost and faster replies on long chats.

## 📊 19.0.7.2.0 — Interactive charts & tables
- **Charts**: hover tooltips (value + % of total) with highlight, Bar / Line / Pie switch, sort, **period chips** (1M · 3M · 6M · 12M · YTD · All) and **Week / Month / Quarter** grouping for trends, **CSV and PNG export**, animated rendering.
- **Drill-down**: click a bar, point, slice or legend row → the matching Odoo records open in a dialog (chat stays open).
- **Result tables**: click a column to sort, type to filter, export visible rows to CSV, click a row to open the record.
- New endpoint `/claude_ai/chart_data` re-aggregates charts with the user's access rights (model, fields, period and granularity are validated; no AI call, 0 tokens).
