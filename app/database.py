"""
Database Module - SQLite3 Management
Handles all database operations for users and likes history
"""
import sqlite3
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "likes_bot.db"):
        self.db_path = db_path
        self.init_db()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def init_db(self):
        """Initialize database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid TEXT UNIQUE NOT NULL,
                    telegram_id INTEGER,
                    nickname TEXT,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    plan_days INTEGER DEFAULT 0,
                    remaining_days INTEGER DEFAULT 0,
                    plan_expiry TIMESTAMP,
                    status TEXT DEFAULT 'inactive',
                    last_like_attempt TIMESTAMP,
                    next_retry TIMESTAMP,
                    last_error TEXT,
                    likes_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0
                )
            ''')
            
            # Likes history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS likes_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_uid TEXT NOT NULL,
                    date DATE NOT NULL,
                    likes_sent INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    likes_before INTEGER DEFAULT 0,
                    likes_after INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_uid) REFERENCES users(uid)
                )
            ''')
            
            # Retry attempts table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS retry_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_uid TEXT NOT NULL,
                    attempt_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reason TEXT,
                    next_retry TIMESTAMP,
                    FOREIGN KEY (user_uid) REFERENCES users(uid)
                )
            ''')
            
            # Plans table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_uid TEXT NOT NULL,
                    plan_name TEXT NOT NULL,
                    days_purchased INTEGER NOT NULL,
                    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_date TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    FOREIGN KEY (user_uid) REFERENCES users(uid)
                )
            ''')
            
            logger.info("Database initialized successfully")

    # ==================== USER OPERATIONS ====================
    
    def add_user(self, uid: str, telegram_id: int = None, nickname: str = None) -> bool:
        """Add a new user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO users (uid, telegram_id, nickname, status)
                    VALUES (?, ?, ?, 'inactive')
                ''', (uid, telegram_id, nickname))
                logger.info(f"User {uid} added successfully")
                return True
        except sqlite3.IntegrityError:
            logger.warning(f"User {uid} already exists")
            return False
        except Exception as e:
            logger.error(f"Error adding user {uid}: {e}")
            return False

    def get_user(self, uid: str) -> dict:
        """Get user information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users WHERE uid = ?', (uid,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user {uid}: {e}")
            return None

    def get_user_by_telegram(self, telegram_id: int) -> dict:
        """Get user by Telegram ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user by telegram ID {telegram_id}: {e}")
            return None

    def get_all_active_users(self) -> list:
        """Get all active users"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM users 
                    WHERE status = 'active' 
                    AND (plan_expiry IS NULL OR plan_expiry > datetime('now'))
                    ORDER BY uid
                ''')
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting active users: {e}")
            return []

    def update_user_status(self, uid: str, status: str, telegram_id: int = None, nickname: str = None) -> bool:
        """Update user status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if telegram_id or nickname:
                    cursor.execute('''
                        UPDATE users 
                        SET status = ?, telegram_id = COALESCE(?, telegram_id), nickname = COALESCE(?, nickname)
                        WHERE uid = ?
                    ''', (status, telegram_id, nickname, uid))
                else:
                    cursor.execute('UPDATE users SET status = ? WHERE uid = ?', (status, uid))
                logger.info(f"User {uid} status updated to {status}")
                return True
        except Exception as e:
            logger.error(f"Error updating user {uid} status: {e}")
            return False

    def activate_plan(self, uid: str, days: int, nickname: str = None) -> bool:
        """Activate a plan for user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                expiry_date = datetime.now() + timedelta(days=days)
                
                cursor.execute('''
                    UPDATE users 
                    SET status = 'active', 
                        plan_days = ?,
                        remaining_days = ?,
                        plan_expiry = ?,
                        nickname = COALESCE(?, nickname)
                    WHERE uid = ?
                ''', (days, days, expiry_date, nickname, uid))
                
                # Add plan record
                cursor.execute('''
                    INSERT INTO plans (user_uid, plan_name, days_purchased, end_date)
                    VALUES (?, ?, ?, ?)
                ''', (uid, f"{days}_days", days, expiry_date))
                
                logger.info(f"Plan activated for {uid}: {days} days until {expiry_date}")
                return True
        except Exception as e:
            logger.error(f"Error activating plan for {uid}: {e}")
            return False

    def remove_user(self, uid: str) -> bool:
        """Remove user from system"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM users WHERE uid = ?', (uid,))
                logger.info(f"User {uid} removed")
                return True
        except Exception as e:
            logger.error(f"Error removing user {uid}: {e}")
            return False

    def extend_plan(self, uid: str, additional_days: int) -> bool:
        """Extend user plan"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                user = self.get_user(uid)
                
                if not user:
                    return False
                
                current_expiry = datetime.fromisoformat(user['plan_expiry']) if user['plan_expiry'] else datetime.now()
                new_expiry = current_expiry + timedelta(days=additional_days)
                total_days = user['plan_days'] + additional_days
                
                cursor.execute('''
                    UPDATE users 
                    SET plan_days = ?,
                        remaining_days = remaining_days + ?,
                        plan_expiry = ?
                    WHERE uid = ?
                ''', (total_days, additional_days, new_expiry, uid))
                
                logger.info(f"Plan extended for {uid}: +{additional_days} days")
                return True
        except Exception as e:
            logger.error(f"Error extending plan for {uid}: {e}")
            return False

    # ==================== HISTORY OPERATIONS ====================
    
    def add_history(self, uid: str, likes_sent: int, success: int, fails: int, 
                   likes_before: int = 0, likes_after: int = 0, error: str = None) -> bool:
        """Add like attempt to history"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO likes_history 
                    (user_uid, date, likes_sent, success_count, fail_count, 
                     likes_before, likes_after, error_message)
                    VALUES (?, DATE('now'), ?, ?, ?, ?, ?, ?)
                ''', (uid, likes_sent, success, fails, likes_before, likes_after, error))
                
                # Update user stats
                cursor.execute('''
                    UPDATE users 
                    SET likes_count = likes_count + ?,
                        success_count = success_count + ?,
                        fail_count = fail_count + ?,
                        last_like_attempt = CURRENT_TIMESTAMP
                    WHERE uid = ?
                ''', (likes_sent, success, fails, uid))
                
                logger.info(f"History added for {uid}: {success} success, {fails} fails")
                return True
        except Exception as e:
            logger.error(f"Error adding history for {uid}: {e}")
            return False

    def get_history(self, uid: str, days: int = 30) -> list:
        """Get user like history"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM likes_history 
                    WHERE user_uid = ? AND date >= DATE('now', '-' || ? || ' days')
                    ORDER BY date DESC
                ''', (uid, days))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting history for {uid}: {e}")
            return []

    def get_today_status(self, uid: str) -> dict:
        """Get today's status for user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT 
                        COALESCE(SUM(likes_sent), 0) as total_sent,
                        COALESCE(SUM(success_count), 0) as success,
                        COALESCE(SUM(fail_count), 0) as fails
                    FROM likes_history 
                    WHERE user_uid = ? AND date = DATE('now')
                ''', (uid,))
                row = cursor.fetchone()
                return dict(row) if row else {'total_sent': 0, 'success': 0, 'fails': 0}
        except Exception as e:
            logger.error(f"Error getting today status for {uid}: {e}")
            return {'total_sent': 0, 'success': 0, 'fails': 0}

    # ==================== RETRY OPERATIONS ====================
    
    def add_retry(self, uid: str, reason: str, retry_time: datetime = None) -> bool:
        """Add retry attempt"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if retry_time is None:
                    from config import INTERVALO_RETENTATIVA
                    retry_time = datetime.now() + timedelta(hours=INTERVALO_RETENTATIVA)
                
                cursor.execute('''
                    INSERT INTO retry_attempts (user_uid, reason, next_retry)
                    VALUES (?, ?, ?)
                ''', (uid, reason, retry_time))
                
                cursor.execute('''
                    UPDATE users SET next_retry = ? WHERE uid = ?
                ''', (retry_time, uid))
                
                logger.info(f"Retry added for {uid}, next attempt at {retry_time}")
                return True
        except Exception as e:
            logger.error(f"Error adding retry for {uid}: {e}")
            return False

    def set_last_error(self, uid: str, error: str) -> bool:
        """Set last error for user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users SET last_error = ? WHERE uid = ?
                ''', (error, uid))
                return True
        except Exception as e:
            logger.error(f"Error setting error for {uid}: {e}")
            return False

    # ==================== CLEANUP OPERATIONS ====================
    
    def cleanup_expired_plans(self) -> int:
        """Deactivate users with expired plans"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users 
                    SET status = 'expired'
                    WHERE status = 'active' 
                    AND plan_expiry IS NOT NULL 
                    AND plan_expiry < datetime('now')
                ''')
                affected = cursor.rowcount
                logger.info(f"Cleanup: {affected} expired plans deactivated")
                return affected
        except Exception as e:
            logger.error(f"Error in cleanup: {e}")
            return 0
