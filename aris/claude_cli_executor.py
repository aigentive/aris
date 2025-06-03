import asyncio
import json
import os
import signal
from typing import List, Optional, AsyncIterator

# Assuming logging_utils is in the same directory or accessible via Python path
from .logging_utils import log_router_activity, log_error, log_warning


class ClaudeCLIExecutor:
    def __init__(self, claude_cli_path: str):
        """
        Initializes the ClaudeCLIExecutor.
        Args:
            claude_cli_path: The path to the Claude CLI executable.
        """
        self.claude_cli_path = claude_cli_path
        self.current_process: Optional[asyncio.subprocess.Process] = None
        log_router_activity(f"ClaudeCLIExecutor initialized. CLI path: {self.claude_cli_path}")
    
    def terminate_current_process(self):
        """
        Terminates the currently running Claude CLI process.
        
        This is called synchronously from the interrupt handler.
        """
        if self.current_process:
            if self.current_process.returncode is not None:
                # Process already finished, just clear the reference
                log_router_activity("ClaudeCLIExecutor: Process already finished, clearing reference")
                self.current_process = None
                return
                
            # Process is still running, terminate it
            log_router_activity("ClaudeCLIExecutor: Terminating current Claude CLI process due to interruption")
            try:
                # Try graceful termination first
                self.current_process.terminate()
                log_router_activity(f"ClaudeCLIExecutor: Sent SIGTERM to process {self.current_process.pid}")
                
                # Since we're in a sync context, we can't use await
                # Just send the signal and let the readline loop handle the termination
                # The readline loop will detect the process termination and break
                
            except ProcessLookupError:
                log_router_activity("ClaudeCLIExecutor: Process already terminated")
            except Exception as term_err:
                log_error(f"ClaudeCLIExecutor: Error terminating process: {term_err}")
                # Try force kill as fallback
                try:
                    self.current_process.kill()
                    log_router_activity(f"ClaudeCLIExecutor: Sent SIGKILL to process {self.current_process.pid}")
                except Exception as kill_err:
                    log_error(f"ClaudeCLIExecutor: Error force-killing process: {kill_err}")
            finally:
                # Clear the process reference
                self.current_process = None

    async def execute_cli(
        self,
        prompt_string: str,
        shared_flags: List[str],
        session_to_resume: Optional[str] = None
    ) -> AsyncIterator[str]:
        """
        Executes the Claude CLI as a subprocess and yields its stdout stream.

        Args:
            prompt_string: The fully formatted prompt string for the -p argument.
            shared_flags: A list of shared command-line flags (e.g., --allowedTools, --mcp-config).
            session_to_resume: Optional session ID to resume a Claude CLI session.

        Yields:
            str: Lines from the Claude CLI stdout, with a newline character appended.
        """
        log_router_activity(f"ClaudeCLIExecutor: Preparing to execute. Session to resume: {session_to_resume}")
        
        cmd: List[str]
        if session_to_resume:
            cmd = [self.claude_cli_path, "--resume", session_to_resume, "-p", prompt_string]
        else:
            cmd = [self.claude_cli_path, "-p", prompt_string]
        cmd.extend(shared_flags)

        # For logging purposes, create a display version of the command
        logging_cmd_str_parts = []
        for part_idx, part in enumerate(cmd):
            # Crude check for the prompt string based on the -p flag before it
            if part_idx > 0 and cmd[part_idx-1] == "-p": 
                part_for_log = part.replace('\n', '\\n').replace('\r', '\\r')
                # Truncate very long prompts for logging to avoid flooding
                if len(part_for_log) > 200:
                    part_for_log = part_for_log[:200] + "... (prompt truncated)"
                logging_cmd_str_parts.append(f"'{part_for_log}'")
            elif ' ' in part:
                logging_cmd_str_parts.append(f"'{part}'")
            else:
                logging_cmd_str_parts.append(part)
                
        log_router_activity(f"ClaudeCLIExecutor: Executing Claude CLI command list: {cmd}") # Log actual command list
        log_router_activity(f"ClaudeCLIExecutor: Equivalent shell command approx: {' '.join(logging_cmd_str_parts)}")

        if not cmd or cmd[0] != self.claude_cli_path:
            log_error("ClaudeCLIExecutor: Command for Claude CLI appears uninitialized or corrupted.")
            yield json.dumps({"type": "error", "error": {"message": "Internal CLI command error."}}) + "\n"; return

        log_router_activity(f"ClaudeCLIExecutor: Attempting to start subprocess: {' '.join(cmd[:5])}...") # Log start of cmd
        try:
            # Create subprocess with custom preexec function to ignore SIGINT
            # This ensures the parent process receives CTRL+C signals
            import sys
            import os
            import time
            
            setup_start_time = time.time()
            log_router_activity(f"ClaudeCLIExecutor: Starting subprocess setup at {setup_start_time:.3f}")
            
            kwargs = {
                'stdout': asyncio.subprocess.PIPE,
                'stderr': asyncio.subprocess.PIPE
            }
            
            kwargs_setup_time = time.time()
            log_router_activity(f"ClaudeCLIExecutor: Basic kwargs setup completed (t={kwargs_setup_time - setup_start_time:.3f}s)")
            
            # Create subprocess with platform-specific handling
            platform_start_time = time.time()
            log_router_activity(f"ClaudeCLIExecutor: Detected platform: {sys.platform}")
            
            if sys.platform.startswith('linux'):
                # Linux: use preexec_fn to ignore SIGINT in the child process
                log_router_activity("ClaudeCLIExecutor: Setting up Linux-specific subprocess handling")
                def preexec_fn():
                    # Ignore SIGINT in the child process
                    import signal
                    signal.signal(signal.SIGINT, signal.SIG_IGN)
                kwargs['preexec_fn'] = preexec_fn
            
            # Force fix macOS subprocess issue at creation time
            if sys.platform == 'darwin':
                macos_start_time = time.time()
                log_router_activity("ClaudeCLIExecutor: Starting macOS-specific subprocess handling")
                
                policy = asyncio.get_event_loop_policy()
                log_router_activity(f"ClaudeCLIExecutor: Policy type: {type(policy).__name__}")
                
                # If we don't have our custom policy, apply the fix now
                if 'MacOSAsyncioPolicy' not in str(type(policy)):
                    log_router_activity("ClaudeCLIExecutor: Applying macOS subprocess fix directly")
                    try:
                        from asyncio import ThreadedChildWatcher
                        
                        # Create ThreadedChildWatcher and attach to current loop
                        loop = asyncio.get_running_loop()
                        watcher = ThreadedChildWatcher()
                        watcher.attach_loop(loop)
                        
                        # Create a temporary policy wrapper
                        original_get_child_watcher = policy.get_child_watcher
                        policy.get_child_watcher = lambda: watcher
                        
                        macos_fix_time = time.time()
                        log_router_activity(f"ClaudeCLIExecutor: macOS subprocess fix applied (t={macos_fix_time - macos_start_time:.3f}s)")
                        
                    except Exception as e:
                        log_error(f"ClaudeCLIExecutor: Failed to apply macOS fix: {e}")
                        raise
                else:
                    log_router_activity("ClaudeCLIExecutor: Custom macOS policy is active")
                
                platform_setup_time = time.time()
                log_router_activity(f"ClaudeCLIExecutor: Platform-specific setup completed (t={platform_setup_time - platform_start_time:.3f}s)")
            
            # Create the subprocess - may take several seconds due to Claude CLI + MCP initialization
            log_router_activity("ClaudeCLIExecutor: Creating subprocess...")
            
            import time
            start_time = time.time()
            
            # Add granular timing for subprocess creation steps
            log_router_activity(f"ClaudeCLIExecutor: Starting asyncio.create_subprocess_exec at {start_time:.3f}")
            log_router_activity(f"ClaudeCLIExecutor: Command: {cmd[0]} with {len(cmd)-1} arguments")
            log_router_activity(f"ClaudeCLIExecutor: Kwargs: {list(kwargs.keys())}")
            
            # Check environment and working directory
            env_check_time = time.time()
            current_dir = os.getcwd()
            log_router_activity(f"ClaudeCLIExecutor: Current working directory: {current_dir}")
            
            # Check if claude command exists in PATH
            import shutil
            claude_which = shutil.which(cmd[0])
            log_router_activity(f"ClaudeCLIExecutor: Claude CLI path resolved to: {claude_which}")
            
            # Check key environment variables
            anthropic_key = "SET" if os.getenv("ANTHROPIC_API_KEY") else "NOT SET"
            log_router_activity(f"ClaudeCLIExecutor: ANTHROPIC_API_KEY: {anthropic_key}")
            
            env_check_complete_time = time.time()
            log_router_activity(f"ClaudeCLIExecutor: Environment checks completed (t={env_check_complete_time - env_check_time:.3f}s)")
            
            # Check asyncio event loop state
            loop_check_time = time.time()
            current_loop = asyncio.get_running_loop()
            log_router_activity(f"ClaudeCLIExecutor: Event loop type: {type(current_loop).__name__}")
            log_router_activity(f"ClaudeCLIExecutor: Event loop is running: {current_loop.is_running()}")
            log_router_activity(f"ClaudeCLIExecutor: Event loop closed: {current_loop.is_closed()}")
            
            # Track before subprocess creation
            pre_creation_time = time.time()
            log_router_activity(f"ClaudeCLIExecutor: About to call create_subprocess_exec (t={pre_creation_time - start_time:.3f}s)")
            
            # Log the exact moment we're calling create_subprocess_exec
            exact_call_time = time.time()
            log_router_activity(f"ClaudeCLIExecutor: 🚀 CALLING create_subprocess_exec NOW at {exact_call_time:.6f}")
            
            # Add comprehensive diagnostics before subprocess creation
            import resource
            import threading
            import psutil
            import gc
            
            try:
                # Thread and process diagnostics
                active_threads = threading.active_count()
                log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess active threads: {active_threads}")
                
                # Memory and resource usage
                memory_info = psutil.Process().memory_info()
                log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess memory: RSS={memory_info.rss//1024//1024}MB, VMS={memory_info.vms//1024//1024}MB")
                
                # File descriptor count (macOS)
                try:
                    import subprocess as sp
                    fd_count = len(sp.check_output(['lsof', '-p', str(os.getpid())]).decode().split('\n')) - 1
                    log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess file descriptors: {fd_count}")
                except:
                    log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess file descriptors: Unable to count")
                
                # Async task diagnostics
                current_task = asyncio.current_task()
                all_tasks = asyncio.all_tasks()
                log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess current task: {current_task}")
                log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess total async tasks: {len(all_tasks)}")
                
                # Log details of running tasks
                running_tasks = [task for task in all_tasks if not task.done()]
                log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess running tasks: {len(running_tasks)}")
                for i, task in enumerate(running_tasks[:5]):  # Log first 5 tasks
                    task_name = getattr(task, '_name', str(task))
                    log_router_activity(f"ClaudeCLIExecutor: Running task {i+1}: {task_name}")
                
                # Event loop diagnostics
                loop = asyncio.get_running_loop()
                log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess event loop: {type(loop).__name__}")
                log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess loop is running: {loop.is_running()}")
                
                # Garbage collection stats
                gc_stats = gc.get_stats()
                log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess GC stats: {len(gc_stats)} generations")
                
                # Process tree info
                parent = psutil.Process()
                children = parent.children(recursive=True)
                log_router_activity(f"ClaudeCLIExecutor: Pre-subprocess child processes: {len(children)}")
                
            except Exception as diag_error:
                log_router_activity(f"ClaudeCLIExecutor: Diagnostic error: {diag_error}")
            
            # Try with a timeout to see if we can get more info during the hang
            try:
                # Give it 30 seconds before logging that it's hanging
                proc = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(*cmd, **kwargs),
                    timeout=30.0
                )
                exact_return_time = time.time()
                log_router_activity(f"ClaudeCLIExecutor: ✅ create_subprocess_exec RETURNED at {exact_return_time:.6f}")
            except asyncio.TimeoutError:
                log_router_activity(f"ClaudeCLIExecutor: ⏰ create_subprocess_exec HANGING after 30s - continuing to wait...")
                
                # Add diagnostics during the hang
                try:
                    # Check what's changed during the hang
                    active_threads_now = threading.active_count()
                    all_tasks_now = asyncio.all_tasks()
                    running_tasks_now = [task for task in all_tasks_now if not task.done()]
                    
                    log_router_activity(f"ClaudeCLIExecutor: During hang - threads: {active_threads_now}, tasks: {len(all_tasks_now)}, running: {len(running_tasks_now)}")
                    
                    # Log any new tasks that appeared
                    for i, task in enumerate(running_tasks_now[:5]):
                        task_name = getattr(task, '_name', str(task))
                        log_router_activity(f"ClaudeCLIExecutor: Hanging task {i+1}: {task_name}")
                    
                    # Check if any tasks are blocking
                    import inspect
                    for task in running_tasks_now[:3]:
                        try:
                            frame = task.get_stack()[-1] if task.get_stack() else None
                            if frame:
                                log_router_activity(f"ClaudeCLIExecutor: Task stack: {frame.f_code.co_filename}:{frame.f_lineno}")
                        except:
                            pass
                            
                except Exception as hang_diag_error:
                    log_router_activity(f"ClaudeCLIExecutor: Hang diagnostic error: {hang_diag_error}")
                
                # Continue without timeout to see full hang time
                proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
                exact_return_time = time.time()
                log_router_activity(f"ClaudeCLIExecutor: ✅ create_subprocess_exec FINALLY RETURNED at {exact_return_time:.6f}")
                
                # Post-hang diagnostics
                try:
                    final_threads = threading.active_count()
                    final_tasks = len(asyncio.all_tasks())
                    log_router_activity(f"ClaudeCLIExecutor: Post-hang - threads: {final_threads}, tasks: {final_tasks}")
                except Exception as post_diag_error:
                    log_router_activity(f"ClaudeCLIExecutor: Post-hang diagnostic error: {post_diag_error}")
            
            # Immediately check if there's any stderr output available
            if proc.stderr:
                log_router_activity("ClaudeCLIExecutor: Checking for immediate stderr output...")
                try:
                    # Non-blocking check for stderr
                    import select
                    import sys
                    if sys.platform != 'win32':
                        ready, _, _ = select.select([proc.stderr], [], [], 0.1)  # 100ms timeout
                        if ready:
                            early_stderr = await asyncio.wait_for(proc.stderr.read(1024), timeout=0.5)
                            if early_stderr:
                                early_stderr_str = early_stderr.decode('utf-8', errors='ignore')
                                log_router_activity(f"ClaudeCLIExecutor: EARLY STDERR: {early_stderr_str}")
                except Exception as e:
                    log_router_activity(f"ClaudeCLIExecutor: Error checking early stderr: {e}")
            
            post_creation_time = time.time()
            creation_time = post_creation_time - start_time
            actual_creation_time = post_creation_time - pre_creation_time
            
            log_router_activity(f"ClaudeCLIExecutor: create_subprocess_exec returned (t={actual_creation_time:.3f}s)")
            log_router_activity(f"ClaudeCLIExecutor: Subprocess created in {creation_time:.3f}s total. PID: {proc.pid if proc else 'N/A'}")
            
            # More detailed timing analysis
            if actual_creation_time > 5.0:
                log_router_activity(f"ClaudeCLIExecutor: ⚠️  SLOW SUBPROCESS CREATION: {actual_creation_time:.3f}s in create_subprocess_exec")
            elif actual_creation_time > 2.0:
                log_router_activity(f"ClaudeCLIExecutor: Subprocess creation took {actual_creation_time:.3f}s")
            
            if creation_time > 3.0:
                log_router_activity(f"ClaudeCLIExecutor: Total subprocess setup took {creation_time:.3f}s (normal for Claude CLI with MCP servers)")
            elif creation_time > 1.0:
                log_router_activity(f"ClaudeCLIExecutor: Total subprocess setup took {creation_time:.3f}s")
            
            # Store the process reference for potential termination
            self.current_process = proc
            
            # Verify signal handler is still active after subprocess creation
            current_handler = signal.getsignal(signal.SIGINT)
            log_router_activity(f"ClaudeCLIExecutor: Signal handler after subprocess creation: {current_handler}")
            
            # On macOS, ensure the subprocess doesn't block our signals
            if sys.platform == 'darwin' and hasattr(signal, 'pthread_sigmask'):
                # Check if SIGINT is blocked
                blocked_signals = signal.pthread_sigmask(signal.SIG_BLOCK, [])
                if signal.SIGINT in blocked_signals:
                    log_warning("ClaudeCLIExecutor: SIGINT is blocked! Unblocking...")
                    signal.pthread_sigmask(signal.SIG_UNBLOCK, [signal.SIGINT])

            stdout_lines_yielded = False
            if proc.stdout:
                log_router_activity("ClaudeCLIExecutor: Processing stdout...")
                while True:
                    try:
                        # Use readline with increased timeout for large responses
                        # readline() will handle line boundaries properly
                        line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=2.0)
                    except asyncio.TimeoutError:
                        # Check if process is still running and current_process is still set
                        if self.current_process is None or proc.returncode is not None:
                            log_router_activity("ClaudeCLIExecutor: Process was terminated, breaking from stdout loop")
                            break
                        # Also check if we should handle a pending interrupt
                        try:
                            # Check if there's a pending KeyboardInterrupt
                            import select
                            if sys.platform != 'win32' and select.select([sys.stdin], [], [], 0)[0]:
                                # There's input waiting, might be an interrupt
                                pass
                        except:
                            pass
                        continue  # Continue reading if still running
                    except Exception as e_readline:
                        # Handle the "chunk longer than limit" error with chunked reading
                        log_error(f"ClaudeCLIExecutor: Exception during proc.stdout.readline(): {e_readline}")
                        if "chunk is longer than limit" in str(e_readline):
                            log_warning("ClaudeCLIExecutor: Large response detected, switching to chunked reading")
                            # Switch to chunked reading for large responses
                            try:
                                large_line = await self._read_large_response_chunked(proc.stdout)
                                if large_line:
                                    line_str = large_line.decode('utf-8', errors='ignore').strip()
                                    log_router_activity(f"ClaudeCLIExecutor: RAW Claude CLI stdout (chunked): {line_str[:200]}{'...' if len(line_str) > 200 else ''}")
                                    if line_str:
                                        stdout_lines_yielded = True
                                        yield line_str
                                continue  # Continue with regular reading after handling large response
                            except Exception as chunk_error:
                                log_error(f"ClaudeCLIExecutor: Failed to read large response with chunked method: {chunk_error}")
                                break
                        else:
                            # Other readline errors should still break the loop
                            break
                    if not line_bytes:
                        log_router_activity("ClaudeCLIExecutor: stdout.readline() returned no more bytes (EOF).")
                        break
                    line_str = line_bytes.decode('utf-8', errors='ignore').strip()
                    log_router_activity(f"ClaudeCLIExecutor: RAW Claude CLI stdout: {line_str}")
                    if line_str:
                        stdout_lines_yielded = True
                        yield line_str
            else:
                log_warning("ClaudeCLIExecutor: proc.stdout is None.")
            
            log_router_activity("ClaudeCLIExecutor: Finished processing stdout. Reading stderr...")
            stderr_output_bytes = await proc.stderr.read() if proc.stderr else b''
            stderr_output = stderr_output_bytes.decode('utf-8').strip()
            if stderr_output:
                log_error(f"ClaudeCLIExecutor: RAW Claude CLI stderr: {stderr_output}")
            else:
                log_router_activity("ClaudeCLIExecutor: No stderr output from Claude CLI.")

            log_router_activity("ClaudeCLIExecutor: Waiting for Claude CLI process to exit...")
            return_code = await proc.wait()
            log_router_activity(f"ClaudeCLIExecutor: Claude CLI process finished with exit code {return_code}")
            
            # Clear the process reference when done
            self.current_process = None

            if return_code != 0:
                error_detail = stderr_output if stderr_output else f"CLI process exited with code {return_code}."
                log_error(f"ClaudeCLIExecutor: Claude CLI exited with non-zero status: {return_code}. Stderr (if any): {stderr_output if stderr_output else 'N/A'}", 
                          exception_info=error_detail)
                yield json.dumps({"type": "error", "error": {"message": f"CLI process error (code {return_code})", "details": stderr_output}}) + "\n"
            elif not stdout_lines_yielded and not stderr_output:
                log_router_activity("ClaudeCLIExecutor: Claude CLI produced no output on stdout or stderr and exited cleanly.")
                yield json.dumps({"type": "status", "status": "no_output_clean_exit"}) + "\n"

        except FileNotFoundError:
            error_msg = f"ClaudeCLIExecutor: Claude CLI not found at '{self.claude_cli_path}'."
            log_error(error_msg, "FileNotFoundError")
            yield json.dumps({"type": "error", "error": {"message": error_msg}}) + "\n"
        except Exception as e:
            error_msg = f"ClaudeCLIExecutor: Unexpected error running Claude CLI: {repr(e)}"
            log_error(error_msg, exception_info=repr(e))
            import traceback
            log_error(f"ClaudeCLIExecutor: Full traceback: {traceback.format_exc()}")
            yield json.dumps({"type": "error", "error": {"message": error_msg}}) + "\n"
        finally:
            # Always clear the process reference when exiting
            self.current_process = None

    async def _read_large_response_chunked(self, stdout_stream) -> bytes:
        """
        Reads a large response that exceeded readline() buffer limits using chunked reading.
        
        Args:
            stdout_stream: The stdout stream to read from
            
        Returns:
            bytes: The complete line data
        """
        log_router_activity("ClaudeCLIExecutor: Starting chunked reading for large response")
        
        # Build the response by reading chunks until we find a complete line
        buffer = b""
        chunk_size = 8192  # 8KB chunks
        chunks_read = 0
        max_chunks = 1000  # Limit to ~8MB total to prevent runaway memory usage
        
        try:
            while chunks_read < max_chunks:
                # Read a chunk with timeout
                try:
                    chunk = await asyncio.wait_for(stdout_stream.read(chunk_size), timeout=5.0)
                except asyncio.TimeoutError:
                    log_warning(f"ClaudeCLIExecutor: Timeout reading chunk {chunks_read + 1}, buffer size: {len(buffer)}")
                    # If we have data in buffer and timeout, treat as end of line
                    if buffer and b'\n' in buffer:
                        break
                    continue
                
                if not chunk:
                    log_router_activity(f"ClaudeCLIExecutor: EOF reached during chunked reading, buffer size: {len(buffer)}")
                    break
                
                buffer += chunk
                chunks_read += 1
                
                # Log progress periodically
                if chunks_read % 10 == 0:
                    log_router_activity(f"ClaudeCLIExecutor: Chunked reading progress - chunks: {chunks_read}, buffer size: {len(buffer)}")
                
                # Check if we have a complete line (ending with newline)
                if b'\n' in buffer:
                    # Split on first newline to get the complete line
                    line_end = buffer.find(b'\n')
                    complete_line = buffer[:line_end]
                    remaining_data = buffer[line_end + 1:]
                    
                    # If there's remaining data, we need to put it back somehow
                    # For now, log that we found the line boundary
                    if remaining_data:
                        log_warning(f"ClaudeCLIExecutor: Found {len(remaining_data)} bytes after newline - may contain next message")
                    
                    log_router_activity(f"ClaudeCLIExecutor: Successfully read large response via chunking - {len(complete_line)} bytes in {chunks_read} chunks")
                    return complete_line
            
            # If we reached max chunks or other exit condition
            if chunks_read >= max_chunks:
                log_error(f"ClaudeCLIExecutor: Reached maximum chunk limit ({max_chunks}), buffer size: {len(buffer)}")
                # Return what we have, even if incomplete
                return buffer
            
            # Return the buffer even without newline if we got EOF
            log_router_activity(f"ClaudeCLIExecutor: Returning buffer without newline terminator - {len(buffer)} bytes")
            return buffer
            
        except Exception as e:
            log_error(f"ClaudeCLIExecutor: Error during chunked reading: {e}")
            # Return partial data if we have any
            if buffer:
                log_router_activity(f"ClaudeCLIExecutor: Returning partial buffer due to error - {len(buffer)} bytes")
                return buffer
            return b""


# Example Usage (for testing cli_agent.py directly)
async def main_test_cli_executor():
    print("Testing ClaudeCLIExecutor...")
    # This test requires claude CLI to be installed and configured.
    # It also assumes a basic prompt and some dummy flags.
    
    # Path to your claude executable (adjust if necessary)
    claude_path = os.getenv("CLAUDE_CLI_PATH", "claude") 
    executor = ClaudeCLIExecutor(claude_cli_path=claude_path)

    # Dummy prompt and flags for testing
    # A real prompt would be much larger and come from PromptEngineeringAgent
    # Real flags would come from ToolManagementAgent
    test_prompt = "<assistant_instructions>\nHello!\n</assistant_instructions>\n<current_user_message_for_this_turn>\nHi there!\n</current_user_message_for_this_turn>"
    test_flags = ["--output-format", "stream-json", "--verbose", "--max-turns", "1"]

    print(f"\nExecuting with CLI path: {claude_path}")
    print(f"Prompt (partial): {test_prompt[:100]}...")
    print(f"Flags: {test_flags}")

    if not os.path.exists(claude_path):
        print(f"WARNING: Claude CLI not found at {claude_path}. Test will likely fail with FileNotFoundError.")

    print("\n--- CLI Output Stream ---")
    try:
        async for chunk in executor.execute_cli(prompt_string=test_prompt, shared_flags=test_flags):
            print(f"Chunk from CLI: {chunk.strip()}")
    except Exception as e:
        print(f"Error during test execution: {e}")
    print("--- End of CLI Output Stream ---")
