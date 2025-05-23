"""
Text-to-speech functionality for ARIS.
"""
import os
import asyncio
from typing import Optional

from .logging_utils import log_debug, log_warning, log_error
from .interrupt_handler import get_interrupt_handler, InterruptContext

# TTS configuration
TTS_VOICE = "nova"  # Default TTS voice

# TTS playback lock to prevent overlapping speech
_tts_playback_lock = asyncio.Lock()

# Voice dependencies
_voice_dependencies_loaded = False
_async_openai_client_for_tts = None

# Current TTS playback task for interruption
_current_tts_task: Optional[asyncio.Task] = None

# TTS interruption event
_tts_interrupt_event = asyncio.Event()

# Dynamically loaded modules
OpenAI = None
AsyncOpenAI = None
LocalAudioPlayer = None

def _ensure_voice_dependencies():
    """
    Ensure that all voice-related dependencies are loaded.
    
    Returns:
        True if dependencies are successfully loaded, False otherwise
    """
    global _voice_dependencies_loaded, OpenAI, AsyncOpenAI, LocalAudioPlayer
    
    if _voice_dependencies_loaded:
        return True
    
    try:
        from RealtimeSTT import AudioToTextRecorder as DynRecorder
        import soundfile as dyn_sf
        from openai import OpenAI as DynOpenAI, AsyncOpenAI as DynAsyncOpenAI
        from openai.helpers import LocalAudioPlayer as DynLocalAudioPlayer

        global Recorder, sf
        Recorder = DynRecorder
        sf = dyn_sf
        OpenAI = DynOpenAI
        AsyncOpenAI = DynAsyncOpenAI
        LocalAudioPlayer = DynLocalAudioPlayer

        _voice_dependencies_loaded = True
        return True
    except ImportError as ie:
        from prompt_toolkit import print_formatted_text
        from prompt_toolkit.formatted_text import FormattedText
        
        # This import should be available as it's a direct dependency
        try:
            from .cli import cli_style
        except ImportError:
            cli_style = None
            
        print_formatted_text(FormattedText([
            ('class:error', f"Voice mode dependencies missing: {ie}. Please run 'poetry install --with voice' or 'pip install .[voice]'.")
        ]), style=cli_style)
        
        log_error(f"Failed to load voice dependencies: {ie}")
        return False

def _init_openai_clients_for_tts():
    """
    Initialize OpenAI clients for TTS.
    
    Returns:
        True if clients are successfully initialized, False otherwise
    """
    global _async_openai_client_for_tts
    
    log_debug("[TTS Client Init] Attempting to initialize OpenAI clients for TTS.")
    
    if not OpenAI or not AsyncOpenAI:  # Dependencies not loaded
        log_warning("[TTS Client Init] OpenAI or AsyncOpenAI classes not available (dependencies not loaded).")
        return False
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        log_warning("[TTS Client Init] OPENAI_API_KEY environment variable not found.")
        
        # Keep the user-facing print for immediate feedback if console is visible
        from prompt_toolkit import print_formatted_text
        from prompt_toolkit.formatted_text import FormattedText
        
        # This import should be available as it's a direct dependency
        try:
            from .cli import cli_style
        except ImportError:
            cli_style = None
            
        print_formatted_text(FormattedText([
            ('class:error', "OPENAI_API_KEY environment variable is required for voice output.")
        ]), style=cli_style)
        
        return False
    else:
        # For security, don't log the full key, just that it was found.
        log_debug(f"[TTS Client Init] OPENAI_API_KEY found (length: {len(api_key)}).")

    try:
        if _async_openai_client_for_tts is None:
            log_debug("[TTS Client Init] Initializing asynchronous OpenAI client...")
            _async_openai_client_for_tts = AsyncOpenAI(api_key=api_key)
            log_debug("[TTS Client Init] Asynchronous OpenAI client initialized.")
        return True
    except Exception as e:
        log_error(f"[TTS Client Init] Error initializing OpenAI clients: {e}", exception_info=str(e))
        
        from prompt_toolkit import print_formatted_text
        from prompt_toolkit.formatted_text import FormattedText
        
        # This import should be available as it's a direct dependency
        try:
            from .cli import cli_style
        except ImportError:
            cli_style = None
            
        print_formatted_text(FormattedText([
            ('class:error', f"Error initializing OpenAI clients for TTS: {e}")
        ]), style=cli_style)
        
        return False

def interrupt_tts():
    """
    Interrupt current TTS playback.
    
    This function is called by the interrupt handler when CTRL+C
    is pressed during TTS playback.
    """
    global _current_tts_task
    
    log_debug("[TTS] Interrupt requested")
    _tts_interrupt_event.set()
    
    # Cancel the current TTS task if it exists
    if _current_tts_task and not _current_tts_task.done():
        log_debug("[TTS] Cancelling current TTS task")
        _current_tts_task.cancel()

async def tts_speak(text: str):
    """
    Speak the given text using TTS.
    
    Args:
        text: The text to speak
    """
    global _current_tts_task, _tts_interrupt_event
    
    log_debug(f"[TTS] Attempting to speak: '{text[:50]}...'")
    
    if not _async_openai_client_for_tts:
        if not _ensure_voice_dependencies() or not _init_openai_clients_for_tts():
            log_warning("[TTS] Cannot speak due to missing API key or dependencies. TTS Disabled.")
            return
    
    # Reset interrupt event
    _tts_interrupt_event.clear()
    
    # Store current task
    _current_tts_task = asyncio.current_task()
    
    # Get interrupt handler and register callback
    interrupt_handler = get_interrupt_handler()
    interrupt_handler.register_tts_callback(interrupt_tts)
    
    try:
        # Set TTS context
        interrupt_handler.set_context(InterruptContext.TTS_PLAYING)
        
        async with _tts_playback_lock:
            log_debug("[TTS] Playback lock acquired.")
            try:
                log_debug("[TTS] Requesting speech stream from OpenAI...")
                
                # Check if interrupted before starting
                if _tts_interrupt_event.is_set():
                    log_debug("[TTS] Interrupted before starting playback")
                    return
                
                async with _async_openai_client_for_tts.audio.speech.with_streaming_response.create(
                    model="gpt-4o-mini-tts", voice=TTS_VOICE, input=text, response_format="pcm",
                ) as resp:
                    log_debug(f"[TTS] Received speech stream, status: {resp.status_code}.")
                    if not LocalAudioPlayer:
                        log_error("[TTS] LocalAudioPlayer not available.")
                        return
                    
                    log_debug("[TTS] Attempting to play audio...")
                    
                    # Create playback task that can be cancelled
                    playback_task = asyncio.create_task(LocalAudioPlayer().play(resp))
                    
                    # Wait for either playback to complete or interruption
                    interrupt_task = asyncio.create_task(_tts_interrupt_event.wait())
                    
                    done, pending = await asyncio.wait(
                        [playback_task, interrupt_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Cancel any pending tasks
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    
                    if interrupt_task in done:
                        log_debug("[TTS] Playback interrupted by user")
                        from prompt_toolkit import print_formatted_text
                        from prompt_toolkit.formatted_text import FormattedText
                        
                        try:
                            from .cli import cli_style
                        except ImportError:
                            cli_style = None
                            
                        print_formatted_text(FormattedText([
                            ('class:warning', "\n[TTS] Speech cancelled by user.")
                        ]), style=cli_style)
                    else:
                        log_debug("[TTS] Audio playback finished normally")
                        
            except asyncio.CancelledError:
                log_debug("[TTS] Task cancelled")
                raise
            except Exception as e:
                log_error(f"[TTS] API/playback error: {e}.", exception_info=str(e))
            finally:
                log_debug("[TTS] Playback lock released.")
    
    except asyncio.CancelledError:
        log_warning("[TTS] TTS task cancelled")
        # Re-raise to propagate cancellation
        raise
    except Exception as e_outer:
        log_error(f"[TTS] Outer error in tts_speak: {e_outer}.", exception_info=str(e_outer))
    finally:
        # Reset context back to idle
        interrupt_handler.set_context(InterruptContext.IDLE)
        _current_tts_task = None

async def summarize_for_voice(text: str, max_len: int = 220) -> str:
    """
    Summarize text for voice output.
    
    Args:
        text: The text to summarize
        max_len: Maximum length of the summary
        
    Returns:
        The summarized text
    """
    log_debug("[Summarizer] Starting summarization...")
    
    if not _async_openai_client_for_tts:
        if not _ensure_voice_dependencies() or not _init_openai_clients_for_tts():
            log_warning("[Summarizer] Cannot summarize due to missing API key or dependencies. Summarizer Disabled.")
            fallback_summary = text[:max_len].rsplit(' ',1)[0] + '...' if len(text) > max_len else text
            log_debug(f"[Summarizer] Using fallback summary: '{fallback_summary[:50]}...'")
            return fallback_summary

    try:
        system_msg = f"""You are a highly efficient text summarizer for voice output. Your task is to take the provided text and rephrase its core message into a single, concise, natural-sounding sentence for audible playback.
- If the input text uses first-person (e.g., "I will...", "Let me..."), the summary MUST also be in the first person (e.g., "I'll...", "I'm about to...").
- The summary must be factual and directly derived from the input.
- Do NOT add conversational filler, questions, opinions, or any text not present in the input's core message.
- Keep the summary under {max_len} characters.
Example Input: "I am going to use the file reading tool to examine the document specified by the user."
Example Output: "I'll read the specified document."
Example Input: "The next step involves calling the workflow execution service."
Example Output: "The next step is to call the workflow execution service.""" 

        log_debug("[Summarizer] Requesting summarization from OpenAI...")
        resp = await _async_openai_client_for_tts.chat.completions.create(
             model="gpt-4.1-nano", 
             messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": text.strip()}],
             max_tokens=max_len // 2, 
             temperature=0.1, 
        )
        summary = resp.choices[0].message.content.strip()
        if summary.startswith('"') and summary.endswith('"'):
            summary = summary[1:-1]
        if summary.startswith("'") and summary.endswith("'"):
            summary = summary[1:-1]
        final_summary = summary[:max_len].rsplit(' ', 1)[0] + '...' if len(summary) > max_len else summary
        log_debug(f"[Summarizer] Summarization successful: '{final_summary[:50]}...'")
        return final_summary
    except Exception as e:
        log_error(f"[Summarizer] TTS summarization error: {e}. Using fallback.", exception_info=str(e))
        fallback_summary = text[:max_len].rsplit(' ',1)[0] + '...' if len(text) > max_len else text
        log_debug(f"[Summarizer] Error, using fallback summary: '{fallback_summary[:50]}...'")
        return fallback_summary