"""
Scheduler Module - APScheduler Integration
Handles automatic like sending at scheduled times
"""
import logging
from datetime import datetime, time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from app.database import Database
import asyncio
import aiohttp
from app.token_manager import TokenCache, get_headers
from app.utils.protobuf_utils import encode_uid, create_protobuf, decode_info
from app.utils.crypto_utils import encrypt_aes

logger = logging.getLogger(__name__)


class LikeScheduler:
    def __init__(self, db: Database, servers: dict, token_cache: TokenCache, timezone: str = "America/Sao_Paulo"):
        self.db = db
        self.servers = servers
        self.token_cache = token_cache
        self.timezone = pytz.timezone(timezone)
        self.scheduler = BackgroundScheduler(timezone=self.timezone)
        self.is_running = False

    def start(self, send_time: str = "13:00"):
        """Start the scheduler"""
        try:
            hour, minute = map(int, send_time.split(':'))
            
            # Schedule daily like sending
            self.scheduler.add_job(
                self.send_daily_likes,
                CronTrigger(hour=hour, minute=minute, timezone=self.timezone),
                id='daily_like_sender',
                name='Daily Like Sender',
                replace_existing=True
            )
            
            # Schedule cleanup of expired plans every day at 00:00
            self.scheduler.add_job(
                self.cleanup_expired,
                CronTrigger(hour=0, minute=0, timezone=self.timezone),
                id='cleanup_expired',
                name='Cleanup Expired Plans',
                replace_existing=True
            )
            
            self.scheduler.start()
            self.is_running = True
            logger.info(f"Scheduler started. Daily likes at {send_time} ({self.timezone})")
        except Exception as e:
            logger.error(f"Error starting scheduler: {e}")

    def stop(self):
        """Stop the scheduler"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown()
                self.is_running = False
                logger.info("Scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")

    async def send_daily_likes(self):
        """Send likes to all active users"""
        logger.info("Starting daily like sending process...")
        
        try:
            active_users = self.db.get_all_active_users()
            logger.info(f"Found {len(active_users)} active users")
            
            for user in active_users:
                try:
                    await self.send_likes_to_user(user)
                except Exception as e:
                    logger.error(f"Error sending likes to {user['uid']}: {e}")
                    self.db.add_retry(user['uid'], str(e))
                    self.db.set_last_error(user['uid'], str(e))
                    
        except Exception as e:
            logger.error(f"Error in daily like sending: {e}")

    async def send_likes_to_user(self, user: dict):
        """Send likes to a specific user"""
        uid = user['uid']
        logger.info(f"Sending likes to user {uid}...")
        
        try:
            # Detect player region
            region, player_info = await self._detect_player_region(uid)
            
            if not player_info or not region:
                error_msg = "Player not found on any server"
                logger.warning(f"{error_msg} for UID {uid}")
                self.db.add_history(uid, 0, 0, 0, error=error_msg)
                return
            
            likes_before = player_info.AccountInfo.Likes
            nickname = player_info.AccountInfo.PlayerNickname
            
            logger.info(f"Found player: {nickname} (UID: {uid}) with {likes_before} likes on {region}")
            
            # Send likes
            result = await self._send_likes(uid, region)
            
            # Get updated like count
            tokens = self.token_cache.get_tokens(region)
            likes_after = likes_before
            
            if tokens:
                try:
                    info_url = f"{self.servers[region]}/GetPlayerPersonalShow"
                    new_info = await self._get_player_info(uid, info_url, tokens[0], region)
                    if new_info:
                        likes_after = new_info.AccountInfo.Likes
                except Exception as e:
                    logger.error(f"Error getting updated likes: {e}")
                    likes_after = likes_before
            
            # Record in history
            likes_added = likes_after - likes_before
            self.db.add_history(
                uid=uid,
                likes_sent=result['sent'],
                success=result['added'],
                fails=result['sent'] - result['added'],
                likes_before=likes_before,
                likes_after=likes_after
            )
            
            # Update user nickname
            self.db.update_user_status(uid, 'active', nickname=nickname)
            
            logger.info(f"Likes sent to {uid}: {likes_added} added")
            
        except Exception as e:
            logger.error(f"Error sending likes to user {uid}: {e}")
            self.db.add_history(uid, 0, 0, 0, error=str(e))
            self.db.add_retry(uid, str(e))

    async def _detect_player_region(self, uid: str):
        """Detect which server the player is on"""
        for region_key in self.servers.keys():
            try:
                tokens = self.token_cache.get_tokens(region_key)
                if not tokens:
                    continue
                
                info_url = f"{self.servers[region_key]}/GetPlayerPersonalShow"
                player_info = await self._get_player_info(uid, info_url, tokens[0], region_key)
                
                if player_info and player_info.AccountInfo.PlayerNickname:
                    return region_key, player_info
            except Exception as e:
                logger.debug(f"Region {region_key} check failed: {e}")
                continue
        
        return None, None

    async def _get_player_info(self, uid: str, url: str, token: str, region: str):
        """Get player info from API"""
        try:
            headers = get_headers(token)
            data = bytes.fromhex(encode_uid(uid))
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        return decode_info(content)
            return None
        except Exception as e:
            logger.error(f"Error getting player info: {e}")
            return None

    async def _send_likes(self, uid: str, region: str):
        """Send likes to user"""
        try:
            tokens = self.token_cache.get_tokens(region)
            like_url = f"{self.servers[region]}/LikeProfile"
            encrypted = encrypt_aes(create_protobuf(uid, region))
            
            tasks = []
            for token in tokens:
                tasks.append(self._async_post_like(like_url, bytes.fromhex(encrypted), token))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            successful = sum(1 for r in results if r and not isinstance(r, Exception))
            
            return {
                'sent': len(results),
                'added': successful
            }
        except Exception as e:
            logger.error(f"Error sending likes: {e}")
            return {'sent': 0, 'added': 0}

    async def _async_post_like(self, url: str, data: bytes, token: str):
        """Post like request asynchronously"""
        try:
            headers = get_headers(token)
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, headers=headers, timeout=10) as resp:
                    return await resp.read() if resp.status == 200 else None
        except Exception as e:
            logger.error(f"Async like request failed: {e}")
            return None

    def cleanup_expired(self):
        """Clean up expired plans"""
        try:
            logger.info("Running cleanup of expired plans...")
            affected = self.db.cleanup_expired_plans()
            logger.info(f"Cleanup completed: {affected} plans deactivated")
        except Exception as e:
            logger.error(f"Error in cleanup: {e}")

    def get_status(self) -> dict:
        """Get scheduler status"""
        return {
            'is_running': self.is_running,
            'next_run_time': str(self.scheduler.get_job('daily_like_sender').next_run_time) if self.scheduler.get_job('daily_like_sender') else None,
            'active_users': len(self.db.get_all_active_users())
        }


# Global scheduler instance
_scheduler = None


def init_scheduler(db: Database, servers: dict, token_cache: TokenCache, 
                   timezone: str = "America/Sao_Paulo", send_time: str = "13:00"):
    """Initialize global scheduler"""
    global _scheduler
    _scheduler = LikeScheduler(db, servers, token_cache, timezone)
    _scheduler.start(send_time)
    return _scheduler


def get_scheduler() -> LikeScheduler:
    """Get global scheduler instance"""
    return _scheduler


def stop_scheduler():
    """Stop global scheduler"""
    if _scheduler:
        _scheduler.stop()
