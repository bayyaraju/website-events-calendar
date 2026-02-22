# Advanced Inventory Control & Negative Stock Prevention Engine
### Odoo 19 Community | Enterprise-Level Module

---

## 🚀 Features Overview

### 1️⃣ Smart Blocking Levels (Multi-Mode Control)
Three modes per warehouse:
- 🟢 **Allow** – No restriction, stock can go negative freely
- 🟡 **Warn Only** – Popup warning shown, user can still proceed
- 🔴 **Strict Block** – Hard stop, requires manager override

### 2️⃣ Product & Category-Level Configuration
- **Product-level**: `Allow` / `Inherit` / `Block (Strict)` per product
- **Category-level**: Inheritable setting for entire product families
- **Effective Policy** displayed on product form showing actual active rule
- Service/virtual products can be set to always allow

### 3️⃣ Role-Based Override with Audit Trail
- Manager override button on blocked transfers
- **Mandatory reason input** (configurable)
- Full audit log stored with:
  - User, date, quantity, location, document reference
  - Before/after stock quantities
- Logged to **chatter** on the transfer
- Dedicated **Override Audit Log** menu with full search/filter

### 4️⃣ Real-Time Stock Calculation Methods
Configurable per warehouse:
- **On Hand Only** – checks raw quant quantity
- **On Hand – Reserved** – checks truly available qty
- **Forecasted Quantity** – includes incoming/outgoing moves

### 5️⃣ Warehouse-Level Control Panel
Each warehouse has its own:
- Negative stock policy
- Stock calculation method
- Manager override permission
- Override reason requirement
- Alert recipient list

### 6️⃣ Negative Stock Dashboard
Real-time view showing:
- All products currently at negative stock
- Days since it went negative
- Warehouse and location
- Total negative quantity (On Hand / Available / Forecasted)
- Responsible user
- Override count and last override user
- Severity: Critical / Warning / Info

### 7️⃣ Scheduled Monitor (Daily Cron)
- Refreshes dashboard daily
- Sends email alert when negative stock exists
- Configurable alert email address
- HTML email with color-coded severity table

### 8️⃣ Sale Order Soft-Lock Warning
- Warning popup on Sale Order confirmation when stock is insufficient
- Shows shortfall per product
- User can confirm anyway (logged to chatter) or go back to review
- Configurable on/off in Settings

### 9️⃣ Override Analytics
Track via Audit Log:
- Total override count
- Per-user override frequency
- Per-product frequency
- Filterable by date range, warehouse, user

### 🔟 Multi-Company Safe
- All policies and logs are company-specific
- Dashboard shows company's data only
- Access groups tied to standard Odoo Stock roles

---

## 📦 Installation

1. Copy `negative_stock_control` folder to your Odoo addons path
2. Update Apps list
3. Install **Advanced Inventory Control & Negative Stock Prevention Engine**

### Dependencies
- `stock` (Inventory)
- `sale_stock` (Sales + Inventory)
- `purchase_stock` (Purchase + Inventory)
- `mail` (Discuss/Chatter)

---

## ⚙️ Configuration

### Global Settings
`Inventory → Configuration → Settings → Negative Stock Control`
- Default policy (Allow / Warn / Block)
- Enable/disable SO warning popup
- Daily email alerts on/off + recipient email
- Analytics lookback period

### Per-Warehouse Settings
`Inventory → Configuration → Warehouses → [Warehouse] → Negative Stock Control tab`
- Policy (Allow / Warn / Block)
- Stock calculation method
- Allow manager override
- Require override reason
- Alert recipients

### Per-Product Settings
`Inventory → Products → [Product] → Stock Control tab`
- Negative stock setting (Inherit / Allow / Block)
- Optional note/reason

### Per-Category Settings
`Inventory → Configuration → Product Categories → [Category]`
- Negative stock setting (Inherit / Allow / Block)

---

## 👤 User Roles
| Role | Permission |
|------|-----------|
| Stock User | View dashboard, accept warnings |
| Stock Manager | Full access + override blocks |
| Negative Stock: Override Permission | Custom override group |
| Negative Stock: View Dashboard | Read-only dashboard access |

---

## 🔄 Workflow

### Strict Block Scenario
1. Warehouse policy = 🔴 Strict Block
2. User validates transfer → would go negative
3. System checks policy → shows blocked popup
4. If Manager Override = Yes and user is Stock Manager:
   → Override wizard opens
   → User must enter reason
   → System logs override + posts to chatter
   → Transfer proceeds
5. If Manager Override = No:
   → Hard error raised, transfer cannot proceed

### Warn Only Scenario
1. Warehouse policy = 🟡 Warn Only
2. User validates transfer → would go negative
3. Warning wizard opens showing affected products
4. User can enter optional reason and click "Proceed Anyway"
5. Action logged to audit trail
6. Transfer proceeds

---

## 📊 Analytics Queries (via Override Audit Log)

**Top Override Users (30 days)**:
`Audit Log → Group By: User → This Month filter`

**Most Frequently Negative Products**:
`Audit Log → Group By: Product → sort by count`

**Override Trend**:
`Audit Log → Group By: Month`

---

## 📝 Changelog

### v19.0.1.0.0
- Initial release
- All 10 enterprise features implemented
- Multi-company support
- Full audit trail
- PDF report
- Daily cron monitor
