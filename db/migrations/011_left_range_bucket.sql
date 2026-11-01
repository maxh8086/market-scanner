-- Add 'left_range' to bucket constraint for left_range change detection.
-- When a stock leaves the range, we create a snapshot row with its last known values
-- to hang the snapshot_changes row on. The bucket is set to 'left_range'.

ALTER TABLE stock_snapshots DROP CONSTRAINT stock_snapshots_bucket_check;
ALTER TABLE stock_snapshots ADD CONSTRAINT stock_snapshots_bucket_check
  CHECK (bucket IN ('at_ath','within_5','within_10','within_26','left_range'));
