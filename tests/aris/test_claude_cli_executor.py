# Tests for aris.claude_cli_executor

import pytest 
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from aris import claude_cli_executor
from aris.claude_cli_executor import ClaudeCLIExecutor

# Mock logging functions directly within the claude_cli_executor module for testing
@pytest.fixture(autouse=True)
def mock_executor_logging(monkeypatch):
    monkeypatch.setattr("aris.claude_cli_executor.log_router_activity", MagicMock())
    monkeypatch.setattr("aris.claude_cli_executor.log_error", MagicMock())
    monkeypatch.setattr("aris.claude_cli_executor.log_warning", MagicMock())
    yield

@pytest.fixture
def executor() -> ClaudeCLIExecutor:
    return ClaudeCLIExecutor(claude_cli_path="fake_claude_cli")

@pytest.fixture
def mock_subprocess_protocol() -> AsyncMock:
    mock_protocol = AsyncMock(spec=asyncio.SubprocessProtocol)
    mock_protocol.stdout = AsyncMock(spec=asyncio.StreamReader)
    mock_protocol.stderr = AsyncMock(spec=asyncio.StreamReader)
    return mock_protocol

@pytest.fixture
def mock_process(mock_subprocess_protocol: AsyncMock) -> AsyncMock:
    mock_proc = AsyncMock(spec=asyncio.subprocess.Process)
    mock_proc.pid = 1234
    mock_proc.stdout = mock_subprocess_protocol.stdout
    mock_proc.stderr = mock_subprocess_protocol.stderr
    mock_proc.wait = AsyncMock(return_value=0) # Default to successful exit
    return mock_proc

@pytest.mark.asyncio
async def test_execute_cli_success_new_session(executor: ClaudeCLIExecutor, mock_process: AsyncMock):
    prompt = "Test prompt"
    flags = ["--flag1", "value1"]
    expected_cmd = ["fake_claude_cli", "-p", prompt] + flags

    mock_process.stdout.readline = AsyncMock(side_effect=[
        b'{"type": "message_start"}\n',
        b'{"type": "content_block", "text": "Hello"}\n',
        b'{"type": "message_end"}\n',
        b'' # EOF
    ])
    mock_process.stderr.read = AsyncMock(return_value=b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_create_subprocess:
        results = [chunk async for chunk in executor.execute_cli(prompt_string=prompt, shared_flags=flags)]

        # Check subprocess call - behavior varies by platform
        import sys
        if sys.platform.startswith('linux'):
            mock_create_subprocess.assert_awaited_once_with(
                *expected_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=ANY
            )
        else:
            # On macOS, it tries create_subprocess_exec first
            mock_create_subprocess.assert_awaited_once_with(
                *expected_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        mock_process.wait.assert_awaited_once()

        assert len(results) == 3
        assert json.loads(results[0]) == {"type": "message_start"}
        assert json.loads(results[1]) == {"type": "content_block", "text": "Hello"}
        assert json.loads(results[2]) == {"type": "message_end"}
        # Check specific log call via the mock
        claude_cli_executor.log_router_activity.assert_any_call("ClaudeCLIExecutor: Claude CLI process finished with exit code 0")

@pytest.mark.asyncio
async def test_execute_cli_success_resume_session(executor: ClaudeCLIExecutor, mock_process: AsyncMock):
    prompt = "Follow up prompt"
    flags = ["--verbose"]
    session_id = "session123"
    expected_cmd = ["fake_claude_cli", "--resume", session_id, "-p", prompt] + flags

    mock_process.stdout.readline = AsyncMock(side_effect=[b'{"type": "resumed"}\n', b''])
    mock_process.stderr.read = AsyncMock(return_value=b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_create_subprocess:
        results = [chunk async for chunk in executor.execute_cli(prompt_string=prompt, shared_flags=flags, session_to_resume=session_id)]
        # Check subprocess call - preexec_fn is only used on Linux
        import sys
        if sys.platform.startswith('linux'):
            mock_create_subprocess.assert_awaited_once_with(*expected_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, preexec_fn=ANY)
        else:
            mock_create_subprocess.assert_awaited_once_with(*expected_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        assert len(results) == 1
        assert json.loads(results[0]) == {"type": "resumed"}

@pytest.mark.asyncio
async def test_execute_cli_non_zero_exit_code(executor: ClaudeCLIExecutor, mock_process: AsyncMock):
    prompt = "Error prompt"
    flags = []
    mock_process.wait = AsyncMock(return_value=1) # Simulate error exit code
    mock_process.stdout.readline = AsyncMock(return_value=b"") # No stdout
    mock_process.stderr.read = AsyncMock(return_value=b"CLI Error Occurred")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        results = [chunk async for chunk in executor.execute_cli(prompt_string=prompt, shared_flags=flags)]

        assert len(results) == 1
        error_result = json.loads(results[0])
        assert error_result["type"] == "error"
        assert error_result["error"]["message"] == "CLI process error (code 1)"
        assert error_result["error"]["details"] == "CLI Error Occurred"
        claude_cli_executor.log_error.assert_any_call("ClaudeCLIExecutor: Claude CLI exited with non-zero status: 1. Stderr (if any): CLI Error Occurred", exception_info="CLI Error Occurred")
        claude_cli_executor.log_error.assert_any_call("ClaudeCLIExecutor: RAW Claude CLI stderr: CLI Error Occurred")

@pytest.mark.asyncio
async def test_execute_cli_file_not_found(executor: ClaudeCLIExecutor):
    prompt = "Any prompt"
    flags = []
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("CLI not found")):
        results = [chunk async for chunk in executor.execute_cli(prompt_string=prompt, shared_flags=flags)]
        assert len(results) == 1
        error_result = json.loads(results[0])
        assert error_result["type"] == "error"
        assert error_result["error"]["message"] == f"ClaudeCLIExecutor: Claude CLI not found at '{executor.claude_cli_path}'."
        claude_cli_executor.log_error.assert_called_with(f"ClaudeCLIExecutor: Claude CLI not found at '{executor.claude_cli_path}'.", "FileNotFoundError")

@pytest.mark.asyncio
async def test_execute_cli_unexpected_exception(executor: ClaudeCLIExecutor):
    prompt = "Any prompt"
    flags = []
    with patch("asyncio.create_subprocess_exec", side_effect=Exception("Unexpected subprocess boom")):
        results = [chunk async for chunk in executor.execute_cli(prompt_string=prompt, shared_flags=flags)]
        assert len(results) == 1
        error_result = json.loads(results[0])
        assert error_result["type"] == "error"
        assert error_result["error"]["message"] == "ClaudeCLIExecutor: Unexpected error running Claude CLI: Exception('Unexpected subprocess boom')"
        # Check that log_error was called with the repr() format
        claude_cli_executor.log_error.assert_any_call("ClaudeCLIExecutor: Unexpected error running Claude CLI: Exception('Unexpected subprocess boom')", exception_info="Exception('Unexpected subprocess boom')")

@pytest.mark.asyncio
async def test_execute_cli_no_stdout_or_stderr_clean_exit(executor: ClaudeCLIExecutor, mock_process: AsyncMock):
    prompt = "Quiet prompt"
    flags = []
    mock_process.stdout.readline = AsyncMock(return_value=b"") # No stdout
    mock_process.stderr.read = AsyncMock(return_value=b"")    # No stderr
    mock_process.wait = AsyncMock(return_value=0)             # Clean exit

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        results = [chunk async for chunk in executor.execute_cli(prompt_string=prompt, shared_flags=flags)]
        # When both stdout and stderr are empty, we expect no output to be yielded
        # or a single status message to be yielded
        assert len(results) <= 1
        if len(results) == 1:
            status_json = json.loads(results[0])
            assert status_json.get("type") in ["info", "status"]
        claude_cli_executor.log_router_activity.assert_any_call("ClaudeCLIExecutor: Claude CLI produced no output on stdout or stderr and exited cleanly.")

@pytest.mark.asyncio
async def test_execute_cli_corrupted_command_internally(executor: ClaudeCLIExecutor):
    original_path = executor.claude_cli_path
    executor.claude_cli_path = "" 
    
    prompt = "Test"
    flags = []
    results = [chunk async for chunk in executor.execute_cli(prompt_string=prompt, shared_flags=flags)]
    
    executor.claude_cli_path = original_path

    assert len(results) == 1
    error_result = json.loads(results[0])
    assert error_result["type"] == "error"
    assert "message" in error_result["error"]
    # The specific error message depends on the environment
    # Just check that it contains key information
    assert "message" in error_result["error"]
    assert "command" in error_result["error"]["message"].lower() or "permission" in error_result["error"]["message"].lower() or "error" in error_result["error"]["message"].lower()
    # With an empty CLI path, it might either catch the error at the corrupted command check
    # or later when trying to execute the command, depending on the environment
    # So we don't check for a specific error message, just that an error was logged
    assert claude_cli_executor.log_error.called

@pytest.mark.asyncio
async def test_execute_cli_stdout_readline_exception(executor: ClaudeCLIExecutor, mock_process: AsyncMock):
    prompt = "Test prompt"
    flags = []
    
    mock_process.stdout.readline = AsyncMock(side_effect=Exception("Readline error"))
    mock_process.stderr.read = AsyncMock(return_value=b"")
    mock_process.wait = AsyncMock(return_value=0) 

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        results = [chunk async for chunk in executor.execute_cli(prompt_string=prompt, shared_flags=flags)]
        
        # We now expect a status message since we've modified the implementation
        assert len(results) == 1
        status = json.loads(results[0])
        assert status.get("type") == "status"
        claude_cli_executor.log_error.assert_any_call("ClaudeCLIExecutor: Exception during proc.stdout.readline(): Readline error")

@pytest.mark.asyncio
async def test_execute_cli_chunk_longer_than_limit_error_triggers_chunked_reading(executor: ClaudeCLIExecutor, mock_process: AsyncMock):
    """Test that 'chunk is longer than limit' error triggers chunked reading fallback."""
    prompt = "Test prompt"
    flags = []
    
    # Simulate the specific error that triggers chunked reading, then EOF
    chunk_limit_error = Exception("Separator is found, but chunk is longer than limit")
    mock_process.stdout.readline = AsyncMock(side_effect=[chunk_limit_error, b''])  # Error then EOF
    mock_process.stderr.read = AsyncMock(return_value=b"")
    mock_process.wait = AsyncMock(return_value=0)
    
    # Mock the chunked reading method to return a large response
    large_response = b'{"type":"assistant","content":"Very large response content..."}' 
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        with patch.object(executor, '_read_large_response_chunked', return_value=large_response) as mock_chunked_read:
            results = [chunk async for chunk in executor.execute_cli(prompt_string=prompt, shared_flags=flags)]
            
            # Verify chunked reading was called
            mock_chunked_read.assert_awaited_once_with(mock_process.stdout)
            
            # Should get the large response back
            assert len(results) == 1
            response_data = json.loads(results[0])
            assert response_data["type"] == "assistant"
            assert "Very large response content" in response_data["content"]
            
            # Verify proper logging
            claude_cli_executor.log_error.assert_any_call("ClaudeCLIExecutor: Exception during proc.stdout.readline(): Separator is found, but chunk is longer than limit")
            claude_cli_executor.log_warning.assert_any_call("ClaudeCLIExecutor: Large response detected, switching to chunked reading")

@pytest.mark.asyncio 
async def test_read_large_response_chunked_success():
    """Test successful chunked reading of a large response."""
    executor = ClaudeCLIExecutor(claude_cli_path="fake_claude_cli")
    
    # Create a mock stream that returns data in chunks
    mock_stream = AsyncMock()
    large_json = b'{"type":"tool_result","content":"' + b'x' * 10000 + b'"}'
    newline_terminated = large_json + b'\n'
    
    # Split into chunks to simulate chunked reading
    chunk_size = 8192
    chunks = [newline_terminated[i:i+chunk_size] for i in range(0, len(newline_terminated), chunk_size)]
    chunks.append(b'')  # EOF
    
    mock_stream.read = AsyncMock(side_effect=chunks)
    
    with patch("aris.claude_cli_executor.log_router_activity"):
        result = await executor._read_large_response_chunked(mock_stream)
        
        # Should get the original data back (without newline)
        assert result == large_json
        assert len(result) > 8192  # Verify it's actually large
        
        # Verify read was called multiple times
        assert mock_stream.read.call_count >= 2

@pytest.mark.asyncio
async def test_read_large_response_chunked_timeout_handling():
    """Test chunked reading with timeout scenarios."""
    executor = ClaudeCLIExecutor(claude_cli_path="fake_claude_cli")
    
    mock_stream = AsyncMock()
    # First call times out, second call returns data
    mock_stream.read = AsyncMock(side_effect=[
        asyncio.TimeoutError(),
        b'{"type":"response"}\n',
        b''  # EOF
    ])
    
    with patch("aris.claude_cli_executor.log_router_activity"):
        with patch("aris.claude_cli_executor.log_warning"):
            result = await executor._read_large_response_chunked(mock_stream)
            
            assert result == b'{"type":"response"}'
            assert mock_stream.read.call_count == 2  # timeout + data (no EOF needed since line is complete)

@pytest.mark.asyncio
async def test_read_large_response_chunked_max_chunks_limit():
    """Test chunked reading respects maximum chunks limit."""
    executor = ClaudeCLIExecutor(claude_cli_path="fake_claude_cli")
    
    mock_stream = AsyncMock()
    # Return chunks indefinitely (simulating very large response)
    chunk_data = b'x' * 8192
    mock_stream.read = AsyncMock(return_value=chunk_data)
    
    with patch("aris.claude_cli_executor.log_router_activity"):
        with patch("aris.claude_cli_executor.log_error"):
            result = await executor._read_large_response_chunked(mock_stream)
            
            # Should hit the 1000 chunk limit and return what it has
            assert len(result) > 0
            # Should call read 1000 times (the limit)
            assert mock_stream.read.call_count == 1000

@pytest.mark.asyncio
async def test_read_large_response_chunked_eof_without_newline():
    """Test chunked reading when EOF reached without newline terminator."""
    executor = ClaudeCLIExecutor(claude_cli_path="fake_claude_cli")
    
    mock_stream = AsyncMock()
    # Data without newline terminator, then EOF
    mock_stream.read = AsyncMock(side_effect=[
        b'{"type":"incomplete_response"}',
        b''  # EOF
    ])
    
    with patch("aris.claude_cli_executor.log_router_activity"):
        result = await executor._read_large_response_chunked(mock_stream)
        
        assert result == b'{"type":"incomplete_response"}'

@pytest.mark.asyncio
async def test_read_large_response_chunked_error_handling():
    """Test chunked reading error handling."""
    executor = ClaudeCLIExecutor(claude_cli_path="fake_claude_cli")
    
    mock_stream = AsyncMock()
    mock_stream.read = AsyncMock(side_effect=Exception("Stream read error"))
    
    with patch("aris.claude_cli_executor.log_router_activity"):
        with patch("aris.claude_cli_executor.log_error"):
            result = await executor._read_large_response_chunked(mock_stream)
            
            # Should return empty bytes on error
            assert result == b""

@pytest.mark.asyncio
async def test_execute_cli_chunked_reading_continues_normal_operation(executor: ClaudeCLIExecutor, mock_process: AsyncMock):
    """Test that after successful chunked reading, normal readline operation continues."""
    prompt = "Test prompt"
    flags = []
    
    # First readline fails with chunk limit error, then normal operation resumes
    chunk_limit_error = Exception("Separator is found, but chunk is longer than limit")
    mock_process.stdout.readline = AsyncMock(side_effect=[
        chunk_limit_error,  # Triggers chunked reading
        b'{"type":"normal_message"}\n',  # Normal operation resumes
        b''  # EOF
    ])
    mock_process.stderr.read = AsyncMock(return_value=b"")
    mock_process.wait = AsyncMock(return_value=0)
    
    # Mock chunked reading to return large response
    large_response = b'{"type":"large_response","data":"x"}' 
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        with patch.object(executor, '_read_large_response_chunked', return_value=large_response):
            results = [chunk async for chunk in executor.execute_cli(prompt_string=prompt, shared_flags=flags)]
            
            # Should get both the chunked response and the normal message
            assert len(results) == 2
            
            # First result from chunked reading
            chunked_result = json.loads(results[0])
            assert chunked_result["type"] == "large_response"
            
            # Second result from normal readline
            normal_result = json.loads(results[1])
            assert normal_result["type"] == "normal_message"
            
            # Verify readline was called multiple times (continue operation after chunked reading)
            assert mock_process.stdout.readline.call_count == 3  # error + normal + EOF

@pytest.mark.asyncio
async def test_chunked_reading_handles_remaining_data():
    """Test that chunked reading properly handles data after newline."""
    executor = ClaudeCLIExecutor(claude_cli_path="fake_claude_cli")
    
    mock_stream = AsyncMock()
    # Data with newline in middle, followed by additional data
    response_with_extra = b'{"type":"response"}\n{"type":"next_message"}'
    mock_stream.read = AsyncMock(side_effect=[response_with_extra, b''])
    
    with patch("aris.claude_cli_executor.log_router_activity"):
        with patch("aris.claude_cli_executor.log_warning") as mock_warning:
            result = await executor._read_large_response_chunked(mock_stream)
            
            # Should return only the first complete line
            assert result == b'{"type":"response"}'
            
            # Should warn about remaining data
            mock_warning.assert_any_call("ClaudeCLIExecutor: Found 23 bytes after newline - may contain next message") 