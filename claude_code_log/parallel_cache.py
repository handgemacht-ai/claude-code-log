#!/usr/bin/env python3
"""Parallel cache manager for Claude Code Log with concurrent processing."""

import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable, Any, Union

from .cache import CacheManager, get_library_version
from .scanner import DirectoryScanner, ProjectInfo, FileInfo

logger = logging.getLogger(__name__)


@dataclass
class WorkItem:
    """Work item for parallel processing."""
    
    project_path: Path
    files: List[FileInfo]
    estimated_size: int
    work_type: str  # 'large_file', 'batch', 'single'

    @property
    def file_count(self) -> int:
        """Number of files in this work item."""
        return len(self.files)


class ParallelCacheManager:
    """Cache manager with parallel processing capabilities."""
    
    def __init__(self, max_workers: Optional[int] = None):
        """Initialize parallel cache manager.
        
        Args:
            max_workers: Maximum number of workers for parallel processing.
                        If None, uses optimal defaults based on system.
        """
        # Use threads for I/O-bound cache validation
        self.io_workers = max_workers or min(32, (os.cpu_count() or 1) * 4)
        
        # Use fewer processes for CPU-intensive parsing to avoid memory pressure
        self.cpu_workers = min(4, os.cpu_count() or 1)
        
        # Thresholds for work batching
        self.large_file_threshold = 10_000_000  # 10MB
        self.batch_size_threshold = 50_000_000  # 50MB batches
        
        logger.info(f"Initialized ParallelCacheManager with {self.io_workers} I/O workers, {self.cpu_workers} CPU workers")
    
    def validate_projects_parallel(
        self, 
        projects: Dict[str, ProjectInfo],
        library_version: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, List[FileInfo]]:
        """Validate all project caches in parallel and return files needing update.
        
        Args:
            projects: Dict of project name -> ProjectInfo from directory scan
            library_version: Current library version for cache validation
            progress_callback: Optional callback for progress updates (completed, total, current_item)
            
        Returns:
            Dict mapping project names to lists of files that need updating
        """
        start_time = time.perf_counter()
        
        # Phase 1: Quick validation using directory snapshot
        validation_tasks = []
        with ThreadPoolExecutor(max_workers=self.io_workers) as executor:
            for project_name, project_info in projects.items():
                future = executor.submit(
                    self._validate_project_cache,
                    project_info,
                    library_version
                )
                validation_tasks.append((future, project_name, project_info))
        
        # Collect files needing update
        files_to_update = {}
        completed = 0
        total = len(validation_tasks)
        
        for future, project_name, project_info in validation_tasks:
            try:
                modified_files = future.result()
                if modified_files:
                    files_to_update[project_name] = modified_files
                    logger.info(f"Project {project_name}: {len(modified_files)} files need updating")
                else:
                    logger.debug(f"Project {project_name}: cache up to date")
                
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, project_name)
                    
            except Exception as e:
                logger.error(f"Failed to validate cache for project {project_name}: {e}")
                # On validation error, assume all files need updating
                files_to_update[project_name] = project_info.jsonl_files
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, f"{project_name} (error)")
        
        validation_time = time.perf_counter() - start_time
        total_files_to_update = sum(len(files) for files in files_to_update.values())
        logger.info(f"Cache validation completed in {validation_time:.3f}s: {total_files_to_update} files need updating")
        
        return files_to_update
    
    def _validate_project_cache(
        self, 
        project_info: ProjectInfo,
        library_version: str
    ) -> List[FileInfo]:
        """Validate cache for a single project using pre-scanned directory info.
        
        Args:
            project_info: ProjectInfo from directory scan
            library_version: Current library version
            
        Returns:
            List of FileInfo objects that need updating
        """
        modified_files = []
        
        # Create cache manager for this project
        cache_manager = CacheManager(project_info.path, library_version)
        
        # Check if cache is valid (library version compatible)
        if not cache_manager._is_cache_version_compatible(library_version):
            logger.info(f"Project {project_info.name}: library version mismatch, invalidating all cache")
            return project_info.jsonl_files
        
        # Compare mtimes from our snapshot (no additional filesystem calls!)
        for jsonl_file in project_info.jsonl_files:
            cache_file = project_info.cache_files.get(jsonl_file.rel_path)
            
            if not cache_file:
                # No cache file exists
                modified_files.append(jsonl_file)
                logger.debug(f"No cache for {jsonl_file.rel_path}")
            elif jsonl_file.mtime > cache_file.mtime:
                # Source file is newer than cache
                modified_files.append(jsonl_file)
                logger.debug(f"Source newer than cache for {jsonl_file.rel_path}")
            else:
                logger.debug(f"Cache up to date for {jsonl_file.rel_path}")
        
        return modified_files
    
    def process_files_parallel(
        self,
        files_by_project: Dict[str, List[FileInfo]],
        library_version: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        use_processes: bool = True
    ) -> None:
        """Process modified files in parallel.
        
        Args:
            files_by_project: Dict mapping project names to lists of files to update
            library_version: Current library version
            progress_callback: Optional callback for progress updates
            use_processes: Whether to use process pool for CPU-intensive work
        """
        if not files_by_project:
            logger.info("No files to process")
            return
        
        start_time = time.perf_counter()
        
        # Create work items with size estimates
        work_items = self._create_work_items(files_by_project)
        
        # Sort by size (largest first) for better load balancing
        work_items.sort(key=lambda x: x.estimated_size, reverse=True)
        
        total_files = sum(item.file_count for item in work_items)
        logger.info(f"Processing {total_files} files across {len(work_items)} work items")
        
        # Process with appropriate executor
        if use_processes and self._should_use_processes(work_items):
            self._process_with_processes(work_items, library_version, progress_callback)
        else:
            self._process_with_threads(work_items, library_version, progress_callback)
        
        processing_time = time.perf_counter() - start_time
        logger.info(f"Parallel processing completed in {processing_time:.3f}s")
    
    def _create_work_items(self, files_by_project: Dict[str, List[FileInfo]]) -> List[WorkItem]:
        """Create work items for parallel processing with optimal batching.
        
        Args:
            files_by_project: Files grouped by project
            
        Returns:
            List of WorkItem objects optimized for parallel processing
        """
        work_items = []
        
        for project_name, files in files_by_project.items():
            if not files:
                continue
            
            project_path = files[0].path.parent  # All files share same parent
            
            # Separate large files from small files
            large_files = []
            small_files = []
            
            for file_info in files:
                if file_info.is_large_file:
                    large_files.append(file_info)
                else:
                    small_files.append(file_info)
            
            # Large files get individual work items
            for large_file in large_files:
                work_items.append(WorkItem(
                    project_path=project_path,
                    files=[large_file],
                    estimated_size=large_file.size,
                    work_type='large_file'
                ))
            
            # Batch small files to optimize throughput
            current_batch = []
            current_batch_size = 0
            
            for small_file in small_files:
                current_batch.append(small_file)
                current_batch_size += small_file.size
                
                # Create batch when it reaches size threshold
                if current_batch_size >= self.batch_size_threshold:
                    work_items.append(WorkItem(
                        project_path=project_path,
                        files=current_batch.copy(),
                        estimated_size=current_batch_size,
                        work_type='batch'
                    ))
                    current_batch = []
                    current_batch_size = 0
            
            # Add remaining small files as final batch
            if current_batch:
                work_items.append(WorkItem(
                    project_path=project_path,
                    files=current_batch,
                    estimated_size=current_batch_size,
                    work_type='batch'
                ))
        
        return work_items
    
    def _should_use_processes(self, work_items: List[WorkItem]) -> bool:
        """Determine whether to use process pool based on workload characteristics.
        
        Args:
            work_items: List of work items to process
            
        Returns:
            True if process pool should be used, False for thread pool
        """
        total_size = sum(item.estimated_size for item in work_items)
        large_file_count = sum(1 for item in work_items if item.work_type == 'large_file')
        
        # Use processes for large workloads or many large files
        return total_size > 100_000_000 or large_file_count > 2  # 100MB threshold
    
    def _process_with_threads(
        self, 
        work_items: List[WorkItem], 
        library_version: str,
        progress_callback: Optional[Callable[[int, int, str], None]]
    ) -> None:
        """Process work items using thread pool.
        
        Args:
            work_items: Work items to process
            library_version: Current library version
            progress_callback: Optional progress callback
        """
        completed = 0
        total_items = len(work_items)
        
        with ThreadPoolExecutor(max_workers=self.io_workers) as executor:
            # Submit all work
            futures = {
                executor.submit(
                    self._process_work_item,
                    item,
                    library_version
                ): item
                for item in work_items
            }
            
            # Process results as they complete
            for future in as_completed(futures):
                work_item = futures[future]
                try:
                    future.result()  # This will raise if the work item failed
                    completed += 1
                    if progress_callback:
                        file_names = [f.path.name for f in work_item.files[:3]]  # Show first 3 file names
                        display_name = ", ".join(file_names)
                        if len(work_item.files) > 3:
                            display_name += f" (+{len(work_item.files) - 3} more)"
                        progress_callback(completed, total_items, display_name)
                except Exception as e:
                    logger.error(f"Failed to process work item {work_item}: {e}")
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total_items, "ERROR")
    
    def _process_with_processes(
        self, 
        work_items: List[WorkItem], 
        library_version: str,
        progress_callback: Optional[Callable[[int, int, str], None]]
    ) -> None:
        """Process work items using process pool for CPU-intensive work.
        
        Args:
            work_items: Work items to process
            library_version: Current library version
            progress_callback: Optional progress callback
        """
        completed = 0
        total_items = len(work_items)
        
        with ProcessPoolExecutor(max_workers=self.cpu_workers) as executor:
            # Submit all work
            futures = {
                executor.submit(
                    process_work_item_isolated,  # Pickleable function
                    item,
                    library_version
                ): item
                for item in work_items
            }
            
            # Process results as they complete
            for future in as_completed(futures):
                work_item = futures[future]
                try:
                    future.result()
                    completed += 1
                    if progress_callback:
                        file_names = [f.path.name for f in work_item.files[:3]]
                        display_name = ", ".join(file_names)
                        if len(work_item.files) > 3:
                            display_name += f" (+{len(work_item.files) - 3} more)"
                        progress_callback(completed, total_items, display_name)
                except Exception as e:
                    logger.error(f"Failed to process work item {work_item}: {e}")
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total_items, "ERROR")
    
    def _process_work_item(self, work_item: WorkItem, library_version: str) -> None:
        """Process a single work item (for thread pool).
        
        Args:
            work_item: Work item to process
            library_version: Current library version
        """
        cache_manager = CacheManager(work_item.project_path, library_version)
        
        for file_info in work_item.files:
            try:
                # Import here to avoid circular imports
                from .parser import load_transcript
                
                # Process the file using parser
                transcript_data = load_transcript(file_info.path, cache_manager)
                
                logger.debug(f"Processed {file_info.path.name}: {len(transcript_data.entries)} entries")
                
            except Exception as e:
                logger.error(f"Error processing {file_info.path}: {e}")
                raise


# Pickleable function for process pool
def process_work_item_isolated(work_item: WorkItem, library_version: str) -> None:
    """Process work item in isolated process.
    
    This function must be at module level to be pickleable for ProcessPoolExecutor.
    
    Args:
        work_item: Work item to process
        library_version: Current library version
    """
    cache_manager = CacheManager(work_item.project_path, library_version)
    
    for file_info in work_item.files:
        try:
            # Import here to avoid issues with process forking
            from .parser import load_transcript
            
            # Process the file
            transcript_data = load_transcript(file_info.path, cache_manager)
            
            logger.debug(f"Process {os.getpid()}: Processed {file_info.path.name}: {len(transcript_data.entries)} entries")
            
        except Exception as e:
            logger.error(f"Process {os.getpid()}: Error processing {file_info.path}: {e}")
            raise


def validate_cache_fast(
    projects_root: Path, 
    library_version: Optional[str] = None,
    max_workers: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Dict[str, List[FileInfo]]:
    """Fast cache validation for all projects using parallel processing.
    
    Args:
        projects_root: Root directory containing projects
        library_version: Library version for compatibility checking
        max_workers: Maximum number of parallel workers
        progress_callback: Optional progress callback
        
    Returns:
        Dict mapping project names to files that need updating
    """
    if library_version is None:
        library_version = get_library_version()
    
    # Fast directory scan
    scanner = DirectoryScanner()
    projects = scanner.scan_projects(projects_root)
    
    if not projects:
        logger.warning(f"No projects found in {projects_root}")
        return {}
    
    # Parallel cache validation
    parallel_cache = ParallelCacheManager(max_workers)
    return parallel_cache.validate_projects_parallel(projects, library_version, progress_callback)