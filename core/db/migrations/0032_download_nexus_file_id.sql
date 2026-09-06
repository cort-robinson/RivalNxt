-- Preserve exact Nexus file identity independently of archive names and versions.
ALTER TABLE local_downloads ADD COLUMN nexus_file_id INTEGER;
ALTER TABLE local_downloads ADD COLUMN nexus_file_fingerprint TEXT;
CREATE INDEX IF NOT EXISTS idx_local_downloads_nexus_file ON local_downloads(mod_id, nexus_file_id);
