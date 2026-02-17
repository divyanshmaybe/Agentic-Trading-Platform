#!/usr/bin/env python3
"""
Kafka Studio - A Streamlit-based interface to explore Kafka topics, messages, and consumer groups.
Similar to Prisma Studio for Kafka.

Usage:
    streamlit run kafkaStudio.py

Requirements:
    pip install streamlit kafka-python
"""

import streamlit as st
from kafka import KafkaAdminClient, KafkaConsumer
import json
import os
from typing import List, Dict, Any


def get_kafka_admin_client() -> KafkaAdminClient:
    """Create and return Kafka admin client."""
    bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    try:
        return KafkaAdminClient(bootstrap_servers=bootstrap_servers)
    except Exception as e:
        st.error(f"Failed to connect to Kafka: {e}")
        return None


def get_topics(admin_client: KafkaAdminClient) -> List[str]:
    """Get list of all topics."""
    try:
        return admin_client.list_topics()
    except Exception as e:
        st.error(f"Failed to list topics: {e}")
        return []


def get_consumer_groups(admin_client: KafkaAdminClient) -> List[str]:
    """Get list of consumer groups."""
    try:
        return admin_client.list_consumer_groups()
    except Exception as e:
        st.error(f"Failed to list consumer groups: {e}")
        return []


def get_topic_messages(topic: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent messages from a topic."""
    bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    messages = []
    try:
        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            auto_offset_reset='earliest',
            enable_auto_commit=False,
            consumer_timeout_ms=1000,
            value_deserializer=lambda x: json.loads(x.decode('utf-8')) if x else None
        )
        for message in consumer:
            if len(messages) >= limit:
                break
            msg_data = {
                'topic': message.topic,
                'partition': message.partition,
                'offset': message.offset,
                'key': message.key.decode('utf-8') if message.key else None,
                'value': message.value,
                'timestamp': message.timestamp,
                'headers': {k: v.decode('utf-8') if isinstance(v, bytes) else v for k, v in (message.headers or [])}
            }
            messages.append(msg_data)
        consumer.close()
    except Exception as e:
        st.error(f"Failed to read messages from topic {topic}: {e}")
    return messages


def get_consumer_group_details(admin_client: KafkaAdminClient, group_id: str) -> Dict[str, Any]:
    """Get details of a consumer group."""
    try:
        group_description = admin_client.describe_consumer_groups([group_id])[0]
        return {
            'group_id': group_description.group_id,
            'state': group_description.state,
            'protocol_type': group_description.protocol_type,
            'protocol': group_description.protocol,
            'members': [
                {
                    'member_id': member.member_id,
                    'client_id': member.client_id,
                    'host': member.host,
                    'assignment': member.assignment.topic_partitions if member.assignment else []
                }
                for member in group_description.members
            ]
        }
    except Exception as e:
        st.error(f"Failed to get details for consumer group {group_id}: {e}")
        return {}


def main():
    st.set_page_config(page_title="Kafka Studio", page_icon="📊", layout="wide")
    st.title("📊 Kafka Studio")
    st.markdown("Explore Kafka topics, messages, and consumer groups")

    admin_client = get_kafka_admin_client()
    if not admin_client:
        st.stop()

    # Sidebar for navigation
    st.sidebar.header("Navigation")
    view = st.sidebar.radio("Select View", ["Topics", "Consumer Groups"])

    if view == "Topics":
        st.header("📋 Topics")

        topics = get_topics(admin_client)
        if not topics:
            st.info("No topics found")
        else:
            selected_topic = st.selectbox("Select Topic", topics)

            if selected_topic:
                st.subheader(f"Topic: {selected_topic}")

                col1, col2, col3 = st.columns(3)
                with col1:
                    limit = st.slider("Number of messages to show", 10, 500, 1000)
                with col2:
                    if st.button("Refresh Messages"):
                        st.rerun()
                with col3:
                    messages = get_topic_messages(selected_topic, limit)
                    if messages:
                        json_data = json.dumps(messages, indent=2)
                        st.download_button(
                            label="Export as JSON",
                            data=json_data,
                            file_name=f"{selected_topic}_messages.json",
                            mime="application/json"
                        )

                if messages:
                    st.subheader("Messages")
                    for msg in messages:
                        with st.expander(f"Offset {msg['offset']} - {msg['timestamp']}"):
                            st.json(msg)
                else:
                    st.info("No messages found in this topic")

    elif view == "Consumer Groups":
        st.header("👥 Consumer Groups")

        consumer_groups = get_consumer_groups(admin_client)
        if not consumer_groups:
            st.info("No consumer groups found")
        else:
            selected_group = st.selectbox("Select Consumer Group", consumer_groups)

            if selected_group:
                st.subheader(f"Consumer Group: {selected_group}")

                details = get_consumer_group_details(admin_client, selected_group)
                if details:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.json(details)
                    with col2:
                        json_data = json.dumps(details, indent=2)
                        st.download_button(
                            label="Export as JSON",
                            data=json_data,
                            file_name=f"{selected_group}_details.json",
                            mime="application/json"
                        )
                else:
                    st.info("No details available")

    admin_client.close()


if __name__ == "__main__":
    main()