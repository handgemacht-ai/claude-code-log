#!/usr/bin/env python3
"""Tests for migration runner functionality."""

import sqlite3
from pathlib import Path

import pytest

from claude_code_log.migrations.runner import (
    _compute_checksum,
    _ensure_schema_version_table,
    _parse_migration_number,
    apply_migration,
    get_applied_migrations,
    get_available_migrations,
    get_current_version,
    get_pending_migrations,
    run_migrations,
    verify_migrations,
)


class TestParseMigrationNumber:
    """Tests for migration filename parsing."""

    def test_parses_standard_format(self):
        """Parses standard migration filename."""
        assert _parse_migration_number("001_initial_schema.sql") == 1
        assert _parse_migration_number("002_add_column.sql") == 2
        assert _parse_migration_number("010_fix_bug.sql") == 10
        assert _parse_migration_number("100_big_change.sql") == 100

    def test_handles_double_underscores(self):
        """Handles filenames with multiple underscores."""
        assert _parse_migration_number("003_add_html_cache.sql") == 3

    def test_invalid_format_raises_error(self):
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError):
            _parse_migration_number("invalid.sql")
        with pytest.raises(ValueError):
            _parse_migration_number("no_number.sql")
        with pytest.raises(ValueError):
            _parse_migration_number("abc_name.sql")


class TestComputeChecksum:
    """Tests for checksum computation."""

    def test_consistent_checksum(self):
        """Same content produces same checksum."""
        content = "CREATE TABLE test (id INTEGER);"
        checksum1 = _compute_checksum(content)
        checksum2 = _compute_checksum(content)
        assert checksum1 == checksum2

    def test_different_content_different_checksum(self):
        """Different content produces different checksum."""
        checksum1 = _compute_checksum("CREATE TABLE test1;")
        checksum2 = _compute_checksum("CREATE TABLE test2;")
        assert checksum1 != checksum2

    def test_checksum_is_sha256_hex(self):
        """Checksum is 64-character hex string (SHA256)."""
        checksum = _compute_checksum("test")
        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)


class TestEnsureSchemaVersionTable:
    """Tests for schema version table creation."""

    def test_creates_table_if_not_exists(self, tmp_path: Path):
        """Creates _schema_version table on fresh database."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)

        _ensure_schema_version_table(conn)

        # Verify table exists with correct columns
        columns = conn.execute("PRAGMA table_info(_schema_version)").fetchall()
        column_names = {col[1] for col in columns}
        assert "version" in column_names
        assert "filename" in column_names
        assert "applied_at" in column_names
        assert "checksum" in column_names

        conn.close()

    def test_upgrades_old_format_table(self, tmp_path: Path):
        """Upgrades old format table (without checksum) to new format."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)

        # Create old format table (without checksum)
        conn.execute("""
            CREATE TABLE _schema_version (
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)
        conn.commit()

        # Call ensure - should upgrade
        _ensure_schema_version_table(conn)

        # Verify new schema
        columns = conn.execute("PRAGMA table_info(_schema_version)").fetchall()
        column_names = {col[1] for col in columns}
        assert "checksum" in column_names

        conn.close()


class TestGetAppliedMigrations:
    """Tests for getting applied migrations."""

    def test_empty_database_returns_empty_list(self, tmp_path: Path):
        """Fresh database returns empty list."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)

        applied = get_applied_migrations(conn)
        assert applied == []

        conn.close()

    def test_returns_applied_migrations(self, tmp_path: Path):
        """Returns list of applied migrations."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        _ensure_schema_version_table(conn)

        # Insert some migration records
        conn.execute(
            "INSERT INTO _schema_version VALUES (1, '001_test.sql', '2024-01-01', 'abc')"
        )
        conn.execute(
            "INSERT INTO _schema_version VALUES (2, '002_test.sql', '2024-01-02', 'def')"
        )
        conn.commit()

        applied = get_applied_migrations(conn)
        assert len(applied) == 2
        assert applied[0] == (1, "abc")
        assert applied[1] == (2, "def")

        conn.close()


class TestGetAvailableMigrations:
    """Tests for getting available migrations."""

    def test_returns_sql_files_in_order(self):
        """Returns migration files sorted by version."""
        migrations = get_available_migrations()

        # Should have at least the initial migrations
        assert len(migrations) >= 1

        # Should be sorted by version
        versions = [v for v, _ in migrations]
        assert versions == sorted(versions)

        # All should be .sql files
        for _, path in migrations:
            assert path.suffix == ".sql"


class TestGetPendingMigrations:
    """Tests for getting pending migrations."""

    def test_all_pending_on_fresh_database(self, tmp_path: Path):
        """All migrations pending on fresh database."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        _ensure_schema_version_table(conn)

        pending = get_pending_migrations(conn)
        available = get_available_migrations()

        assert len(pending) == len(available)

        conn.close()

    def test_none_pending_after_all_applied(self, tmp_path: Path):
        """No migrations pending after all applied."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)

        # Run all migrations
        run_migrations(db_path)

        # Reconnect and check
        conn = sqlite3.connect(db_path)
        pending = get_pending_migrations(conn)
        assert len(pending) == 0

        conn.close()


class TestApplyMigration:
    """Tests for applying individual migrations."""

    def test_applies_migration_and_records(self, tmp_path: Path):
        """Applies migration and records in schema version."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        _ensure_schema_version_table(conn)

        # Create a test migration file
        migration_file = tmp_path / "001_test.sql"
        migration_file.write_text("CREATE TABLE test_table (id INTEGER);")

        apply_migration(conn, 1, migration_file)

        # Verify table was created
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'"
        ).fetchall()
        assert len(tables) == 1

        # Verify migration was recorded
        applied = get_applied_migrations(conn)
        assert len(applied) == 1
        assert applied[0][0] == 1

        conn.close()


class TestVerifyMigrations:
    """Tests for migration verification."""

    def test_no_warnings_for_unmodified_migrations(self, tmp_path: Path):
        """No warnings when migrations haven't been modified."""
        db_path = tmp_path / "test.db"

        # Run migrations
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        warnings = verify_migrations(conn)

        # Should have no warnings for unmodified migrations
        assert warnings == []

        conn.close()

    def test_warning_for_modified_migration(self, tmp_path: Path):
        """Warning when migration file has been modified."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        _ensure_schema_version_table(conn)

        # Insert a fake migration record with wrong checksum
        conn.execute(
            "INSERT INTO _schema_version VALUES (1, '001_initial_schema.sql', '2024-01-01', 'wrong_checksum')"
        )
        conn.commit()

        warnings = verify_migrations(conn)

        # Should warn about modified migration
        assert len(warnings) == 1
        assert "modified" in warnings[0].lower()

        conn.close()


class TestRunMigrations:
    """Tests for running all migrations."""

    def test_runs_all_pending_migrations(self, tmp_path: Path):
        """Runs all pending migrations on fresh database."""
        db_path = tmp_path / "test.db"

        count = run_migrations(db_path)

        # Should have run at least the initial migrations
        assert count >= 1

        # Verify schema was created
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}

        # Should have core tables from initial migration
        assert "projects" in table_names
        assert "_schema_version" in table_names

        conn.close()

    def test_idempotent_multiple_runs(self, tmp_path: Path):
        """Running multiple times is safe."""
        db_path = tmp_path / "test.db"

        count1 = run_migrations(db_path)
        count2 = run_migrations(db_path)

        # First run applies migrations
        assert count1 >= 1
        # Second run applies nothing (already applied)
        assert count2 == 0

    def test_creates_database_if_not_exists(self, tmp_path: Path):
        """Creates database file if it doesn't exist."""
        db_path = tmp_path / "new_db.db"
        assert not db_path.exists()

        run_migrations(db_path)

        assert db_path.exists()


class TestGetCurrentVersion:
    """Tests for getting current schema version."""

    def test_returns_zero_for_fresh_database(self, tmp_path: Path):
        """Returns 0 for database with no migrations."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)

        version = get_current_version(conn)
        assert version == 0

        conn.close()

    def test_returns_highest_version(self, tmp_path: Path):
        """Returns highest applied migration version."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        _ensure_schema_version_table(conn)

        # Insert migrations out of order
        conn.execute(
            "INSERT INTO _schema_version VALUES (3, '003_test.sql', '2024-01-03', 'c')"
        )
        conn.execute(
            "INSERT INTO _schema_version VALUES (1, '001_test.sql', '2024-01-01', 'a')"
        )
        conn.execute(
            "INSERT INTO _schema_version VALUES (2, '002_test.sql', '2024-01-02', 'b')"
        )
        conn.commit()

        version = get_current_version(conn)
        assert version == 3

        conn.close()

    def test_returns_version_after_real_migrations(self, tmp_path: Path):
        """Returns correct version after running real migrations."""
        db_path = tmp_path / "test.db"
        run_migrations(db_path)

        conn = sqlite3.connect(db_path)
        version = get_current_version(conn)

        # Should match number of available migrations
        available = get_available_migrations()
        expected_version = max(v for v, _ in available)
        assert version == expected_version

        conn.close()
