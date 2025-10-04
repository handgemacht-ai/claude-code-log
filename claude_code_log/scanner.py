#!/usr/bin/env python3
"""Fast directory scanner for Claude Code Log using os.scandir()."""

import os
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """Lightweight file metadata from single scan."""
    
    path: Path
    size: int
    mtime: float
    rel_path: str  # Relative to project root

    @property
    def is_large_file(self) -> bool:
        """Check if this is a large file that should be processed individually."""
        return self.size > 10_000_000  # > 10MB


@dataclass
class ProjectInfo:
    """All files in a project from single scan."""
    
    path: Path
    name: str
    jsonl_files: List[FileInfo] = field(default_factory=list)
    cache_files: Dict[str, FileInfo] = field(default_factory=dict)  # jsonl_name -> cache file
    cache_index_mtime: Optional[float] = None
    
    @property
    def total_size(self) -> int:
        """Total size of all JSONL files in bytes."""
        return sum(f.size for f in self.jsonl_files)
    
    @property
    def total_files(self) -> int:
        """Total number of JSONL files."""
        return len(self.jsonl_files)


class DirectoryScanner:
    """Ultra-fast directory scanner using os.scandir()."""
    
    def scan_projects(self, root_path: Path) -> Dict[str, ProjectInfo]:
        """Scan entire projects directory in one pass.
        
        Args:
            root_path: Path to ~/.claude/projects/ or similar
            
        Returns:
            Dict mapping project names to ProjectInfo objects
        """
        start_time = time.perf_counter()
        projects = {}
        
        if not root_path.exists():
            logger.warning(f"Projects directory does not exist: {root_path}")
            return projects
        
        try:
            # Single pass with os.scandir - much faster than multiple globs
            with os.scandir(root_path) as entries:
                for project_entry in entries:
                    if project_entry.is_dir(follow_symlinks=False):
                        try:
                            project_info = self._scan_project(project_entry)
                            if project_info.jsonl_files:  # Only include projects with JSONL files
                                projects[project_info.name] = project_info
                        except OSError as e:
                            logger.warning(f"Failed to scan project {project_entry.name}: {e}")
                            continue
        except OSError as e:
            logger.error(f"Failed to scan projects directory {root_path}: {e}")
            return projects
        
        scan_time = time.perf_counter() - start_time
        logger.info(f"Scanned {len(projects)} projects with {sum(p.total_files for p in projects.values())} total files in {scan_time:.3f}s")
        return projects
    
    def scan_single_project(self, project_path: Path) -> Optional[ProjectInfo]:
        """Scan a single project directory efficiently.
        
        Args:
            project_path: Path to a specific project directory
            
        Returns:
            ProjectInfo object or None if scan fails
        """
        if not project_path.exists() or not project_path.is_dir():
            return None
        
        try:
            # Create a fake DirEntry-like object for _scan_project
            class FakeDirEntry:
                def __init__(self, path: Path):
                    self.path = str(path)
                    self.name = path.name
                
                def is_dir(self):
                    return True
            
            fake_entry = FakeDirEntry(project_path)
            return self._scan_project(fake_entry)
        except OSError as e:
            logger.warning(f"Failed to scan project {project_path}: {e}")
            return None
    
    def _scan_project(self, project_entry: Union[os.DirEntry, object]) -> ProjectInfo:
        """Scan single project directory efficiently.
        
        Args:
            project_entry: os.DirEntry from scandir or fake entry object
            
        Returns:
            ProjectInfo with all file metadata
        """
        project_path = Path(project_entry.path)
        project_info = ProjectInfo(
            path=project_path,
            name=project_entry.name
        )
        
        # Scan project root and cache subdirectory in one go
        try:
            with os.scandir(project_path) as entries:
                for entry in entries:
                    if entry.is_file():
                        if entry.name.endswith('.jsonl'):
                            # DirEntry.stat() is cached from scandir
                            stat_result = entry.stat()
                            project_info.jsonl_files.append(FileInfo(
                                path=Path(entry.path),
                                size=stat_result.st_size,
                                mtime=stat_result.st_mtime,
                                rel_path=entry.name
                            ))
                    elif entry.name == 'cache' and entry.is_dir():
                        # Scan cache directory
                        self._scan_cache_dir(entry.path, project_info)
        except OSError as e:
            logger.warning(f"Failed to scan project directory {project_path}: {e}")
        
        # Sort JSONL files by modification time (newest first) for better processing order
        project_info.jsonl_files.sort(key=lambda f: f.mtime, reverse=True)
        
        return project_info
    
    def _scan_cache_dir(self, cache_path: str, project_info: ProjectInfo) -> None:
        """Scan cache directory for existing cache files.
        
        Args:
            cache_path: Path to the cache directory
            project_info: ProjectInfo to update with cache file information
        """
        try:
            with os.scandir(cache_path) as entries:
                for entry in entries:
                    if entry.is_file():
                        if entry.name == 'index.json':
                            # Store cache index modification time
                            project_info.cache_index_mtime = entry.stat().st_mtime
                        elif entry.name.endswith('.json'):
                            # Map cache files to their source JSONL
                            jsonl_name = entry.name[:-5] + '.jsonl'  # Remove .json, add .jsonl
                            stat_result = entry.stat()
                            project_info.cache_files[jsonl_name] = FileInfo(
                                path=Path(entry.path),
                                size=stat_result.st_size,
                                mtime=stat_result.st_mtime,
                                rel_path=f"cache/{entry.name}"
                            )
        except OSError as e:
            logger.warning(f"Failed to scan cache directory {cache_path}: {e}")


def scan_directory_fast(directory_path: Path) -> Optional[ProjectInfo]:
    """Convenience function to quickly scan a single directory.
    
    Args:
        directory_path: Path to scan
        
    Returns:
        ProjectInfo or None if scan fails
    """
    scanner = DirectoryScanner()
    return scanner.scan_single_project(directory_path)


def scan_projects_fast(projects_root: Path) -> Dict[str, ProjectInfo]:
    """Convenience function to quickly scan all projects.
    
    Args:
        projects_root: Path to projects root directory (e.g., ~/.claude/projects/)
        
    Returns:
        Dict mapping project names to ProjectInfo objects
    """
    scanner = DirectoryScanner()
    return scanner.scan_projects(projects_root)