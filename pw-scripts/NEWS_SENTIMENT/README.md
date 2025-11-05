# News Sentiment Based Trading - Pathway

This module converts the Colab notebook into a Pathway pipeline that:
- Defines sector/topic news streams
- Pulls top-k recent articles from NewsAPI
- Classifies article sentiment with FinBERT (transformers)
- Aggregates to per-stream composite signals (-1/0/1)
- Provides a demo script

## Setup

1) Install deps into your environment:
```
pip install pathway[xpack-llm] transformers torch requests python-dotenv
```

2) Set environment variable for NewsAPI:
```
export NEWS_ORG_API_KEY=your_newsapi_key
```

## Run Demo

```
python NEWS_SENTIMENT/news_sentiment_demo.py
```

This will:
- Create 3 example streams
- Fetch top-3 recent articles per stream
- Run sentiment classification
- Aggregate and print composite signals

## Integrating in Streaming Mode

You can supply streams from HTTP/Kafka/CSV by producing a table with schema:
```
class StreamSchema(pw.Schema):
    stream: str
    query: str
    top_k: int
```
Then call `build_pipeline(streams_table, api_key, top_k_default)` and route the resulting `signals` table to a writer connector (e.g., `pw.io.jsonlines.write`).

## Notes

- FinBERT loads lazily and is cached in-process.
- For GPU, torch will use CUDA if available.
- This demo focuses on news->sentiment->aggregate signals. You can extend it to call an LLM for textual trading guidance if desired.


