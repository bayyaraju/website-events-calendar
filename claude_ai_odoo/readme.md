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