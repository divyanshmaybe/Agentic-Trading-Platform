"""
Trade Email Notification Service
Sends email notifications for trade executions via central email pipeline.
"""

import logging
import os
from decimal import Decimal
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Central email API endpoint
EMAIL_API_URL = os.getenv("EMAIL_API_URL", "http://localhost:3001/api/email/send")
EMAIL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


async def send_trade_execution_email(
    user_email: str,
    user_name: str,
    trade_data: dict,
    portfolio_name: str = "Portfolio"
) -> bool:
    """
    Send trade execution email notification via central email service.
    
    Args:
        user_email: Recipient email address
        user_name: User's name
        trade_data: Dict containing trade details
        portfolio_name: Name of the portfolio
        
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        from emails.trade_executed import trade_executed_email
        
        # Generate HTML email
        html_content = trade_executed_email(
            user_name=user_name,
            trade_type=trade_data.get("trade_type", "stock"),
            symbol=trade_data.get("symbol", ""),
            side=trade_data.get("side", "BUY"),
            quantity=trade_data.get("executed_quantity", 0),
            executed_price=Decimal(str(trade_data.get("executed_price", 0))),
            order_type=trade_data.get("order_type", "market"),
            limit_price=Decimal(str(trade_data.get("limit_price"))) if trade_data.get("limit_price") else None,
            trigger_price=Decimal(str(trade_data.get("trigger_price"))) if trade_data.get("trigger_price") else None,
            fees=Decimal(str(trade_data.get("fees", 0))),
            taxes=Decimal(str(trade_data.get("taxes", 0))),
            net_amount=Decimal(str(trade_data.get("net_amount", 0))),
            execution_time=trade_data.get("execution_time") or datetime.utcnow(),
            portfolio_name=portfolio_name
        )
        
        # Prepare email payload
        subject = f"{'🟢' if trade_data.get('side') == 'BUY' else '🔴'} Trade Executed: {trade_data.get('symbol')} - {trade_data.get('order_type', 'market').title()} Order"
        
        # Send via central email API
        import httpx
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                EMAIL_API_URL,
                json={
                    "to": user_email,
                    "subject": subject,
                    "html": html_content,
                    "category": "trade_execution"
                },
                headers={
                    "Authorization": f"Bearer {EMAIL_API_KEY}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Trade execution email sent to {user_email} for {trade_data.get('symbol')}")
                return True
            else:
                logger.error(f"❌ Failed to send trade email: {response.status_code} - {response.text}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Error sending trade execution email: {e}", exc_info=True)
        return False


async def send_order_pending_email(
    user_email: str,
    user_name: str,
    order_data: dict,
    portfolio_name: str = "Portfolio"
) -> bool:
    """
    Send email notification for pending order creation.
    
    Args:
        user_email: Recipient email address
        user_name: User's name
        order_data: Dict containing order details
        portfolio_name: Name of the portfolio
        
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        order_type = order_data.get("order_type", "limit")
        symbol = order_data.get("symbol", "")
        side = order_data.get("side", "BUY")
        
        # Simple pending order notification
        subject = f"⏳ Order Pending: {symbol} - {order_type.title()} Order"
        
        html_content = f"""
        <h2>Order Placed Successfully</h2>
        <p>Hi {user_name},</p>
        <p>Your {order_type} order for <strong>{symbol}</strong> has been placed and is pending execution.</p>
        <p><strong>Order Details:</strong></p>
        <ul>
            <li>Symbol: {symbol}</li>
            <li>Side: {side}</li>
            <li>Quantity: {order_data.get('quantity', 0)} shares</li>
            <li>Order Type: {order_type.title()}</li>
        </ul>
        <p>You will receive another email when the order is executed.</p>
        <p>Best regards,<br>AgentInvest Team</p>
        """
        
        import httpx
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                EMAIL_API_URL,
                json={
                    "to": user_email,
                    "subject": subject,
                    "html": html_content,
                    "category": "order_pending"
                },
                headers={
                    "Authorization": f"Bearer {EMAIL_API_KEY}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Pending order email sent to {user_email} for {symbol}")
                return True
            else:
                logger.warning(f"⚠️  Failed to send pending order email: {response.status_code}")
                return False
                
    except Exception as e:
        logger.warning(f"⚠️  Error sending pending order email: {e}")
        return False  # Don't fail the order creation if email fails
