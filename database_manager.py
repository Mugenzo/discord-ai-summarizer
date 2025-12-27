"""
Database Manager - Handles storage and retrieval of discussions, transcriptions, and summaries using SQLite
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import json
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite database for discussions, transcriptions, and summaries."""

    def __init__(self, db_path: str = 'notes/discussions.db'):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
        return conn

    def _init_database(self):
        """Initialize database tables if they don't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Discussions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS discussions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voice_channel_id INTEGER NOT NULL,
                channel_name TEXT NOT NULL,
                started_by_user_id INTEGER NOT NULL,
                started_by_username TEXT,
                started_at TIMESTAMP NOT NULL,
                ended_at TIMESTAMP,
                combined_audio_file TEXT,
                user_audio_files TEXT,  -- JSON array of file paths
                duration_seconds REAL,
                guild_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Transcriptions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transcriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discussion_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                transcription_text TEXT NOT NULL,
                audio_file_path TEXT,
                timestamp TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
            )
        ''')

        # Summaries table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discussion_id INTEGER NOT NULL,
                summary_type TEXT NOT NULL,  -- 'person' or 'general'
                user_id INTEGER,  -- NULL for general summary
                username TEXT,  -- NULL for general summary
                summary_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
            )
        ''')

        # Create indexes for better query performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_discussions_channel ON discussions(voice_channel_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_discussions_started_at ON discussions(started_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transcriptions_discussion ON transcriptions(discussion_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transcriptions_user ON transcriptions(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_summaries_discussion ON summaries(discussion_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_summaries_type ON summaries(summary_type)')

        conn.commit()
        conn.close()
        logger.info(f'Database initialized at {self.db_path}')

    def create_discussion(
        self,
        voice_channel_id: int,
        channel_name: str,
        started_by_user_id: int,
        started_by_username: Optional[str] = None,
        started_at: Optional[datetime] = None,
        guild_id: Optional[int] = None
    ) -> int:
        """Create a new discussion record and return its ID."""
        if started_at is None:
            started_at = datetime.now()

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO discussions 
            (voice_channel_id, channel_name, started_by_user_id, started_by_username, 
             started_at, guild_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (voice_channel_id, channel_name, started_by_user_id, started_by_username, 
              started_at, guild_id))

        discussion_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.debug(f'Created discussion {discussion_id} for channel {channel_name}')
        return discussion_id

    def update_discussion(
        self,
        discussion_id: int,
        ended_at: Optional[datetime] = None,
        combined_audio_file: Optional[str] = None,
        user_audio_files: Optional[Dict[int, str]] = None,
        duration_seconds: Optional[float] = None
    ):
        """Update a discussion with end time and audio file information."""
        conn = self._get_connection()
        cursor = conn.cursor()

        updates = []
        params = []

        if ended_at is not None:
            updates.append('ended_at = ?')
            params.append(ended_at)

        if combined_audio_file is not None:
            updates.append('combined_audio_file = ?')
            params.append(combined_audio_file)

        if user_audio_files is not None:
            updates.append('user_audio_files = ?')
            params.append(json.dumps(user_audio_files))

        if duration_seconds is not None:
            updates.append('duration_seconds = ?')
            params.append(duration_seconds)

        if updates:
            params.append(discussion_id)
            query = f'UPDATE discussions SET {", ".join(updates)} WHERE id = ?'
            cursor.execute(query, params)
            conn.commit()

        conn.close()
        logger.debug(f'Updated discussion {discussion_id}')

    def add_transcription(
        self,
        discussion_id: int,
        user_id: int,
        transcription_text: str,
        username: Optional[str] = None,
        audio_file_path: Optional[str] = None,
        timestamp: Optional[datetime] = None
    ) -> int:
        """Add a transcription to a discussion."""
        if timestamp is None:
            timestamp = datetime.now()

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO transcriptions 
            (discussion_id, user_id, username, transcription_text, audio_file_path, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (discussion_id, user_id, username, transcription_text, audio_file_path, timestamp))

        transcription_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.debug(f'Added transcription {transcription_id} for user {user_id} in discussion {discussion_id}')
        return transcription_id

    def add_summary(
        self,
        discussion_id: int,
        summary_text: str,
        summary_type: str = 'general',  # 'person' or 'general'
        user_id: Optional[int] = None,
        username: Optional[str] = None
    ) -> int:
        """Add a summary (per-person or general) to a discussion."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO summaries 
            (discussion_id, summary_type, user_id, username, summary_text)
            VALUES (?, ?, ?, ?, ?)
        ''', (discussion_id, summary_type, user_id, username, summary_text))

        summary_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.debug(f'Added {summary_type} summary {summary_id} for discussion {discussion_id}')
        return summary_id

    def get_discussion(self, discussion_id: int) -> Optional[Dict]:
        """Get a discussion by ID with all related data."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Get discussion
        cursor.execute('SELECT * FROM discussions WHERE id = ?', (discussion_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        discussion = dict(row)

        # Get transcriptions
        cursor.execute('''
            SELECT * FROM transcriptions 
            WHERE discussion_id = ? 
            ORDER BY timestamp ASC
        ''', (discussion_id,))
        discussion['transcriptions'] = [dict(r) for r in cursor.fetchall()]

        # Get summaries
        cursor.execute('''
            SELECT * FROM summaries 
            WHERE discussion_id = ? 
            ORDER BY summary_type, user_id
        ''', (discussion_id,))
        discussion['summaries'] = [dict(r) for r in cursor.fetchall()]

        # Parse user_audio_files JSON
        if discussion.get('user_audio_files'):
            try:
                discussion['user_audio_files'] = json.loads(discussion['user_audio_files'])
            except (json.JSONDecodeError, TypeError):
                discussion['user_audio_files'] = {}

        conn.close()
        return discussion

    def get_discussions_for_channel(
        self, 
        voice_channel_id: int, 
        limit: int = 10
    ) -> List[Dict]:
        """Get recent discussions for a specific voice channel."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM discussions 
            WHERE voice_channel_id = ? 
            ORDER BY started_at DESC 
            LIMIT ?
        ''', (voice_channel_id, limit))

        discussions = [dict(row) for row in cursor.fetchall()]

        # Parse user_audio_files JSON for each discussion
        for discussion in discussions:
            if discussion.get('user_audio_files'):
                try:
                    discussion['user_audio_files'] = json.loads(discussion['user_audio_files'])
                except (json.JSONDecodeError, TypeError):
                    discussion['user_audio_files'] = {}

        conn.close()
        return discussions

    def get_all_discussions(self, limit: int = None) -> List[Dict]:
        """Get all discussions, optionally limited."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if limit:
            cursor.execute('''
                SELECT * FROM discussions 
                ORDER BY started_at DESC 
                LIMIT ?
            ''', (limit,))
        else:
            cursor.execute('''
                SELECT * FROM discussions 
                ORDER BY started_at DESC
            ''')

        discussions = [dict(row) for row in cursor.fetchall()]

        # Parse user_audio_files JSON for each discussion
        for discussion in discussions:
            if discussion.get('user_audio_files'):
                try:
                    discussion['user_audio_files'] = json.loads(discussion['user_audio_files'])
                except (json.JSONDecodeError, TypeError):
                    discussion['user_audio_files'] = {}

        conn.close()
        return discussions

    def get_total_discussions(self) -> int:
        """Get total number of discussions."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM discussions')
        count = cursor.fetchone()[0]

        conn.close()
        return count

    def get_transcriptions_for_discussion(self, discussion_id: int) -> List[Dict]:
        """Get all transcriptions for a discussion."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM transcriptions 
            WHERE discussion_id = ? 
            ORDER BY timestamp ASC
        ''', (discussion_id,))

        transcriptions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return transcriptions

    def get_summaries_for_discussion(self, discussion_id: int) -> Dict[str, List[Dict]]:
        """Get all summaries for a discussion, organized by type."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM summaries 
            WHERE discussion_id = ? 
            ORDER BY summary_type, user_id
        ''', (discussion_id,))

        summaries = [dict(row) for row in cursor.fetchall()]
        conn.close()

        # Organize by type
        result = {
            'general': [],
            'person': []
        }

        for summary in summaries:
            summary_type = summary.get('summary_type', 'general')
            if summary_type == 'person':
                result['person'].append(summary)
            else:
                result['general'].append(summary)

        return result

    def delete_discussion(self, discussion_id: int) -> bool:
        """Delete a discussion and all related transcriptions and summaries (CASCADE)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('DELETE FROM discussions WHERE id = ?', (discussion_id,))
        deleted = cursor.rowcount > 0

        conn.commit()
        conn.close()

        if deleted:
            logger.debug(f'Deleted discussion {discussion_id} and related data')
        return deleted

