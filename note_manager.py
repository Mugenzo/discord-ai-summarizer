"""
Note Manager - Handles storage and retrieval of notes
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import discord


class NoteManager:
    """Manages storage and retrieval of notes."""

    def __init__(self, notes_dir: str = 'notes'):
        self.notes_dir = Path(notes_dir)
        self.notes_dir.mkdir(exist_ok=True)
        self.notes_file = self.notes_dir / 'notes.json'
        self._notes: List[Dict] = []
        self._load_notes()

    def _load_notes(self):
        """Load notes from disk."""
        if self.notes_file.exists():
            try:
                with open(self.notes_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Convert timestamp strings back to datetime objects when loading
                    for note in data:
                        if 'timestamp' in note:
                            note['timestamp'] = datetime.fromisoformat(note['timestamp'])
                    self._notes = data
            except Exception as e:
                print(f"Error loading notes: {e}")
                self._notes = []
        else:
            self._notes = []

    def _save_notes(self):
        """Save notes to disk."""
        try:
            # Convert datetime objects to ISO format strings for JSON serialization
            notes_to_save = []
            for note in self._notes:
                note_copy = note.copy()
                if 'timestamp' in note_copy and isinstance(note_copy['timestamp'], datetime):
                    note_copy['timestamp'] = note_copy['timestamp'].isoformat()
                # Don't save full message objects, just metadata
                if 'messages' in note_copy:
                    note_copy['message_count'] = len(note_copy['messages'])
                    # Save minimal message info instead of full objects
                    note_copy['message_preview'] = [
                        {
                            'author': msg.author.name if hasattr(msg, 'author') else 'Unknown',
                            'content': msg.content[:100] if hasattr(msg, 'content') else '',
                            'timestamp': msg.created_at.isoformat() if hasattr(msg, 'created_at') else None
                        }
                        for msg in note_copy['messages'][:5]  # Only save first 5 as preview
                    ]
                    del note_copy['messages']
                notes_to_save.append(note_copy)

            with open(self.notes_file, 'w', encoding='utf-8') as f:
                json.dump(notes_to_save, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving notes: {e}")

    def save_note(
        self,
        channel_id: int,
        channel_name: str,
        messages: List[discord.Message],
        summary: str,
        timestamp: datetime
    ) -> Dict:
        """Save a new note."""
        note_id = len(self._notes) + 1

        note = {
            'id': note_id,
            'channel_id': channel_id,
            'channel_name': channel_name,
            'messages': messages,  # Keep in memory for now
            'message_count': len(messages),
            'summary': summary,
            'timestamp': timestamp
        }

        self._notes.append(note)
        self._save_notes()

        return note

    def get_note(self, note_id: int) -> Optional[Dict]:
        """Get a note by ID."""
        for note in self._notes:
            if note['id'] == note_id:
                # Convert timestamp string back to datetime if needed
                if isinstance(note.get('timestamp'), str):
                    note['timestamp'] = datetime.fromisoformat(note['timestamp'])
                return note
        return None

    def get_notes_for_channel(self, channel_id: int, limit: int = 10) -> List[Dict]:
        """Get recent notes for a specific channel."""
        channel_notes = [
            note for note in self._notes
            if note['channel_id'] == channel_id
        ]

        # Sort by timestamp (newest first)
        channel_notes.sort(key=lambda x: x.get('timestamp', datetime.min), reverse=True)

        # Convert timestamp strings back to datetime if needed
        for note in channel_notes:
            if isinstance(note.get('timestamp'), str):
                note['timestamp'] = datetime.fromisoformat(note['timestamp'])

        return channel_notes[:limit]

    def get_total_notes(self) -> int:
        """Get total number of notes."""
        return len(self._notes)

    def get_all_notes(self, limit: int = None) -> List[Dict]:
        """Get all notes, optionally limited."""
        notes = sorted(self._notes, key=lambda x: x.get('timestamp', datetime.min), reverse=True)

        # Convert timestamp strings back to datetime if needed
        for note in notes:
            if isinstance(note.get('timestamp'), str):
                note['timestamp'] = datetime.fromisoformat(note['timestamp'])

        if limit:
            return notes[:limit]
        return notes

