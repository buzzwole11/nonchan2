-- Runs once when the database volume is first created.
-- The test suite uses its own database so a test run never touches development data;
-- test_migrations.py additionally creates and drops `papermatch_test_migrations`.
CREATE DATABASE papermatch_test OWNER papermatch;
