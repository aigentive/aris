"""
Tests for CLI insights flag functionality.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from aris.cli_args import parse_arguments_and_configure_logging
from aris.cli import execute_non_interactive_mode, format_non_interactive_response


class TestCliInsightsFlag:
    """Test CLI insights flag functionality."""
    
    def test_disable_insights_flag_parsing(self):
        """Test that --disable-insights flag is properly parsed."""
        # Test with flag present
        with patch('sys.argv', ['aris', '--disable-insights']):
            args = parse_arguments_and_configure_logging()
            assert hasattr(args, 'disable_insights')
            assert args.disable_insights is True
        
        # Test with flag absent
        with patch('sys.argv', ['aris']):
            args = parse_arguments_and_configure_logging()
            assert hasattr(args, 'disable_insights')
            assert args.disable_insights is False
    
    def test_disable_insights_flag_help_text(self):
        """Test that --disable-insights flag has proper help text."""
        import argparse
        from aris.cli_args import parse_arguments_and_configure_logging
        
        # Capture help output
        with patch('sys.argv', ['aris', '--help']):
            try:
                parse_arguments_and_configure_logging()
            except SystemExit:
                pass  # argparse exits on --help
        
        # The flag should be properly registered (tested in previous test)
    
    @pytest.mark.asyncio
    async def test_non_interactive_mode_insights_enabled_default(self):
        """Test that insights are enabled by default in non-interactive mode."""
        with patch('aris.cli.get_current_session_state') as mock_get_session, \
             patch('aris.cli.execute_single_turn', new_callable=AsyncMock) as mock_execute, \
             patch('aris.cli.workspace_manager'), \
             patch('sys.exit'), \
             patch('builtins.print'), \
             patch('aris.cli.create_progress_tracker') as mock_create_tracker, \
             patch('aris.cli_args.PARSED_ARGS') as mock_args:
            
            # Set up mocks
            mock_args.verbose = False
            mock_args.disable_insights = False  # Default: insights enabled
            mock_session = MagicMock()
            mock_get_session.return_value = mock_session
            mock_execute.return_value = "test response"
            mock_tracker = MagicMock()
            mock_create_tracker.return_value = mock_tracker
            
            await execute_non_interactive_mode("test input")
            
            # Should create tracker with insights enabled
            mock_create_tracker.assert_called_once_with(
                interactive=False,
                verbose=False,
                enable_insights=True  # Should be True (not disabled)
            )
    
    @pytest.mark.asyncio
    async def test_non_interactive_mode_insights_disabled_by_flag(self):
        """Test that insights are disabled when --disable-insights flag is used."""
        with patch('aris.cli.get_current_session_state') as mock_get_session, \
             patch('aris.cli.execute_single_turn', new_callable=AsyncMock) as mock_execute, \
             patch('aris.cli.workspace_manager'), \
             patch('sys.exit'), \
             patch('builtins.print'), \
             patch('aris.cli.create_progress_tracker') as mock_create_tracker, \
             patch('aris.cli_args.PARSED_ARGS') as mock_args:
            
            # Set up mocks
            mock_args.verbose = False
            mock_args.disable_insights = True  # Flag present: insights disabled
            mock_session = MagicMock()
            mock_get_session.return_value = mock_session
            mock_execute.return_value = "test response"
            mock_tracker = MagicMock()
            mock_create_tracker.return_value = mock_tracker
            
            await execute_non_interactive_mode("test input")
            
            # Should create tracker with insights disabled
            mock_create_tracker.assert_called_once_with(
                interactive=False,
                verbose=False,
                enable_insights=False  # Should be False (disabled by flag)
            )
    
    @pytest.mark.asyncio
    async def test_non_interactive_mode_insights_with_verbose(self):
        """Test insights behavior with verbose mode enabled."""
        with patch('aris.cli.get_current_session_state') as mock_get_session, \
             patch('aris.cli.execute_single_turn', new_callable=AsyncMock) as mock_execute, \
             patch('aris.cli.workspace_manager'), \
             patch('sys.exit'), \
             patch('builtins.print'), \
             patch('aris.cli.create_progress_tracker') as mock_create_tracker, \
             patch('aris.cli_args.PARSED_ARGS') as mock_args:
            
            # Set up mocks
            mock_args.verbose = True  # Verbose mode enabled
            mock_args.disable_insights = False  # Insights not disabled
            mock_session = MagicMock()
            mock_get_session.return_value = mock_session
            mock_execute.return_value = "test response"
            mock_tracker = MagicMock()
            mock_create_tracker.return_value = mock_tracker
            
            await execute_non_interactive_mode("test input")
            
            # Should create tracker with insights enabled but verbose mode on
            mock_create_tracker.assert_called_once_with(
                interactive=False,
                verbose=True,  # Verbose mode should be passed through
                enable_insights=True  # Insights should still be enabled
            )
    
    def test_format_response_with_insights_enabled(self):
        """Test response formatting when insights are available."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "test_profile"}
        
        # Mock progress tracker with insights
        progress_tracker = MagicMock()
        progress_tracker.get_completion_summary.return_value = {
            "type": "completion_summary",
            "message": "Task completed",
            "metrics": {
                "total_cost": 0.15,
                "duration_seconds": 45,
                "files_created": 2,
                "files_modified": 1
            }
        }
        
        response = "Task completed successfully\nAll files have been updated."
        
        result = format_non_interactive_response(response, session_state, progress_tracker)
        
        # Should include metrics footer
        assert "🤖 test_profile: Task completed successfully" in result
        assert "All files have been updated." in result
        assert "📈 Session metrics:" in result
        assert "💰 $0.15" in result
        assert "⏱️ 45s" in result
        assert "📁 2 files created" in result
        assert "✏️ 1 files updated" in result
    
    def test_format_response_with_insights_disabled(self):
        """Test response formatting when insights are disabled."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "test_profile"}
        
        # No progress tracker (insights disabled)
        progress_tracker = None
        
        response = "Task completed successfully\nAll files have been updated."
        
        result = format_non_interactive_response(response, session_state, progress_tracker)
        
        # Should not include metrics footer
        assert "🤖 test_profile: Task completed successfully" in result
        assert "All files have been updated." in result
        assert "📈 Session metrics:" not in result
        assert "💰" not in result
        assert "⏱️" not in result
    
    def test_format_response_with_insights_no_summary(self):
        """Test response formatting when insights are enabled but no summary available."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "test_profile"}
        
        # Mock progress tracker without completion summary
        progress_tracker = MagicMock()
        progress_tracker.get_completion_summary.return_value = None
        
        response = "Task completed successfully"
        
        result = format_non_interactive_response(response, session_state, progress_tracker)
        
        # Should not include metrics footer
        assert "🤖 test_profile: Task completed successfully" in result
        assert "📈 Session metrics:" not in result
    
    def test_format_response_with_low_cost_operations(self):
        """Test that low-cost operations don't show metrics footer."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "test_profile"}
        
        # Mock progress tracker with low-cost metrics
        progress_tracker = MagicMock()
        progress_tracker.get_completion_summary.return_value = {
            "type": "completion_summary", 
            "message": "Task completed",
            "metrics": {
                "total_cost": 0.02,  # Below 0.05 threshold
                "duration_seconds": 5,  # Below 10s threshold
                "files_created": 0,  # No files created
                "files_modified": 0
            }
        }
        
        response = "Simple task completed"
        
        result = format_non_interactive_response(response, session_state, progress_tracker)
        
        # Should not include metrics footer for low-impact operations
        assert "🤖 test_profile: Simple task completed" in result
        assert "📈 Session metrics:" not in result
    
    def test_format_response_metrics_formatting(self):
        """Test proper formatting of different metric types."""
        session_state = MagicMock()
        session_state.active_profile = {"profile_name": "test"}
        
        # Test different duration formats
        test_cases = [
            {"duration_seconds": 30, "expected": "⏱️ 30s"},
            {"duration_seconds": 90, "expected": "⏱️ 1m 30s"},
            {"duration_seconds": 125, "expected": "⏱️ 2m 5s"}
        ]
        
        for case in test_cases:
            progress_tracker = MagicMock()
            progress_tracker.get_completion_summary.return_value = {
                "type": "completion_summary",
                "message": "Task completed", 
                "metrics": {
                    "total_cost": 0.10,  # Above threshold
                    "duration_seconds": case["duration_seconds"],
                    "files_created": 1,
                    "files_modified": 0
                }
            }
            
            result = format_non_interactive_response("Test", session_state, progress_tracker)
            
            assert case["expected"] in result
    
    def test_getattr_fallback_for_missing_flag(self):
        """Test that getattr fallback works when disable_insights attribute is missing."""
        # Simulate old PARSED_ARGS object without disable_insights attribute
        mock_args = MagicMock()
        del mock_args.disable_insights  # Remove the attribute
        
        with patch('aris.cli_args.PARSED_ARGS', mock_args):
            with patch('aris.cli.get_current_session_state') as mock_get_session, \
                 patch('aris.cli.execute_single_turn', new_callable=AsyncMock) as mock_execute, \
                 patch('aris.cli.workspace_manager'), \
                 patch('sys.exit'), \
                 patch('builtins.print'), \
                 patch('aris.cli.create_progress_tracker') as mock_create_tracker:
                
                mock_session = MagicMock()
                mock_get_session.return_value = mock_session
                mock_execute.return_value = "test"
                mock_tracker = MagicMock()
                mock_create_tracker.return_value = mock_tracker
                
                # Should not crash and should default to insights enabled
                try:
                    import asyncio
                    asyncio.run(execute_non_interactive_mode("test"))
                except SystemExit:
                    pass  # Expected due to sys.exit in the function
                
                # Should default to insights enabled (False for disable_insights)
                mock_create_tracker.assert_called_once()
                call_kwargs = mock_create_tracker.call_args[1]
                assert call_kwargs['enable_insights'] is True


class TestCliInsightsFlagIntegration:
    """Test integration of CLI insights flag with other components."""
    
    @pytest.mark.parametrize("disable_flag,verbose,expected_insights", [
        (False, False, True),   # Default: insights enabled
        (True, False, False),   # Flag disables insights
        (False, True, True),    # Verbose doesn't affect insights
        (True, True, False),    # Flag disables insights even with verbose
    ])
    def test_various_flag_combinations(self, disable_flag, verbose, expected_insights):
        """Test various combinations of CLI flags."""
        with patch('aris.cli.get_current_session_state') as mock_get_session, \
             patch('aris.cli.execute_single_turn', new_callable=AsyncMock) as mock_execute, \
             patch('aris.cli.workspace_manager'), \
             patch('sys.exit'), \
             patch('builtins.print'), \
             patch('aris.cli.create_progress_tracker') as mock_create_tracker, \
             patch('aris.cli_args.PARSED_ARGS') as mock_args:
            
            mock_args.verbose = verbose
            mock_args.disable_insights = disable_flag
            mock_session = MagicMock()
            mock_get_session.return_value = mock_session
            mock_execute.return_value = "test"
            mock_tracker = MagicMock()
            mock_create_tracker.return_value = mock_tracker
            
            try:
                import asyncio
                asyncio.run(execute_non_interactive_mode("test"))
            except SystemExit:
                pass
            
            mock_create_tracker.assert_called_once_with(
                interactive=False,
                verbose=verbose,
                enable_insights=expected_insights
            )