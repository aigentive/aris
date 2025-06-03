"""
Production-grade workspace directory monitor for file changes during session.
Provides cross-platform file system monitoring with performance optimizations.
"""
import time
import threading
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
import logging


class WorkspaceFileMonitor:
    """
    Production-grade workspace directory monitor for file changes during session.
    
    Features:
    - Cross-platform compatibility (Windows, macOS, Linux)
    - Handles large directories efficiently
    - Robust error handling for permission issues
    - Configurable ignore patterns
    - Performance optimizations
    """
    
    # Default ignore patterns - cross-platform
    DEFAULT_IGNORE_PATTERNS = {
        # Hidden files/dirs (Unix-style)
        '.*',
        # OS-specific
        'Thumbs.db',           # Windows thumbnails
        'Desktop.ini',         # Windows folder config  
        '.DS_Store',           # macOS folder metadata
        '._*',                 # macOS resource forks
        # Development artifacts
        '__pycache__',
        '*.pyc',
        '*.pyo', 
        'node_modules',
        '.git',
        '.svn',
        '.hg',
        # Temporary files
        '*.tmp',
        '*.temp',
        '~*',                  # Office temp files
        # IDE files
        '.vscode',
        '.idea',
        '*.swp',              # Vim swap files
        '.#*',                # Emacs lock files
        # ARIS-specific files (exclude from workspace monitoring)
        'logs',               # ARIS log directory
        'logs/*',             # All files in logs directory
        'aris_*.log',         # ARIS log files
        '.aris',              # ARIS profile directory (if in workspace)
        'CLAUDE.md.bak',      # ARIS backup files
    }
    
    def __init__(self, workspace_path: str, ignore_patterns: Optional[Set[str]] = None, max_files: int = 10000):
        """
        Initialize workspace monitor.
        
        Args:
            workspace_path: Path to monitor (can be relative or absolute)
            ignore_patterns: Custom ignore patterns (glob-style), defaults to DEFAULT_IGNORE_PATTERNS
            max_files: Maximum files to track (safety limit for large directories)
        """
        # Normalize path for cross-platform compatibility
        self.workspace_path = Path(workspace_path).resolve()
        self.ignore_patterns = ignore_patterns or self.DEFAULT_IGNORE_PATTERNS.copy()
        self.max_files = max_files
        
        self._lock = threading.RLock()  # Reentrant lock for nested calls
        self._logger = logging.getLogger(__name__)
        
        # Track monitoring state
        self._monitoring_enabled = True
        self._last_scan_time = 0.0
        self._scan_count = 0
        
        # Initialize baseline snapshot
        self._initial_snapshot = self._take_workspace_snapshot()
        
        # Log initialization
        self._logger.debug(f"WorkspaceFileMonitor initialized for: {self.workspace_path}")
        self._logger.debug(f"Initial snapshot contains {len(self._initial_snapshot)} files")
        
    def _should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored based on patterns."""
        import fnmatch
        
        # Check against ignore patterns
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(path.name, pattern):
                return True
            # Also check full relative path for patterns like '.git/*'
            try:
                rel_path = path.relative_to(self.workspace_path)
                if fnmatch.fnmatch(str(rel_path), pattern):
                    return True
            except ValueError:
                # Path is not relative to workspace
                pass
                
        return False
    
    def _take_workspace_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """
        Take snapshot of all files in workspace with metadata.
        
        Returns:
            Dict mapping relative paths to file metadata
        """
        snapshot = {}
        file_count = 0
        
        if not self.workspace_path.exists():
            self._logger.debug(f"Workspace path does not exist: {self.workspace_path}")
            return snapshot
        
        if not self.workspace_path.is_dir():
            self._logger.warning(f"Workspace path is not a directory: {self.workspace_path}")
            return snapshot
            
        try:
            # Use pathlib for cross-platform path handling
            for file_path in self._scan_directory():
                if file_count >= self.max_files:
                    self._logger.warning(f"Hit max_files limit ({self.max_files}), stopping scan")
                    break
                    
                try:
                    # Get relative path for consistent tracking
                    relative_path = file_path.relative_to(self.workspace_path)
                    
                    # Get file stats
                    stat_result = file_path.stat()
                    
                    snapshot[str(relative_path)] = {
                        "size": stat_result.st_size,
                        "mtime": stat_result.st_mtime,
                        "mtime_ns": getattr(stat_result, 'st_mtime_ns', int(stat_result.st_mtime * 1e9)),  # Higher precision
                        "exists": True
                    }
                    file_count += 1
                    
                except (OSError, PermissionError, FileNotFoundError) as e:
                    # File might have been deleted, moved, or is inaccessible
                    self._logger.debug(f"Could not stat file {file_path}: {e}")
                    continue
                except ValueError as e:
                    # Relative path calculation failed
                    self._logger.debug(f"Path not relative to workspace {file_path}: {e}")
                    continue
                    
        except (OSError, PermissionError) as e:
            self._logger.warning(f"Error scanning workspace directory {self.workspace_path}: {e}")
        
        self._scan_count += 1
        self._last_scan_time = time.time()
        
        return snapshot
    
    def _scan_directory(self):
        """
        Generator that yields file paths while respecting ignore patterns.
        Uses pathlib for cross-platform compatibility.
        """
        try:
            for item in self.workspace_path.rglob('*'):
                # Skip if not a file
                if not item.is_file():
                    continue
                    
                # Skip if should be ignored
                if self._should_ignore(item):
                    continue
                    
                yield item
                
        except (OSError, PermissionError) as e:
            self._logger.warning(f"Permission error during directory scan: {e}")
            return
    
    def get_workspace_changes(self) -> Dict[str, List[str]]:
        """
        Get workspace changes since last baseline update.
        
        Returns:
            Dict with 'created', 'modified', 'deleted' file lists
        """
        if not self._monitoring_enabled:
            return {"created": [], "modified": [], "deleted": []}
            
        with self._lock:
            try:
                current_snapshot = self._take_workspace_snapshot()
                
                changes = {
                    "created": [],
                    "modified": [], 
                    "deleted": []
                }
                
                # Find new and modified files
                for file_path, current_info in current_snapshot.items():
                    if file_path not in self._initial_snapshot:
                        changes["created"].append(file_path)
                    else:
                        initial_info = self._initial_snapshot[file_path]
                        # Use high-precision timestamp comparison
                        if current_info["mtime_ns"] > initial_info.get("mtime_ns", int(initial_info["mtime"] * 1e9)):
                            changes["modified"].append(file_path)
                
                # Find deleted files
                for file_path in self._initial_snapshot:
                    if file_path not in current_snapshot:
                        changes["deleted"].append(file_path)
                
                # Log significant changes
                total_changes = len(changes["created"]) + len(changes["modified"]) + len(changes["deleted"])
                if total_changes > 0:
                    self._logger.debug(f"Detected {total_changes} workspace changes: "
                                     f"{len(changes['created'])} created, "
                                     f"{len(changes['modified'])} modified, "
                                     f"{len(changes['deleted'])} deleted")
                
                return changes
                
            except Exception as e:
                self._logger.error(f"Error detecting workspace changes: {e}")
                return {"created": [], "modified": [], "deleted": []}
    
    def update_baseline(self):
        """Update baseline snapshot (call after reporting changes)."""
        if not self._monitoring_enabled:
            return
            
        with self._lock:
            try:
                self._initial_snapshot = self._take_workspace_snapshot()
                self._logger.debug(f"Updated baseline snapshot: {len(self._initial_snapshot)} files")
            except Exception as e:
                self._logger.error(f"Error updating baseline snapshot: {e}")
    
    def disable_monitoring(self):
        """Disable monitoring (for performance in large directories)."""
        self._monitoring_enabled = False
        self._logger.debug("Workspace monitoring disabled")
    
    def enable_monitoring(self):
        """Re-enable monitoring."""
        self._monitoring_enabled = True
        # Refresh baseline when re-enabling
        self.update_baseline()
        self._logger.debug("Workspace monitoring enabled")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics for debugging."""
        return {
            "workspace_path": str(self.workspace_path),
            "monitoring_enabled": self._monitoring_enabled,
            "tracked_files": len(self._initial_snapshot),
            "scan_count": self._scan_count,
            "last_scan_time": self._last_scan_time,
            "ignore_patterns_count": len(self.ignore_patterns)
        }