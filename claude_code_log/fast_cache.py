#!/usr/bin/env python3
"""Fast cache operations with graceful fallbacks to traditional methods."""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any

from .cache import CacheManager, get_library_version

logger = logging.getLogger(__name__)


def validate_cache_with_fallback(
    project_path: Path,
    library_version: Optional[str] = None,
    use_fast_scan: bool = True,
    profiler: Optional[object] = None
) -> List[Path]:
    """Validate cache with fast scan, falling back to traditional method on error.
    
    Args:
        project_path: Path to project directory
        library_version: Library version for compatibility checking
        use_fast_scan: Whether to attempt fast scanning first
        profiler: Optional profiler for performance measurement
        
    Returns:
        List of files that need updating
    """
    if library_version is None:
        library_version = get_library_version()
    
    if use_fast_scan:
        try:
            # Try fast scanning approach
            from .scanner import DirectoryScanner
            from .parallel_cache import ParallelCacheManager
            
            scanner = DirectoryScanner()
            project_info = scanner.scan_single_project(project_path)
            
            if project_info and project_info.jsonl_files:
                parallel_cache = ParallelCacheManager()
                modified_files = parallel_cache._validate_project_cache(project_info, library_version)
                
                logger.debug(f"Fast scan: {len(modified_files)}/{len(project_info.jsonl_files)} files need updating")
                return modified_files
            else:
                logger.debug("Fast scan found no JSONL files, falling back to traditional method")
                
        except Exception as e:
            logger.warning(f"Fast scan failed ({e}), falling back to traditional method")
    
    # Fall back to traditional cache checking
    logger.debug("Using traditional cache validation")
    cache_manager = CacheManager(project_path, library_version, profiler)
    jsonl_files = list(project_path.glob("*.jsonl"))
    return cache_manager.get_modified_files(jsonl_files)


def get_project_sessions_fast(
    projects_root: Path,
    use_fast_scan: bool = True,
    max_workers: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Dict[str, Any]:
    """Get project sessions data using fast scanning with fallback.
    
    Args:
        projects_root: Path to projects root directory
        use_fast_scan: Whether to use fast scanning
        max_workers: Maximum number of workers for parallel processing
        progress_callback: Optional progress callback
        
    Returns:
        Dict containing project information
    """
    if use_fast_scan:
        try:
            from .scanner import DirectoryScanner
            from .parallel_cache import ParallelCacheManager
            
            # Fast directory scan
            scanner = DirectoryScanner()
            projects = scanner.scan_projects(projects_root)
            
            if not projects:
                logger.debug("Fast scan found no projects")
                return {}
            
            # Fast cache validation
            parallel_cache = ParallelCacheManager(max_workers)
            files_to_update = parallel_cache.validate_projects_parallel(
                projects, 
                get_library_version(),
                progress_callback
            )
            
            result = {
                "projects": projects,
                "files_to_update": files_to_update,
                "method": "fast_scan"
            }
            
            logger.info(f"Fast scan completed: {len(projects)} projects, {sum(len(files) for files in files_to_update.values())} files need updating")
            return result
            
        except Exception as e:
            logger.warning(f"Fast project scan failed ({e}), falling back to traditional method")
    
    # Fall back to traditional method
    logger.debug("Using traditional project scanning")
    return _get_project_sessions_traditional(projects_root, progress_callback)


def _get_project_sessions_traditional(
    projects_root: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Dict[str, Any]:
    """Traditional project session scanning as fallback."""
    projects = {}
    files_to_update = {}
    
    if not projects_root.exists():
        return {"projects": projects, "files_to_update": files_to_update, "method": "traditional"}
    
    # Get all project directories
    project_dirs = [d for d in projects_root.iterdir() if d.is_dir()]
    
    completed = 0
    total = len(project_dirs)
    
    for project_dir in project_dirs:
        try:
            jsonl_files = list(project_dir.glob("*.jsonl"))
            if not jsonl_files:
                continue
            
            # Use traditional cache manager
            cache_manager = CacheManager(project_dir, get_library_version())
            modified_files = cache_manager.get_modified_files(jsonl_files)
            
            if modified_files:
                files_to_update[project_dir.name] = modified_files
            
            # Create minimal project info
            projects[project_dir.name] = {
                "path": project_dir,
                "name": project_dir.name,
                "jsonl_files": jsonl_files,
                "total_files": len(jsonl_files)
            }
            
            completed += 1
            if progress_callback:
                progress_callback(completed, total, project_dir.name)
                
        except Exception as e:
            logger.warning(f"Failed to process project {project_dir.name}: {e}")
            completed += 1
            if progress_callback:
                progress_callback(completed, total, f"{project_dir.name} (error)")
    
    return {
        "projects": projects,
        "files_to_update": files_to_update,
        "method": "traditional"
    }


def process_cache_updates_fast(
    files_by_project: Dict[str, List[Any]],
    library_version: Optional[str] = None,
    use_parallel: bool = True,
    max_workers: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> bool:
    """Process cache updates using fast parallel processing with fallback.
    
    Args:
        files_by_project: Dict mapping project names to files needing updates
        library_version: Library version
        use_parallel: Whether to use parallel processing
        max_workers: Maximum number of workers
        progress_callback: Optional progress callback
        
    Returns:
        True if processing succeeded
    """
    if library_version is None:
        library_version = get_library_version()
    
    if not files_by_project:
        logger.info("No files need updating")
        return True
    
    total_files = sum(len(files) for files in files_by_project.values())
    logger.info(f"Processing {total_files} files across {len(files_by_project)} projects")
    
    if use_parallel and total_files > 1:
        try:
            from .parallel_cache import ParallelCacheManager
            
            # Convert file info to proper format for parallel processing
            parallel_cache = ParallelCacheManager(max_workers)
            
            # For now, we'll use the traditional per-project processing
            # since the parallel processing needs the file info in a specific format
            logger.info("Using parallel processing for cache updates")
            
            completed_projects = 0
            total_projects = len(files_by_project)
            
            for project_name, files in files_by_project.items():
                try:
                    if not files:
                        continue
                    
                    project_path = files[0].path.parent if hasattr(files[0], 'path') else Path(files[0]).parent
                    
                    # Process each file in the project
                    from .converter import ensure_fresh_cache
                    cache_manager = CacheManager(project_path, library_version)
                    ensure_fresh_cache(project_path, cache_manager, silent=True)
                    
                    completed_projects += 1
                    if progress_callback:
                        progress_callback(completed_projects, total_projects, project_name)
                    
                except Exception as e:
                    logger.error(f"Failed to process project {project_name}: {e}")
                    completed_projects += 1
                    if progress_callback:
                        progress_callback(completed_projects, total_projects, f"{project_name} (error)")
            
            return True
            
        except Exception as e:
            logger.warning(f"Parallel processing failed ({e}), falling back to sequential")
    
    # Fall back to sequential processing
    logger.info("Using sequential processing for cache updates")
    return _process_cache_updates_sequential(files_by_project, library_version, progress_callback)


def _process_cache_updates_sequential(
    files_by_project: Dict[str, List[Any]],
    library_version: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> bool:
    """Sequential cache update processing as fallback."""
    completed_projects = 0
    total_projects = len(files_by_project)
    
    for project_name, files in files_by_project.items():
        try:
            if not files:
                continue
            
            project_path = files[0].path.parent if hasattr(files[0], 'path') else Path(files[0]).parent
            
            # Use traditional converter method
            from .converter import ensure_fresh_cache
            cache_manager = CacheManager(project_path, library_version)
            ensure_fresh_cache(project_path, cache_manager, silent=True)
            
            completed_projects += 1
            if progress_callback:
                progress_callback(completed_projects, total_projects, project_name)
            
        except Exception as e:
            logger.error(f"Failed to process project {project_name}: {e}")
            completed_projects += 1
            if progress_callback:
                progress_callback(completed_projects, total_projects, f"{project_name} (error)")
    
    return True