# Email Service Configuration Guide

## Overview

The portfolio server uses the centralized Python email service (`shared/py/emailService.py`) for sending risk alerts and notifications via **SendGrid SMTP relay** or any standard SMTP server.

---

## Configuration

### **Environment Variables**

Add these to your `.env` file in `apps/portfolio-server/`:

```bash
# Email Configuration
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_USERNAME=apikey  # Literal string "apikey" for SendGrid
EMAIL_PASSWORD=SG.xxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # Your SendGrid API key
EMAIL_FROM=AgentInvest Alerts <alerts@yourdomain.com>
```

### **SendGrid Setup (Recommended)**

1. **Create SendGrid Account**: https://signup.sendgrid.com/
2. **Create API Key**:
   - Go to Settings → API Keys
   - Click "Create API Key"
   - Name it "AgentInvest Risk Alerts"
   - Select "Restricted Access" → Enable "Mail Send"
   - Copy the API key (starts with `SG.`)
3. **Verify Sender Email**:
   - Go to Settings → Sender Authentication
   - Verify your domain or single sender email
4. **Add to `.env`**:
   ```bash
   EMAIL_HOST=smtp.sendgrid.net
   EMAIL_PORT=587
   EMAIL_USE_TLS=true
   EMAIL_USERNAME=apikey
   EMAIL_PASSWORD=SG.your_actual_api_key_here
   EMAIL_FROM=alerts@yourdomain.com
   ```

### **Gmail Setup (Alternative)**

1. **Enable 2-Factor Authentication**
2. **Create App Password**:
   - Go to Google Account → Security → 2-Step Verification
   - Scroll to "App passwords"
   - Generate password for "Mail" app
3. **Add to `.env`**:
   ```bash
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_USE_TLS=true
   EMAIL_USERNAME=your-email@gmail.com
   EMAIL_PASSWORD=xxxx xxxx xxxx xxxx  # 16-char app password
   EMAIL_FROM=your-email@gmail.com
   ```

---

## Testing Email Configuration

### **Quick Test Script**

```bash
cd apps/portfolio-server
python3 << 'EOF'
import sys
import asyncio
sys.path.insert(0, '.')
sys.path.insert(0, '../../shared/py')

from emailService import EmailService

async def test_email():
    service = EmailService()
    
    # Health check
    print("SMTP Server Health:", "✅ OK" if service.health_check() else "❌ FAIL")
    
    # Send test email
    success = await service.send_email(
        to="your-test-email@example.com",
        subject="Risk Alert Test",
        body="This is a test email from AgentInvest Risk Monitor.",
    )
    
    if success:
        print("✅ Test email sent successfully!")
    else:
        print("❌ Failed to send email. Check logs.")

asyncio.run(test_email())
EOF
```

### **Expected Output**

```
SMTP Server Health: ✅ OK
✅ Test email sent successfully!
```

---

## Risk Alert Email Format

### **Subject Line**
```
[Risk Alert:WORSE] Tech Growth Portfolio, Dividend Portfolio
```

- **Severity Levels**: `WORST`, `WORSE`, `BAD`, `INFO`
- **Portfolios**: Comma-separated list of affected portfolios

### **Email Body**
```
Risk monitoring detected the following conditions:

- RELIANCE | drop: -8.0% | threshold: 5.0% | severity: WORSE | price: 2300.0
  RELIANCE dropped 8.00% (threshold 5.00%) - severity worse
  
- INFY | drop: -6.5% | threshold: 5.0% | severity: BAD | price: 1400.0
  INFY dropped 6.50% (threshold 5.00%) - severity bad

Please review the affected positions and take action if required.
```

---

## How Emails Are Sent

### **1. Risk Monitor Detects Breach**
```python
# Symbol-based monitoring runs every 15 minutes
symbols = ["RELIANCE", "TCS", "INFY", ...]
for symbol in symbols:
    current_price = get_price(symbol)  # Once per symbol
    affected_users = db.query_affected_users(symbol, current_price)
    for user in affected_users:
        queue_email(user, alerts)
```

### **2. Email Batching by Recipient**
```python
# Group all alerts by email address
email_batches = {}
for alert in alerts:
    for recipient in alert.contact_emails:
        email_batches[recipient].append(alert)

# Send ONE email per recipient (not one per alert!)
for recipient, user_alerts in email_batches.items():
    send_risk_alert_email_task.delay(recipient, subject, user_alerts)
```

### **3. Celery Asynchronous Delivery**
```python
# Celery task queues email for delivery
@celery_app.task(name="risk.alerts.send_email", autoretry_for=(Exception,), retry_backoff=True)
def send_risk_alert_email_task(recipient, subject, alerts):
    email_service = EmailService()
    await email_service.send_email(recipient, subject, formatted_body)
```

**Benefits**:
- ✅ Non-blocking (doesn't slow down risk monitoring)
- ✅ Automatic retries on failure (up to 3 attempts with exponential backoff)
- ✅ Batched alerts per user (single email, not spam)

---

## Configuring Contact Emails

### **Portfolio Metadata**

Add alert emails to portfolio metadata:

```python
# When creating portfolio
portfolio = await prisma.portfolio.create(
    data={
        "user_id": "user-123",
        "portfolio_name": "Tech Growth",
        "risk_tolerance": "moderate",
        "metadata": {
            "alert_emails": ["user@example.com", "advisor@example.com"],
            "risk_threshold_pct": 7.0,  # Optional: override default threshold
        }
    }
)
```

### **Position Metadata (Override)**

Position-specific email overrides:

```python
# When creating position
position = await prisma.position.create(
    data={
        "portfolio_id": "portfolio-abc",
        "symbol": "RELIANCE",
        "quantity": 100,
        "average_buy_price": 2500.0,
        "metadata": {
            "risk_emails": ["urgent@example.com"],  # Position-specific
            "risk_threshold_pct": 10.0,  # Custom threshold for this holding
        }
    }
)
```

---

## Troubleshooting

### **Email Not Configured**
```
❌ Username Configured: No
❌ Password Configured: No
```

**Solution**: Add `EMAIL_USERNAME` and `EMAIL_PASSWORD` to `.env`

### **SMTP Connection Failed**
```
❌ SMTP server unreachable
```

**Solution**:
1. Check firewall allows port 587 outbound
2. Verify `EMAIL_HOST` is correct
3. Try `EMAIL_PORT=25` or `EMAIL_PORT=465` (SSL)

### **Authentication Failed**
```
❌ Failed to send email: (535, 'Authentication failed')
```

**Solution**:
1. **SendGrid**: Ensure API key starts with `SG.` and has Mail Send permission
2. **Gmail**: Use App Password (not account password)

### **Emails Going to Spam**
**Solution**:
1. Use SendGrid (better deliverability)
2. Verify sender domain (SPF, DKIM records)
3. Add users to safe senders list

### **Rate Limiting**
```
❌ Failed to send email: (429, 'Too many requests')
```

**Solution**:
1. **SendGrid**: Upgrade plan or wait for rate limit reset
2. **Gmail**: Max 500 emails/day for free accounts
3. Celery already implements exponential backoff

---

## Production Checklist

- [ ] SendGrid API key configured
- [ ] Sender email verified
- [ ] Test email sent successfully
- [ ] SPF/DKIM records configured (for domain)
- [ ] Celery worker running (`pnpm celery` or `celery -A celery_app worker`)
- [ ] Celery beat running for scheduled monitoring
- [ ] Redis running (Celery broker)
- [ ] Email templates exist in `shared/py/email_templates/` (optional)

---

## Environment Variables Reference

```bash
# Required
EMAIL_HOST=smtp.sendgrid.net              # SMTP server hostname
EMAIL_PORT=587                            # SMTP port (587 for TLS, 465 for SSL)
EMAIL_USERNAME=apikey                     # SendGrid: "apikey", Gmail: email address
EMAIL_PASSWORD=SG.xxxxx                   # SendGrid API key or Gmail app password

# Optional
EMAIL_USE_TLS=true                        # Use TLS encryption (recommended)
EMAIL_FROM=alerts@yourdomain.com          # Sender email address
APP_NAME=AgentInvest                       # App name in email templates
```

---

## Summary

✅ **Email service configured** via `shared/py/emailService.py`  
✅ **SendGrid recommended** for production (better deliverability)  
✅ **Gmail acceptable** for development/testing  
✅ **Celery handles delivery** (async, with retries)  
✅ **Batched alerts** (one email per user, not per holding)  
✅ **Health check available** to verify SMTP connectivity  

Configure your `.env` file and test the email service before running risk monitoring!
