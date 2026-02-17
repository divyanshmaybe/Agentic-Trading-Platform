from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

from celery_app import celery_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))

from emailService import EmailService  # type: ignore  # noqa: E402

logger = logging.getLogger(__name__)


def _build_alert_subject(portfolio_name: str, symbol: str, severity: str) -> str:
    return f"[Risk Alert:{severity.upper()}] {symbol} in {portfolio_name}"


def _format_alert_body(alerts: Sequence[Dict[str, Any]]) -> str:
    if not alerts:
        return "Risk monitor triggered but no alert payload was provided."

    lines = ["Risk monitoring detected the following conditions:\n"]
    for item in alerts:
        lines.append(
            f"- {item.get('symbol')} | drop: {item.get('drawdown_pct')}% "
            f"| threshold: {item.get('threshold_pct')}% "
            f"| severity: {item.get('severity', 'bad').upper()} "
            f"| price: {item.get('current_price')}"
        )
        message = item.get("message")
        if message:
            lines.append(f"  {message}")
    lines.append("\nPlease review the affected positions and take action if required.")
    return "\n".join(lines)


@celery_app.task(name="risk.alerts.send_email", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_risk_alert_email_task(recipient: str, subject: str, alerts: List[Dict[str, Any]]) -> None:
    """Send a risk alert email via the shared EmailService."""

    if not recipient:
        logger.warning("Risk alert email skipped due to missing recipient")
        return

    body = _format_alert_body(alerts)
    email_service = EmailService()

    async def _send() -> None:
        await email_service.send_email(recipient, subject, body, html=None)

    asyncio.run(_send())


__all__ = ["send_risk_alert_email_task"]

