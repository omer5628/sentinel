CREATE TABLE IF NOT EXISTS feature_log (
    event_id UUID PRIMARY KEY,
    image_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_image BYTEA,
    vector JSONB NOT NULL,
    label VARCHAR(50),
    model_version VARCHAR(20) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feature_log_image_id
    ON feature_log (image_id);

CREATE INDEX IF NOT EXISTS idx_feature_log_timestamp
    ON feature_log (timestamp);

CREATE INDEX IF NOT EXISTS idx_feature_log_unlabeled
    ON feature_log (timestamp)
    WHERE label IS NULL;

CREATE TABLE IF NOT EXISTS batch_predictions (
    prediction_id UUID PRIMARY KEY,
    image_id VARCHAR(255) NOT NULL,
    campaign_name VARCHAR(100) NOT NULL,
    image_path TEXT NOT NULL,
    predicted_class INTEGER NOT NULL,
    predicted_label VARCHAR(50) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    model_version VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_batch_predictions_campaign
    ON batch_predictions (campaign_name);

CREATE INDEX IF NOT EXISTS idx_batch_predictions_image_id
    ON batch_predictions (image_id);

CREATE INDEX IF NOT EXISTS idx_batch_predictions_created_at
    ON batch_predictions (created_at);