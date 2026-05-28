const { Kafka, logLevel } = require('kafkajs');
const Redis = require('ioredis');

const kafkaBrokers = (process.env.KAFKA_BOOTSTRAP_SERVERS || 'kafka:9092').split(',');
const clientId = process.env.KAFKA_CLIENT_ID || 'frontend-notifications';
const groupId = process.env.KAFKA_GROUP_ID || 'frontend-notifications-group';
const topic = process.env.NOTIFICATION_TOPIC || 'nse_filings_trading_signal';

const redisUrl = process.env.REDIS_URL || 'redis://redis:6379';
const redisChannel = process.env.NOTIFICATION_REDIS_CHANNEL || 'notifications:new';

const kafka = new Kafka({
  clientId,
  brokers: kafkaBrokers,
  logLevel: logLevel.INFO,
  retry: {
    // aggressive but bounded retry/backoff for metadata/connection issues
    retries: 30,
    initialRetryTime: 1000,
    factor: 1.5,
  },
});

const redis = new Redis(redisUrl);

async function waitForTopic(admin, maxAttempts = 20) {
  let attempt = 0;
  let delay = 1000;
  while (attempt < maxAttempts) {
    try {
      const metadata = await admin.fetchTopicMetadata({ topics: [topic] });
      // fetchTopicMetadata returns metadata.topics array
      if (metadata && metadata.topics && metadata.topics.length > 0) {
        const t = metadata.topics[0];
        if (!t.errorCode || t.errorCode === 0) {
          return true;
        }
      }
      throw new Error('Topic metadata incomplete');
    } catch (err) {
      // Treat UNKNOWN_TOPIC_OR_PARTITION as transient and retry
      const msg = String(err.message || err);
      console.error(`[Kafka] fetchTopicMetadata failed (attempt ${attempt + 1}/${maxAttempts}):`, msg);
      attempt += 1;
      await new Promise((res) => setTimeout(res, delay));
      delay = Math.min(30000, Math.floor(delay * 1.5));
    }
  }
  return false;
}

async function run() {
  const admin = kafka.admin();
  const consumer = kafka.consumer({ groupId });

  try {
    await admin.connect();
    console.log('[Kafka] Admin connected. Waiting for topic metadata...');
    const ok = await waitForTopic(admin, 40);
    if (!ok) {
      console.warn('[Kafka] Topic not visible after retries; continuing and attempting subscribe');
    }

    await consumer.connect();
    console.log('[Kafka] Consumer connected, subscribing to topic', topic);
    await consumer.subscribe({ topic, fromBeginning: false });

    await consumer.run({
      eachMessage: async ({ topic, partition, message }) => {
        try {
          const value = message.value ? message.value.toString() : null;
          if (!value) return;
          let payload = value;
          try { payload = JSON.parse(value); } catch (e) { /* keep raw */ }
          // Publish to Redis channel for frontend SSE
          const out = typeof payload === 'string' ? payload : JSON.stringify(payload);
          await redis.publish(redisChannel, out);
          console.log('[Kafka] Published message to Redis', redisChannel, { topic, partition });
        } catch (err) {
          console.error('[Kafka] Error processing message:', err && err.stack ? err.stack : err);
        }
      }
    });

    // graceful shutdown
    const shutdown = async () => {
      console.log('[Kafka] Shutting down consumer');
      try { await consumer.disconnect(); } catch (e) { /* ignore */ }
      try { await admin.disconnect(); } catch (e) { /* ignore */ }
      try { await redis.quit(); } catch (e) { /* ignore */ }
      process.exit(0);
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
  } catch (err) {
    console.error('[Kafka] Fatal error in notification_server:', err && err.stack ? err.stack : err);
    try { await consumer.disconnect(); } catch (e) { /* ignore */ }
    try { await admin.disconnect(); } catch (e) { /* ignore */ }
    // Rethrow so outer restart loop can restart the node process
    throw err;
  }
}

// Run with top-level retry so transient errors don't crash the process immediately
(async () => {
  let attempt = 0;
  while (true) {
    try {
      await run();
      console.log('[Main] run() completed normally — exiting');
      break;
    } catch (err) {
      attempt += 1;
      console.error(`[Main] run() failed (attempt ${attempt}):`, err && err.message ? err.message : err);
      const backoff = Math.min(30000, 1000 * Math.pow(1.5, Math.min(attempt, 10)));
      console.log(`[Main] retrying in ${backoff}ms`);
      await new Promise((res) => setTimeout(res, backoff));
    }
  }
})();
