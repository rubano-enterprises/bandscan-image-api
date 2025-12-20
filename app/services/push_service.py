"""Push notification service for FCM and APNs."""

import json
import logging
from typing import List, Dict, Optional, Tuple
import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class PushNotificationService:
    """Service for sending push notifications via FCM and APNs."""

    async def send_notification(
        self,
        tokens: List[Dict[str, str]],
        title: str,
        body: str,
        data: Optional[Dict] = None,
    ) -> Tuple[int, int]:
        """
        Send push notification to device tokens.

        Args:
            tokens: List of token dicts with 'token' and 'platform' keys
            title: Notification title
            body: Notification body
            data: Optional custom data payload

        Returns:
            Tuple of (success_count, failure_count)
        """
        # Separate tokens by platform
        fcm_tokens = [t["token"] for t in tokens if t["platform"] == "android"]
        apns_tokens = [t["token"] for t in tokens if t["platform"] == "ios"]

        success_count = 0
        failure_count = 0

        # Send to Android via FCM
        if fcm_tokens:
            fcm_success, fcm_failure = await self._send_fcm(
                fcm_tokens, title, body, data
            )
            success_count += fcm_success
            failure_count += fcm_failure

        # Send to iOS via APNs
        if apns_tokens:
            apns_success, apns_failure = await self._send_apns(
                apns_tokens, title, body, data
            )
            success_count += apns_success
            failure_count += apns_failure

        return success_count, failure_count

    async def _send_fcm(
        self,
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict] = None,
    ) -> Tuple[int, int]:
        """Send notifications via Firebase Cloud Messaging."""
        if not settings.fcm_server_key:
            logger.warning("FCM server key not configured, skipping Android notifications")
            return 0, len(tokens)

        success_count = 0
        failure_count = 0

        async with httpx.AsyncClient() as client:
            for token in tokens:
                try:
                    payload = {
                        "to": token,
                        "notification": {
                            "title": title,
                            "body": body,
                            "sound": "default",
                        },
                        "priority": "high",
                    }

                    if data:
                        payload["data"] = data

                    response = await client.post(
                        "https://fcm.googleapis.com/fcm/send",
                        headers={
                            "Authorization": f"Bearer {settings.fcm_server_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                        timeout=10.0,
                    )

                    if response.status_code == 200:
                        result = response.json()
                        if result.get("success", 0) > 0:
                            success_count += 1
                        else:
                            failure_count += 1
                            logger.warning(
                                f"FCM send failed for token: {result.get('results', [{}])[0].get('error')}"
                            )
                    else:
                        failure_count += 1
                        logger.error(
                            f"FCM request failed: {response.status_code} - {response.text}"
                        )

                except Exception as e:
                    failure_count += 1
                    logger.error(f"FCM exception: {e}")

        return success_count, failure_count

    async def _send_apns(
        self,
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict] = None,
    ) -> Tuple[int, int]:
        """Send notifications via Apple Push Notification Service."""
        if not all([settings.apns_key_id, settings.apns_team_id, settings.apns_bundle_id]):
            logger.warning("APNs not fully configured, skipping iOS notifications")
            return 0, len(tokens)

        # APNs implementation requires JWT token generation and HTTP/2
        # This is a simplified version - in production you'd use a library like aioapns
        logger.warning("APNs integration not yet implemented - tokens skipped")
        return 0, len(tokens)


# Global service instance
push_service = PushNotificationService()
