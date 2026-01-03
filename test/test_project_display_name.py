#!/usr/bin/env python3
"""Tests for project display name generation logic."""

from claude_code_log.utils import get_project_display_name


class TestProjectDisplayName:
    """Test the get_project_display_name function with various scenarios."""

    def test_claude_code_log_with_test_subdirectory(self):
        """Test that project root is preferred over test subdirectories."""
        project_dir_name = "-Users-dain-workspace-claude-code-log"
        working_directories = [
            "/Users/dain/workspace/claude-code-log",
            "/Users/dain/workspace/claude-code-log/test/test_data",
        ]

        result = get_project_display_name(project_dir_name, working_directories)
        assert result == "claude-code-log"

    def test_platform_frontend_next_case(self):
        """Test the original platform-frontend-next case still works."""
        project_dir_name = "-Users-dain-workspace-platform-frontend-next"
        working_directories = ["/Users/dain/workspace/platform-frontend-next"]

        result = get_project_display_name(project_dir_name, working_directories)
        assert result == "platform-frontend-next"

    def test_multiple_nested_directories(self):
        """Test with multiple nested working directories - should pick root."""
        project_dir_name = "-Users-dain-workspace-myproject"
        working_directories = [
            "/Users/dain/workspace/myproject",
            "/Users/dain/workspace/myproject/src/components",
            "/Users/dain/workspace/myproject/test",
            "/Users/dain/workspace/myproject/docs/examples",
        ]

        result = get_project_display_name(project_dir_name, working_directories)
        assert result == "myproject"

    def test_only_nested_directories(self):
        """Test when only nested directories are available."""
        project_dir_name = "-Users-dain-workspace-myproject"
        working_directories = [
            "/Users/dain/workspace/myproject/src/components",
            "/Users/dain/workspace/myproject/test",
            "/Users/dain/workspace/myproject/docs/examples",
        ]

        result = get_project_display_name(project_dir_name, working_directories)
        # Should pick the shortest path (least nested)
        assert result in ["src", "test", "docs"]  # Any of the first-level subdirs

    def test_same_depth_different_lengths(self):
        """Test paths with same depth but different lengths."""
        project_dir_name = "-Users-dain-workspace-myproject"
        working_directories = [
            "/Users/dain/workspace/myproject/short",
            "/Users/dain/workspace/myproject/very-long-directory-name",
        ]

        result = get_project_display_name(project_dir_name, working_directories)
        # Should pick the shorter path when depth is the same
        assert result == "short"

    def test_empty_working_directories(self):
        """Test fallback when no working directories are provided."""
        project_dir_name = "-Users-dain-workspace-platform-frontend-next"
        working_directories = []

        result = get_project_display_name(project_dir_name, working_directories)
        # Should fall back to path conversion
        assert result == "Users/dain/workspace/platform/frontend/next"

    def test_single_working_directory(self):
        """Test with a single working directory."""
        project_dir_name = "-Users-dain-workspace-simple-project"
        working_directories = ["/Users/dain/workspace/simple-project"]

        result = get_project_display_name(project_dir_name, working_directories)
        assert result == "simple-project"

    def test_project_dir_without_leading_dash(self):
        """Test project directory name without leading dash."""
        project_dir_name = "simple-project"
        working_directories = ["/Users/dain/workspace/simple-project"]

        result = get_project_display_name(project_dir_name, working_directories)
        assert result == "simple-project"

    def test_working_directory_with_complex_nesting(self):
        """Test with deeply nested and complex directory structures."""
        project_dir_name = "-Users-dain-workspace-complex-project"
        working_directories = [
            "/Users/dain/workspace/complex-project",
            "/Users/dain/workspace/complex-project/backend/api/v1",
            "/Users/dain/workspace/complex-project/frontend/src/components/ui",
            "/Users/dain/workspace/complex-project/test/integration/api",
        ]

        result = get_project_display_name(project_dir_name, working_directories)
        assert result == "complex-project"

    def test_working_directories_same_name_different_paths(self):
        """Test when multiple working directories have the same final directory name."""
        project_dir_name = "-Users-dain-workspace-shared-names"
        working_directories = [
            "/Users/dain/workspace/shared-names/frontend/components",
            "/Users/dain/workspace/shared-names/backend/components",
            "/Users/dain/workspace/shared-names",
        ]

        result = get_project_display_name(project_dir_name, working_directories)
        # Should pick the root directory
        assert result == "shared-names"

    def test_tmp_paths_filtered_out(self):
        """Test that temporary paths (pytest, macOS temp) are filtered out."""
        project_dir_name = "-tmp-pytest-123-test_foo0"
        working_directories = [
            "/private/var/folders/4n/2f7pppjd2_n0fftzg8vrlg040000gn/T/pytest-91/test_foo0",
            "/Users/dain/workspace/real-project",
        ]

        result = get_project_display_name(project_dir_name, working_directories)
        # Should use the real project, not the pytest temp dir
        assert result == "real-project"

    def test_only_tmp_paths_falls_back(self):
        """Test fallback when all working directories are tmp paths."""
        project_dir_name = "-tmp-pytest-123-test_foo0"
        working_directories = [
            "/private/var/folders/4n/test",
            "/tmp/pytest-91/test_foo0",
        ]

        result = get_project_display_name(project_dir_name, working_directories)
        # Should fall back to converting project directory name
        assert result == "tmp/pytest/123/test_foo0"
