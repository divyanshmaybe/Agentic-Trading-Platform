"""
Trade Execution Email Template
Sent to users when their trade (market/limit/stop/take-profit) is executed.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional


def trade_executed_email(
    user_name: str,
    trade_type: str,
    symbol: str,
    side: str,
    quantity: int,
    executed_price: Decimal,
    order_type: str,
    limit_price: Optional[Decimal] = None,
    trigger_price: Optional[Decimal] = None,
    fees: Decimal = Decimal("0"),
    taxes: Decimal = Decimal("0"),
    net_amount: Decimal = Decimal("0"),
    execution_time: Optional[datetime] = None,
    portfolio_name: str = "Portfolio",
) -> str:
    """
    Generate HTML email for trade execution notification.
    
    Args:
        user_name: Name of the user
        trade_type: Type of trade (stock, crypto, etc.)
        symbol: Trading symbol (e.g., RELIANCE-EQ)
        side: BUY or SELL
        quantity: Number of shares/units
        executed_price: Actual execution price
        order_type: market, limit, stop, stop_loss, take_profit
        limit_price: Limit price (for limit orders)
        trigger_price: Trigger price (for stop/take-profit orders)
        fees: Trading fees
        taxes: Tax amount
        net_amount: Net amount (positive for sell, negative for buy)
        execution_time: When the trade was executed
        portfolio_name: Name of the portfolio
    
    Returns:
        HTML email string
    """
    if execution_time is None:
        execution_time = datetime.utcnow()
    
    # Format values
    side_color = "#10b981" if side == "BUY" else "#ef4444"
    side_emoji = "📈" if side == "BUY" else "📉"
    
    gross_value = executed_price * Decimal(quantity)
    total_value = abs(net_amount)
    
    # Order type display
    order_type_display = {
        "market": "Market Order",
        "limit": "Limit Order",
        "stop": "Stop Order",
        "stop_loss": "Stop Loss",
        "take_profit": "Take Profit"
    }.get(order_type, order_type.title())
    
    # Build conditional order info
    order_details = ""
    if order_type == "limit" and limit_price:
        order_details = f"""
        <div class="info-row">
          <span class="info-label">Limit Price:</span>
          <span class="info-value">₹{limit_price:,.2f}</span>
        </div>
        """
    elif order_type in {"stop", "stop_loss", "take_profit"} and trigger_price:
        order_details = f"""
        <div class="info-row">
          <span class="info-label">Trigger Price:</span>
          <span class="info-value">₹{trigger_price:,.2f}</span>
        </div>
        """
    
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Trade Executed - {symbol}</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background-color: #f5f5f5;
    }}
    .container {{
      max-width: 600px;
      margin: 40px auto;
      background-color: #ffffff;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }}
    .header {{
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      padding: 40px 20px;
      text-align: center;
      color: #ffffff;
    }}
    .header h1 {{
      margin: 0;
      font-size: 28px;
      font-weight: 700;
    }}
    .header .subtitle {{
      margin-top: 10px;
      font-size: 14px;
      opacity: 0.9;
    }}
    .content {{
      padding: 40px 30px;
    }}
    .alert-box {{
      background-color: #f0fdf4;
      border-left: 4px solid #10b981;
      padding: 16px;
      border-radius: 4px;
      margin-bottom: 30px;
    }}
    .alert-box .alert-title {{
      font-weight: 600;
      color: #065f46;
      margin-bottom: 5px;
      font-size: 16px;
    }}
    .alert-box .alert-message {{
      color: #047857;
      font-size: 14px;
    }}
    .trade-summary {{
      background: linear-gradient(135deg, #f9fafb 0%, #f3f4f6 100%);
      border-radius: 8px;
      padding: 24px;
      margin: 30px 0;
    }}
    .trade-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 20px;
      padding-bottom: 16px;
      border-bottom: 2px solid #e5e7eb;
    }}
    .trade-symbol {{
      font-size: 24px;
      font-weight: 700;
      color: #111827;
    }}
    .trade-badge {{
      background-color: {side_color};
      color: #ffffff;
      padding: 6px 16px;
      border-radius: 20px;
      font-weight: 600;
      font-size: 14px;
    }}
    .info-row {{
      display: flex;
      justify-content: space-between;
      padding: 12px 0;
      border-bottom: 1px solid #e5e7eb;
    }}
    .info-row:last-child {{
      border-bottom: none;
    }}
    .info-label {{
      color: #6b7280;
      font-size: 14px;
    }}
    .info-value {{
      color: #111827;
      font-weight: 600;
      font-size: 14px;
    }}
    .price-highlight {{
      background-color: #fef3c7;
      padding: 16px;
      border-radius: 6px;
      margin: 20px 0;
      text-align: center;
    }}
    .price-highlight .label {{
      color: #92400e;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    }}
    .price-highlight .value {{
      color: #78350f;
      font-size: 32px;
      font-weight: 700;
    }}
    .financial-breakdown {{
      background-color: #fff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 20px;
      margin: 20px 0;
    }}
    .breakdown-title {{
      font-size: 16px;
      font-weight: 600;
      color: #111827;
      margin-bottom: 16px;
    }}
    .breakdown-row {{
      display: flex;
      justify-content: space-between;
      padding: 8px 0;
      font-size: 14px;
    }}
    .breakdown-total {{
      border-top: 2px solid #e5e7eb;
      margin-top: 12px;
      padding-top: 12px;
      font-weight: 700;
      font-size: 16px;
    }}
    .action-buttons {{
      text-align: center;
      margin: 30px 0;
    }}
    .button {{
      display: inline-block;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: #ffffff;
      text-decoration: none;
      padding: 12px 28px;
      border-radius: 6px;
      font-weight: 600;
      margin: 0 8px;
      font-size: 14px;
    }}
    .button-secondary {{
      background: #ffffff;
      color: #667eea;
      border: 2px solid #667eea;
    }}
    .footer {{
      background-color: #f9fafb;
      padding: 30px;
      text-align: center;
      color: #999999;
      font-size: 14px;
      border-top: 1px solid #e5e7eb;
    }}
    .timestamp {{
      color: #9ca3af;
      font-size: 12px;
      text-align: center;
      margin-top: 20px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{side_emoji} Trade Executed Successfully</h1>
      <div class="subtitle">{portfolio_name}</div>
    </div>
    
    <div class="content">
      <div class="alert-box">
        <div class="alert-title">✅ Trade Confirmation</div>
        <div class="alert-message">
          Your {order_type_display.lower()} has been executed successfully.
        </div>
      </div>

      <div class="trade-summary">
        <div class="trade-header">
          <div class="trade-symbol">{symbol}</div>
          <div class="trade-badge">{side}</div>
        </div>

        <div class="info-row">
          <span class="info-label">Order Type:</span>
          <span class="info-value">{order_type_display}</span>
        </div>
        
        <div class="info-row">
          <span class="info-label">Quantity:</span>
          <span class="info-value">{quantity:,} shares</span>
        </div>
        
        {order_details}
        
        <div class="info-row">
          <span class="info-label">Execution Time:</span>
          <span class="info-value">{execution_time.strftime('%B %d, %Y at %I:%M %p UTC')}</span>
        </div>
      </div>

      <div class="price-highlight">
        <div class="label">Executed Price</div>
        <div class="value">₹{executed_price:,.2f}</div>
      </div>

      <div class="financial-breakdown">
        <div class="breakdown-title">💰 Financial Breakdown</div>
        
        <div class="breakdown-row">
          <span>Gross Value:</span>
          <span>₹{gross_value:,.2f}</span>
        </div>
        
        <div class="breakdown-row">
          <span>Trading Fees:</span>
          <span>₹{fees:,.2f}</span>
        </div>
        
        <div class="breakdown-row">
          <span>Taxes:</span>
          <span>₹{taxes:,.2f}</span>
        </div>
        
        <div class="breakdown-row breakdown-total">
          <span>{'Total Paid' if side == 'BUY' else 'Total Received'}:</span>
          <span style="color: {side_color}">₹{total_value:,.2f}</span>
        </div>
      </div>

      <div class="action-buttons">
        <a href="{get_client_url()}/portfolio" class="button">
          View Portfolio
        </a>
        <a href="{get_client_url()}/trades" class="button button-secondary">
          Trade History
        </a>
      </div>

      <div class="timestamp">
        Trade ID: Auto-generated • Executed on {execution_time.strftime('%Y-%m-%d %H:%M:%S UTC')}
      </div>
    </div>

    <div class="footer">
      <p><strong>Important Notice:</strong></p>
      <p style="font-size: 12px; color: #6b7280; margin-top: 10px;">
        This is an automated notification. Please verify the trade details in your portfolio dashboard.
        If you did not initiate this trade, please contact support immediately.
      </p>
      <p style="margin-top: 20px;">© {datetime.now().year} AgentInvest. All rights reserved.</p>
      <p style="font-size: 12px; margin-top: 10px;">
        You're receiving this email because you have trade notifications enabled.
      </p>
    </div>
  </div>
</body>
</html>
    """


def get_client_url() -> str:
    """Get the client URL from environment or use default."""
    import os
    return os.getenv("CLIENT_URL", "https://agentinvest.com")
