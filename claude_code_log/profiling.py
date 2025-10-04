#!/usr/bin/env python3
"""Profiling utilities for Claude Code Log performance measurement."""

import time
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import json

logger = logging.getLogger(__name__)


class CacheProfiler:
    """Profiler for cache operations and performance measurement."""
    
    def __init__(self):
        """Initialize profiler with empty timings and counters."""
        self.timings: Dict[str, List[float]] = {}
        self.counters: Dict[str, int] = {}
        self.metadata: Dict[str, Any] = {}
    
    @contextmanager
    def measure(self, operation: str):
        """Context manager to measure operation timing.
        
        Args:
            operation: Name of the operation being measured
            
        Yields:
            None
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            if operation not in self.timings:
                self.timings[operation] = []
            self.timings[operation].append(elapsed)
    
    def count(self, operation: str, count: int = 1) -> None:
        """Record a count for an operation.
        
        Args:
            operation: Name of the operation
            count: Count to add (default 1)
        """
        if operation not in self.counters:
            self.counters[operation] = 0
        self.counters[operation] += count
    
    def record_metadata(self, key: str, value: Any) -> None:
        """Record metadata about the profiling session.
        
        Args:
            key: Metadata key
            value: Metadata value
        """
        self.metadata[key] = value
    
    def get_timing_stats(self, operation: str) -> Optional[Dict[str, float]]:
        """Get timing statistics for an operation.
        
        Args:
            operation: Operation name
            
        Returns:
            Dict with timing stats or None if operation not found
        """
        if operation not in self.timings:
            return None
        
        times = self.timings[operation]
        return {
            "count": len(times),
            "total": sum(times),
            "mean": sum(times) / len(times),
            "min": min(times),
            "max": max(times),
            "total_ms": sum(times) * 1000,
            "mean_ms": (sum(times) / len(times)) * 1000,
            "min_ms": min(times) * 1000,
            "max_ms": max(times) * 1000,
        }
    
    def report(self) -> Dict[str, Any]:
        """Generate comprehensive profiling report.
        
        Returns:
            Dict containing all profiling data and statistics
        """
        report = {
            "metadata": self.metadata.copy(),
            "counters": self.counters.copy(),
            "timings": {},
            "summary": {}
        }
        
        # Process timing data
        for operation, times in self.timings.items():
            report["timings"][operation] = self.get_timing_stats(operation)
        
        # Calculate summary metrics
        self._calculate_summary_metrics(report)
        
        return report
    
    def _calculate_summary_metrics(self, report: Dict[str, Any]) -> None:
        """Calculate summary metrics for the report.
        
        Args:
            report: Report dict to update with summary metrics
        """
        summary = report["summary"]
        
        # Cache validation metrics
        if "cache_validation" in self.timings:
            stats = self.get_timing_stats("cache_validation")
            if stats:
                summary["cache_validation_ms"] = stats["total_ms"]
                summary["avg_cache_validation_ms"] = stats["mean_ms"]
        
        # Directory scan metrics
        if "directory_scan" in self.timings:
            stats = self.get_timing_stats("directory_scan")
            if stats:
                summary["directory_scan_ms"] = stats["total_ms"]
        
        # File processing metrics
        if "file_processing" in self.timings:
            stats = self.get_timing_stats("file_processing")
            if stats:
                summary["file_processing_ms"] = stats["total_ms"]
                summary["avg_file_processing_ms"] = stats["mean_ms"]
        
        # Filesystem operation counts
        if "filesystem_calls" in self.counters:
            summary["total_filesystem_calls"] = self.counters["filesystem_calls"]
        
        if "files_processed" in self.counters:
            files_processed = self.counters["files_processed"]
            summary["files_processed"] = files_processed
            
            # Calculate per-file metrics
            if "file_processing" in self.timings and files_processed > 0:
                total_processing_time = sum(self.timings["file_processing"])
                summary["avg_ms_per_file"] = (total_processing_time / files_processed) * 1000
        
        # Cache hit rate
        cache_hits = self.counters.get("cache_hits", 0)
        cache_misses = self.counters.get("cache_misses", 0)
        total_cache_checks = cache_hits + cache_misses
        
        if total_cache_checks > 0:
            summary["cache_hit_rate"] = cache_hits / total_cache_checks
            summary["cache_hits"] = cache_hits
            summary["cache_misses"] = cache_misses
    
    def print_summary(self) -> None:
        """Print a human-readable summary of profiling results."""
        report = self.report()
        summary = report["summary"]
        
        print("\n" + "="*60)
        print("Cache Performance Profile")
        print("="*60)
        
        # Metadata
        if report["metadata"]:
            print(f"Session: {report['metadata'].get('session_name', 'Unknown')}")
            print(f"Projects: {report['metadata'].get('project_count', 'Unknown')}")
            print(f"Total Files: {report['metadata'].get('total_files', 'Unknown')}")
            print("-" * 60)
        
        # Key metrics
        if "cache_validation_ms" in summary:
            print(f"Cache Validation: {summary['cache_validation_ms']:.1f}ms")
        
        if "directory_scan_ms" in summary:
            print(f"Directory Scan: {summary['directory_scan_ms']:.1f}ms")
        
        if "file_processing_ms" in summary:
            print(f"File Processing: {summary['file_processing_ms']:.1f}ms")
        
        if "avg_ms_per_file" in summary:
            print(f"Avg per File: {summary['avg_ms_per_file']:.1f}ms")
        
        # Cache metrics
        if "cache_hit_rate" in summary:
            hit_rate = summary["cache_hit_rate"] * 100
            print(f"Cache Hit Rate: {hit_rate:.1f}% ({summary['cache_hits']}/{summary['cache_hits'] + summary['cache_misses']})")
        
        # Filesystem calls
        if "total_filesystem_calls" in summary:
            print(f"Filesystem Calls: {summary['total_filesystem_calls']}")
        
        print("=" * 60)
    
    def save_report(self, output_path: Path) -> None:
        """Save profiling report to JSON file.
        
        Args:
            output_path: Path to save the report
        """
        report = self.report()
        
        # Add timestamp
        report["timestamp"] = time.time()
        report["timestamp_iso"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Profiling report saved to {output_path}")


@contextmanager
def profile_cache_operation(
    profiler: Optional[CacheProfiler] = None,
    operation_name: str = "cache_operation"
):
    """Context manager for profiling cache operations.
    
    Args:
        profiler: CacheProfiler instance, creates new one if None
        operation_name: Name of the operation being profiled
        
    Yields:
        CacheProfiler instance
    """
    if profiler is None:
        profiler = CacheProfiler()
    
    with profiler.measure(operation_name):
        yield profiler


def compare_profiles(baseline_path: Path, comparison_path: Path) -> Dict[str, Any]:
    """Compare two profiling reports and calculate improvements.
    
    Args:
        baseline_path: Path to baseline profile JSON
        comparison_path: Path to comparison profile JSON
        
    Returns:
        Dict containing comparison results
    """
    with open(baseline_path, "r") as f:
        baseline = json.load(f)
    
    with open(comparison_path, "r") as f:
        comparison = json.load(f)
    
    comparison_result = {
        "baseline": baseline_path.name,
        "comparison": comparison_path.name,
        "improvements": {},
        "regressions": {},
        "summary": {}
    }
    
    baseline_summary = baseline.get("summary", {})
    comparison_summary = comparison.get("summary", {})
    
    # Compare key metrics
    metrics_to_compare = [
        "cache_validation_ms",
        "directory_scan_ms", 
        "file_processing_ms",
        "avg_ms_per_file",
        "total_filesystem_calls",
        "cache_hit_rate"
    ]
    
    for metric in metrics_to_compare:
        if metric in baseline_summary and metric in comparison_summary:
            baseline_val = baseline_summary[metric]
            comparison_val = comparison_summary[metric]
            
            if baseline_val > 0:  # Avoid division by zero
                if metric == "cache_hit_rate":
                    # For hit rate, higher is better
                    improvement = (comparison_val - baseline_val) / baseline_val
                else:
                    # For timing/count metrics, lower is better
                    improvement = (baseline_val - comparison_val) / baseline_val
                
                improvement_pct = improvement * 100
                
                comparison_result["summary"][metric] = {
                    "baseline": baseline_val,
                    "comparison": comparison_val,
                    "improvement_pct": improvement_pct,
                    "better": improvement > 0
                }
                
                if improvement > 0:
                    comparison_result["improvements"][metric] = improvement_pct
                else:
                    comparison_result["regressions"][metric] = improvement_pct
    
    return comparison_result


def print_profile_comparison(comparison: Dict[str, Any]) -> None:
    """Print a human-readable comparison of two profiles.
    
    Args:
        comparison: Comparison result from compare_profiles()
    """
    print(f"\nProfile Comparison: {comparison['baseline']} vs {comparison['comparison']}")
    print("=" * 80)
    
    summary = comparison["summary"]
    
    for metric, data in summary.items():
        baseline = data["baseline"]
        comp_val = data["comparison"]
        improvement = data["improvement_pct"]
        better = data["better"]
        
        symbol = "✓" if better else "✗"
        direction = "improvement" if better else "regression"
        
        print(f"{symbol} {metric}: {baseline:.1f} → {comp_val:.1f} ({improvement:+.1f}% {direction})")
    
    # Overall summary
    improvements = list(comparison["improvements"].keys())
    regressions = list(comparison["regressions"].keys())
    
    print(f"\nSummary: {len(improvements)} improvements, {len(regressions)} regressions")
    
    if improvements:
        print(f"Best improvement: {max(comparison['improvements'], key=comparison['improvements'].get)} "
              f"({comparison['improvements'][max(comparison['improvements'], key=comparison['improvements'].get)]:+.1f}%)")
    
    if regressions:
        print(f"Worst regression: {min(comparison['regressions'], key=comparison['regressions'].get)} "
              f"({comparison['regressions'][min(comparison['regressions'], key=comparison['regressions'].get)]:+.1f}%)")


def create_test_profiler(project_count: int = 1, file_count: int = 10) -> CacheProfiler:
    """Create a profiler with test data for development/testing.
    
    Args:
        project_count: Number of projects to simulate
        file_count: Number of files per project to simulate
        
    Returns:
        CacheProfiler with simulated data
    """
    profiler = CacheProfiler()
    
    # Record metadata
    profiler.record_metadata("session_name", "test_session")
    profiler.record_metadata("project_count", project_count)
    profiler.record_metadata("total_files", project_count * file_count)
    
    # Simulate some timings
    for i in range(project_count):
        # Simulate directory scan
        with profiler.measure("directory_scan"):
            time.sleep(0.001)  # 1ms simulation
        
        # Simulate cache validation
        with profiler.measure("cache_validation"):
            time.sleep(0.005)  # 5ms simulation
        
        # Simulate file processing
        for j in range(file_count):
            with profiler.measure("file_processing"):
                time.sleep(0.002)  # 2ms per file simulation
            
            profiler.count("files_processed")
            profiler.count("filesystem_calls", 2)  # 2 calls per file
            
            # Simulate cache hits/misses
            if j % 3 == 0:  # 33% cache miss rate
                profiler.count("cache_misses")
            else:
                profiler.count("cache_hits")
    
    return profiler