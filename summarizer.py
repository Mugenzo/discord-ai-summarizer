"""
Local AI Summarizer using Ollama
"""

import aiohttp
from typing import Optional

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0  # For consistent results
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False


class LocalSummarizer:
    """Handles local AI summarization using Ollama."""

    def __init__(self, api_url: str = 'http://localhost:11434', model: str = 'llama3'):
        self.api_url = api_url.rstrip('/')
        self.model = model

    async def check_connection(self) -> bool:
        """Check if Ollama API is accessible."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f'{self.api_url}/api/tags', timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        return True
                    return False
        except Exception:
            return False

    def _detect_language(self, text: str) -> str:
        """Detect the main language of the text."""
        if not LANGDETECT_AVAILABLE:
            return "en"  # Default to English

        try:
            # Use first 1000 chars for faster detection
            sample = text[:1000] if len(text) > 1000 else text
            if not sample.strip():
                return "en"
            language = detect(sample)
            return language
        except Exception as e:
            print(f'Language detection error: {e}')
            return "en"  # Default to English

    def _get_language_name(self, lang_code: str) -> str:
        """Get language name from code."""
        language_names = {
            'en': 'English',
            'es': 'Spanish',
            'fr': 'French',
            'de': 'German',
            'it': 'Italian',
            'pt': 'Portuguese',
            'ru': 'Russian',
            'ja': 'Japanese',
            'ko': 'Korean',
            'zh': 'Chinese',
            'ar': 'Arabic',
            'hi': 'Hindi',
            'pl': 'Polish',
            'nl': 'Dutch',
            'tr': 'Turkish',
            'sv': 'Swedish',
            'da': 'Danish',
            'no': 'Norwegian',
            'fi': 'Finnish',
            'cs': 'Czech',
            'uk': 'Ukrainian',
        }
        return language_names.get(lang_code, 'English')

    async def summarize(self, conversation_text: str, channel_name: str, language: Optional[str] = None) -> str:
        """
        Summarize a conversation using local AI.

        Args:
            conversation_text: The formatted conversation text
            channel_name: Name of the channel for context
            language: Optional language code. If None, will be auto-detected.

        Returns:
            Summary string
        """
        # Detect language if not provided
        if language is None:
            language = self._detect_language(conversation_text)

        language_name = self._get_language_name(language)

        # Create prompt in the detected language
        if language == 'en':
            prompt = f"""You are a helpful assistant that summarizes Discord channel discussions.

Channel: {channel_name}

Below is a conversation from this Discord channel. Please provide a concise, well-structured summary that captures:
1. The main topics discussed
2. Key decisions or conclusions reached
3. Important questions raised
4. Action items or next steps (if any)

Conversation:
{conversation_text}

Summary:"""
        else:
            # For non-English, instruct the model to respond in that language
            prompt = f"""You are a helpful assistant that summarizes Discord channel discussions.

Channel: {channel_name}
Language: {language_name}

Below is a conversation from this Discord channel. The conversation is mainly in {language_name}.
Please provide a concise, well-structured summary IN {language_name.upper()} that captures:
1. The main topics discussed
2. Key decisions or conclusions reached
3. Important questions raised
4. Action items or next steps (if any)

IMPORTANT: Write the summary in {language_name}, the same language as the conversation.

Conversation:
{conversation_text}

Summary (in {language_name}):"""

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f'{self.api_url}/api/generate',
                    json={
                        'model': self.model,
                        'prompt': prompt,
                        'stream': False,
                        'options': {
                            'temperature': 0.3,  # Lower temperature for more focused summaries
                            'top_p': 0.9,
                        }
                    },
                    timeout=aiohttp.ClientTimeout(total=120)  # 2 minute timeout
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"Ollama API error: {response.status} - {error_text}")

                    result = await response.json()
                    summary = result.get('response', '').strip()

                    if not summary:
                        raise Exception("Empty response from Ollama")

                    # Remove translation text if LLM added it despite instructions
                    import re
                    # Remove (Translation: ...) patterns
                    summary = re.sub(r'\(Translation:\s*[^)]+\)', '', summary, flags=re.IGNORECASE)
                    # Remove standalone "Translation:" lines
                    summary = re.sub(r'^Translation:\s*.*$', '', summary, flags=re.IGNORECASE | re.MULTILINE)
                    summary = summary.strip()

                    return summary

        except aiohttp.ClientError as e:
            raise Exception(f"Connection error: {str(e)}")
        except Exception as e:
            raise Exception(f"Summarization error: {str(e)}")

    async def summarize_person_tasks(self, person_text: str, person_name: str, language: Optional[str] = None) -> str:
        """
        Generate a summary focused on a specific person's contributions and tasks.

        Args:
            person_text: The transcription text from this person
            person_name: Name of the person
            language: Optional language code. If None, will be auto-detected.

        Returns:
            Summary string with tasks and contributions
        """
        # Detect language if not provided
        if language is None:
            language = self._detect_language(person_text)

        language_name = self._get_language_name(language)

        # Create prompt focused on person's tasks and contributions
        if language == 'en':
            prompt = f"""You are a helpful assistant that analyzes individual contributions in a meeting/discussion.

Person: {person_name}

Below is what {person_name} said during the discussion. Please provide a concise summary that focuses on:
1. What topics or issues {person_name} discussed
2. What decisions or opinions {person_name} expressed
3. What tasks, action items, or responsibilities {person_name} mentioned or was assigned
4. Any questions {person_name} raised
5. Any commitments or promises {person_name} made

Person's contributions:
{person_text}

Summary for {person_name}:"""
        else:
            prompt = f"""You are a helpful assistant that analyzes individual contributions in a meeting/discussion.

Person: {person_name}
Language: {language_name}

Below is what {person_name} said during the discussion (in {language_name}). Please provide a concise summary IN {language_name.upper()} that focuses on:
1. What topics or issues {person_name} discussed
2. What decisions or opinions {person_name} expressed
3. What tasks, action items, or responsibilities {person_name} mentioned or was assigned
4. Any questions {person_name} raised
5. Any commitments or promises {person_name} made

IMPORTANT: 
- Write the summary in {language_name}, the same language as the conversation.
- DO NOT add translations or "(Translation: ...)" text.
- Write ONLY the summary in {language_name}, nothing else.

Person's contributions:
{person_text}

Summary for {person_name} (in {language_name}):"""

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f'{self.api_url}/api/generate',
                    json={
                        'model': self.model,
                        'prompt': prompt,
                        'stream': False,
                        'options': {
                            'temperature': 0.3,
                            'top_p': 0.9,
                        }
                    },
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"Ollama API error: {response.status} - {error_text}")

                    result = await response.json()
                    summary = result.get('response', '').strip()

                    if not summary:
                        raise Exception("Empty response from Ollama")

                    # Remove translation text if LLM added it despite instructions
                    import re
                    # Remove (Translation: ...) patterns
                    summary = re.sub(r'\(Translation:\s*[^)]+\)', '', summary, flags=re.IGNORECASE)
                    # Remove standalone "Translation:" lines
                    summary = re.sub(r'^Translation:\s*.*$', '', summary, flags=re.IGNORECASE | re.MULTILINE)
                    summary = summary.strip()

                    return summary

        except aiohttp.ClientError as e:
            raise Exception(f"Connection error: {str(e)}")
        except Exception as e:
            raise Exception(f"Summarization error: {str(e)}")

