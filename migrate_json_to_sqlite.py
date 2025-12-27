"""
Migration script to convert existing JSON notes to SQLite database.
Run this once to migrate your old notes.json file to the new database format.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from database_manager import DatabaseManager

def migrate_notes():
    """Migrate notes from JSON to SQLite database."""
    notes_file = Path('notes/notes.json')
    db_manager = DatabaseManager()
    
    if not notes_file.exists():
        print("No notes.json file found. Nothing to migrate.")
        return
    
    print(f"Reading notes from {notes_file}...")
    with open(notes_file, 'r', encoding='utf-8') as f:
        notes = json.load(f)
    
    if not notes:
        print("No notes found in JSON file.")
        return
    
    print(f"Found {len(notes)} notes to migrate...")
    
    migrated = 0
    skipped = 0
    
    for note in notes:
        try:
            # Parse timestamp
            timestamp = note.get('timestamp')
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)
            
            # Create discussion record
            discussion_id = db_manager.create_discussion(
                voice_channel_id=note.get('channel_id', 0),
                channel_name=note.get('channel_name', 'Unknown Channel'),
                started_by_user_id=0,  # Old notes don't have this
                started_by_username=None,
                started_at=timestamp,
                guild_id=None
            )
            
            # Update with end time (use same as start time for old notes)
            db_manager.update_discussion(
                discussion_id=discussion_id,
                ended_at=timestamp,
                duration_seconds=0
            )
            
            # Add general summary if available
            summary = note.get('summary')
            if summary:
                db_manager.add_summary(
                    discussion_id=discussion_id,
                    summary_text=summary,
                    summary_type='general'
                )
            
            # Try to add transcriptions from messages if available
            messages = note.get('messages', [])
            if messages:
                # Old format might have transcriptions in messages
                for msg in messages:
                    if isinstance(msg, dict):
                        user_id = msg.get('user_id', 0)
                        text = msg.get('text') or msg.get('transcription', '')
                        username = msg.get('username', f'User {user_id}')
                        msg_timestamp = msg.get('timestamp')
                        if isinstance(msg_timestamp, str):
                            msg_timestamp = datetime.fromisoformat(msg_timestamp)
                        elif not isinstance(msg_timestamp, datetime):
                            msg_timestamp = timestamp
                        
                        if text:
                            db_manager.add_transcription(
                                discussion_id=discussion_id,
                                user_id=user_id,
                                transcription_text=text,
                                username=username,
                                timestamp=msg_timestamp
                            )
            
            migrated += 1
            print(f"✓ Migrated note #{note.get('id', '?')} -> discussion #{discussion_id}")
            
        except Exception as e:
            print(f"✗ Error migrating note #{note.get('id', '?')}: {e}")
            skipped += 1
    
    print(f"\nMigration complete!")
    print(f"  Migrated: {migrated}")
    print(f"  Skipped: {skipped}")
    print(f"\nYour old notes.json file is still available at {notes_file}")
    print("You can delete it after verifying the migration was successful.")

if __name__ == '__main__':
    migrate_notes()

