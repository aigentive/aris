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
            
            kwargs = {
                'stdout': asyncio.subprocess.PIPE,
                'stderr': asyncio.subprocess.PIPE
            }
            
            # Create subprocess with platform-specific handling
            if sys.platform.startswith('linux'):
                # Linux: use preexec_fn to ignore SIGINT in the child process
                def preexec_fn():
                    # Ignore SIGINT in the child process
                    import signal
                    signal.signal(signal.SIGINT, signal.SIG_IGN)
                kwargs['preexec_fn'] = preexec_fn
            
            # Create the subprocess
            proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
            log_router_activity(f"ClaudeCLIExecutor: Subprocess started. PID: {proc.pid if proc else 'N/A'}")
            
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
                        # Add timeout to readline to allow for interruption
                        line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=0.5)
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
                        log_error(f"ClaudeCLIExecutor: Exception during proc.stdout.readline(): {e_readline}")
                        break
                    if not line_bytes:
                        log_router_activity("ClaudeCLIExecutor: stdout.readline() returned no more bytes (EOF).")
                        break
                    line_str = line_bytes.decode('utf-8').strip()
                    log_router_activity(f"ClaudeCLIExecutor: RAW Claude CLI stdout: {line_str}")
                    if line_str:
                        stdout_lines_yielded = True
                        yield line_str + "\n"
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
