#!/usr/bin/env python3
"""
Real-time Data Processing Pipeline - Application Example
Demonstrates streaming data processing with multiple pipeline stages.
"""

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from callpyback import ExecutionMode, emit_event, on_event, execution_session


@dataclass
class StreamRecord:
    id: str
    timestamp: float
    source: str
    event_type: str
    data: Dict[str, Any]
    processing_stage: str = "raw"
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


# Pipeline stage event handlers
@on_event("pipeline.stage.*.processing")
def handle_stage_processing(message):
    """Track processing at each pipeline stage"""
    stage = message.topic.split(".")[2]
    record_id = message.payload.get("record_id", "unknown")
    batch_size = message.payload.get("batch_size", 1)
    print(f"🔄 {stage} stage processing record {record_id} (batch: {batch_size})")


@on_event("pipeline.stage.*.completed")
def handle_stage_completed(message):
    """Track stage completion"""
    stage = message.topic.split(".")[2]
    payload = message.payload
    records_processed = payload.get("records_processed", 0)
    processing_time = payload.get("processing_time", 0)
    throughput = records_processed / processing_time if processing_time > 0 else 0
    print(
        f"✅ {stage} stage: {records_processed} records in {processing_time:.3f}s "
        f"({throughput:.1f} records/sec)"
    )


@on_event("pipeline.anomaly.detected")
def handle_anomaly_detection(message):
    """Handle anomaly alerts"""
    payload = message.payload
    anomaly_type = payload.get("anomaly_type", "unknown")
    record_id = payload.get("record_id", "unknown")
    severity = payload.get("severity", "medium")
    print(f"🚨 ANOMALY DETECTED ({severity}): {anomaly_type} in record {record_id}")


@on_event("pipeline.throughput.alert")
def handle_throughput_alert(message):
    """Handle throughput performance alerts"""
    payload = message.payload
    stage = payload.get("stage", "unknown")
    current_rate = payload.get("current_rate", 0)
    expected_rate = payload.get("expected_rate", 0)
    print(
        f"⚠️ THROUGHPUT ALERT: {stage} stage at {current_rate:.1f} records/sec "
        f"(expected: {expected_rate:.1f})"
    )


class DataIngestionStage:
    """First stage: Data ingestion and initial validation"""

    def __init__(self, stage_id: str):
        self.stage_id = stage_id
        self.processed_count = 0

    def process_batch(self, records: List[StreamRecord]) -> List[StreamRecord]:
        """Process a batch of raw records"""
        start_time = time.time()

        emit_event(
            "pipeline.stage.ingestion.processing",
            {
                "stage_id": self.stage_id,
                "batch_size": len(records),
                "record_id": records[0].id if records else "empty",
            },
        )

        processed_records = []

        for record in records:
            # Simulate ingestion processing time
            time.sleep(random.uniform(0.001, 0.005))

            # Basic validation
            if not record.data or not record.event_type:
                # Skip invalid records
                continue

            # Add ingestion metadata
            record.metadata["ingested_at"] = time.time()
            record.metadata["ingestion_stage"] = self.stage_id
            record.processing_stage = "ingested"

            # Data enrichment - add computed fields
            if record.event_type == "user_action":
                record.data["session_duration"] = random.uniform(30, 3600)
                record.data["user_agent_parsed"] = f"Browser_{random.randint(1, 5)}"
            elif record.event_type == "sensor_reading":
                record.data["temperature_fahrenheit"] = (
                    record.data.get("temperature_celsius", 20) * 9 / 5 + 32
                )
                record.data["anomaly_score"] = random.uniform(0, 1)

            processed_records.append(record)
            self.processed_count += 1

        processing_time = time.time() - start_time

        emit_event(
            "pipeline.stage.ingestion.completed",
            {
                "stage_id": self.stage_id,
                "records_processed": len(processed_records),
                "records_discarded": len(records) - len(processed_records),
                "processing_time": processing_time,
            },
        )

        return processed_records


class DataTransformationStage:
    """Second stage: Data transformation and normalization"""

    def __init__(self, stage_id: str):
        self.stage_id = stage_id
        self.processed_count = 0

    def process_batch(self, records: List[StreamRecord]) -> List[StreamRecord]:
        """Transform and normalize data"""
        start_time = time.time()

        emit_event(
            "pipeline.stage.transformation.processing",
            {
                "stage_id": self.stage_id,
                "batch_size": len(records),
                "record_id": records[0].id if records else "empty",
            },
        )

        transformed_records = []

        for record in records:
            # Simulate transformation processing
            time.sleep(random.uniform(0.002, 0.008))

            # Data transformation based on event type
            if record.event_type == "user_action":
                # Normalize user actions
                action = record.data.get("action", "").lower()
                record.data["normalized_action"] = action
                record.data["action_category"] = self._categorize_action(action)
                record.data["value_score"] = self._calculate_action_value(action)

            elif record.event_type == "sensor_reading":
                # Normalize sensor data
                sensor_type = record.data.get("sensor_type", "unknown")
                raw_value = record.data.get("value", 0)
                record.data["normalized_value"] = self._normalize_sensor_value(
                    sensor_type, raw_value
                )
                record.data["quality_score"] = random.uniform(0.8, 1.0)

            elif record.event_type == "financial_transaction":
                # Normalize financial data
                amount = record.data.get("amount", 0)
                currency = record.data.get("currency", "USD")
                record.data["amount_usd"] = self._convert_to_usd(amount, currency)
                record.data["risk_score"] = self._calculate_risk_score(amount, currency)

            # Add transformation metadata
            record.metadata["transformed_at"] = time.time()
            record.metadata["transformation_stage"] = self.stage_id
            record.processing_stage = "transformed"

            transformed_records.append(record)
            self.processed_count += 1

        processing_time = time.time() - start_time

        emit_event(
            "pipeline.stage.transformation.completed",
            {
                "stage_id": self.stage_id,
                "records_processed": len(transformed_records),
                "processing_time": processing_time,
            },
        )

        return transformed_records

    def _categorize_action(self, action: str) -> str:
        """Categorize user actions"""
        if action in ["login", "logout", "register"]:
            return "authentication"
        elif action in ["view", "browse", "search"]:
            return "navigation"
        elif action in ["purchase", "add_to_cart", "checkout"]:
            return "commerce"
        else:
            return "other"

    def _calculate_action_value(self, action: str) -> float:
        """Calculate business value of action"""
        values = {
            "purchase": 10.0,
            "add_to_cart": 3.0,
            "register": 5.0,
            "view": 1.0,
            "search": 2.0,
        }
        return values.get(action, 0.5)

    def _normalize_sensor_value(self, sensor_type: str, value: float) -> float:
        """Normalize sensor values to 0-1 range"""
        ranges = {
            "temperature": (-50, 150),
            "humidity": (0, 100),
            "pressure": (800, 1200),
            "vibration": (0, 10),
        }

        min_val, max_val = ranges.get(sensor_type, (0, 100))
        return max(0, min(1, (value - min_val) / (max_val - min_val)))

    def _convert_to_usd(self, amount: float, currency: str) -> float:
        """Convert currency to USD (simplified)"""
        rates = {"EUR": 1.1, "GBP": 1.3, "JPY": 0.007, "USD": 1.0}
        return amount * rates.get(currency, 1.0)

    def _calculate_risk_score(self, amount: float, currency: str) -> float:
        """Calculate transaction risk score"""
        base_risk = min(1.0, amount / 10000.0)  # Higher amounts = higher risk
        currency_risk = 0.1 if currency != "USD" else 0.0
        return min(1.0, base_risk + currency_risk + random.uniform(0, 0.2))


class AnomalyDetectionStage:
    """Third stage: Anomaly detection and alerting"""

    def __init__(self, stage_id: str):
        self.stage_id = stage_id
        self.processed_count = 0
        self.anomaly_thresholds = {
            "user_action": {"value_score": 8.0, "session_duration": 7200},
            "sensor_reading": {"anomaly_score": 0.8, "normalized_value": 0.9},
            "financial_transaction": {"amount_usd": 5000, "risk_score": 0.7},
        }

    def process_batch(self, records: List[StreamRecord]) -> List[StreamRecord]:
        """Detect anomalies in processed data"""
        start_time = time.time()

        emit_event(
            "pipeline.stage.anomaly.processing",
            {
                "stage_id": self.stage_id,
                "batch_size": len(records),
                "record_id": records[0].id if records else "empty",
            },
        )

        analyzed_records = []
        anomalies_detected = 0

        for record in records:
            # Simulate anomaly detection processing
            time.sleep(random.uniform(0.003, 0.010))

            # Detect anomalies based on event type
            anomalies = self._detect_anomalies(record)

            # Add anomaly information to record
            record.metadata["anomalies"] = anomalies
            record.metadata["anomaly_count"] = len(anomalies)
            record.metadata["analyzed_at"] = time.time()
            record.processing_stage = "analyzed"

            # Emit anomaly alerts
            for anomaly in anomalies:
                emit_event(
                    "pipeline.anomaly.detected",
                    {
                        "record_id": record.id,
                        "anomaly_type": anomaly["type"],
                        "severity": anomaly["severity"],
                        "value": anomaly["value"],
                        "threshold": anomaly["threshold"],
                        "event_type": record.event_type,
                    },
                )
                anomalies_detected += 1

            analyzed_records.append(record)
            self.processed_count += 1

        processing_time = time.time() - start_time

        emit_event(
            "pipeline.stage.anomaly.completed",
            {
                "stage_id": self.stage_id,
                "records_processed": len(analyzed_records),
                "anomalies_detected": anomalies_detected,
                "processing_time": processing_time,
            },
        )

        return analyzed_records

    def _detect_anomalies(self, record: StreamRecord) -> List[Dict[str, Any]]:
        """Detect anomalies in a single record"""
        anomalies = []
        event_type = record.event_type
        thresholds = self.anomaly_thresholds.get(event_type, {})

        for field, threshold in thresholds.items():
            value = record.data.get(field, 0)

            if isinstance(value, (int, float)) and value > threshold:
                severity = "high" if value > threshold * 1.5 else "medium"
                anomalies.append(
                    {
                        "type": f"high_{field}",
                        "field": field,
                        "value": value,
                        "threshold": threshold,
                        "severity": severity,
                    }
                )

        # Additional pattern-based anomaly detection
        if event_type == "user_action":
            # Detect unusual action sequences
            if (
                record.data.get("action") == "purchase"
                and record.data.get("session_duration", 0) < 30
            ):
                anomalies.append(
                    {
                        "type": "suspicious_quick_purchase",
                        "field": "session_duration",
                        "value": record.data.get("session_duration"),
                        "threshold": 30,
                        "severity": "high",
                    }
                )

        return anomalies


class DataStorageStage:
    """Final stage: Data storage and indexing"""

    def __init__(self, stage_id: str):
        self.stage_id = stage_id
        self.processed_count = 0
        self.storage_systems = ["primary_db", "analytics_db", "search_index"]

    def process_batch(self, records: List[StreamRecord]) -> List[StreamRecord]:
        """Store processed data in various systems"""
        start_time = time.time()

        emit_event(
            "pipeline.stage.storage.processing",
            {
                "stage_id": self.stage_id,
                "batch_size": len(records),
                "record_id": records[0].id if records else "empty",
            },
        )

        stored_records = []
        storage_operations = 0

        for record in records:
            # Simulate storage operations
            time.sleep(random.uniform(0.005, 0.015))

            # Store in different systems based on data characteristics
            storage_locations = []

            # Primary database (always)
            storage_locations.append("primary_db")
            storage_operations += 1

            # Analytics database (for certain event types)
            if record.event_type in ["user_action", "financial_transaction"]:
                storage_locations.append("analytics_db")
                storage_operations += 1

            # Search index (for records with anomalies or high value)
            if (
                record.metadata.get("anomaly_count", 0) > 0
                or record.data.get("value_score", 0) > 5.0
            ):
                storage_locations.append("search_index")
                storage_operations += 1

            # Add storage metadata
            record.metadata["stored_at"] = time.time()
            record.metadata["storage_locations"] = storage_locations
            record.metadata["storage_stage"] = self.stage_id
            record.processing_stage = "stored"

            stored_records.append(record)
            self.processed_count += 1

        processing_time = time.time() - start_time

        emit_event(
            "pipeline.stage.storage.completed",
            {
                "stage_id": self.stage_id,
                "records_processed": len(stored_records),
                "storage_operations": storage_operations,
                "processing_time": processing_time,
            },
        )

        return stored_records


def generate_stream_data(batch_size: int, source: str) -> List[StreamRecord]:
    """Generate simulated streaming data"""
    records = []

    event_types = ["user_action", "sensor_reading", "financial_transaction"]

    for i in range(batch_size):
        event_type = random.choice(event_types)
        record_id = f"{source}_{int(time.time() * 1000) % 100000}_{i:03d}"

        # Generate event-specific data
        if event_type == "user_action":
            data = {
                "user_id": f"user_{random.randint(1000, 9999)}",
                "action": random.choice(
                    ["view", "purchase", "login", "search", "add_to_cart"]
                ),
                "page": f"/page_{random.randint(1, 100)}",
                "user_agent": "Mozilla/5.0 Chrome/91.0",
                "ip_address": f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}",
            }
        elif event_type == "sensor_reading":
            data = {
                "sensor_id": f"sensor_{random.randint(100, 999)}",
                "sensor_type": random.choice(
                    ["temperature", "humidity", "pressure", "vibration"]
                ),
                "value": random.uniform(0, 100),
                "temperature_celsius": random.uniform(-20, 50),
                "location": f"building_{random.randint(1, 10)}_floor_{random.randint(1, 5)}",
            }
        else:  # financial_transaction
            data = {
                "transaction_id": f"txn_{random.randint(100000, 999999)}",
                "user_id": f"user_{random.randint(1000, 9999)}",
                "amount": round(random.uniform(10, 2000), 2),
                "currency": random.choice(["USD", "EUR", "GBP", "JPY"]),
                "merchant": f"merchant_{random.randint(1, 100)}",
                "card_type": random.choice(["visa", "mastercard", "amex"]),
            }

        record = StreamRecord(
            id=record_id,
            timestamp=time.time(),
            source=source,
            event_type=event_type,
            data=data,
        )
        records.append(record)

    return records


def run_pipeline_stage(stage, records):
    """Helper function to run a pipeline stage"""
    return stage.process_batch(records)


def main():
    """Demo real-time data processing pipeline"""
    print("🚰 Real-time Data Processing Pipeline")
    print("=" * 50)

    # Create pipeline stages
    ingestion_stage = DataIngestionStage("ingestion_001")
    transformation_stage = DataTransformationStage("transform_001")
    anomaly_stage = AnomalyDetectionStage("anomaly_001")
    storage_stage = DataStorageStage("storage_001")

    stages = [ingestion_stage, transformation_stage, anomaly_stage, storage_stage]
    stage_names = ["Ingestion", "Transformation", "Anomaly Detection", "Storage"]

    with execution_session() as manager:
        # Configure for I/O intensive stream processing
        manager.configure().max_threads(8).execution_mode(ExecutionMode.THREAD).apply()

        print("🌊 Generating streaming data batches...")

        # Generate multiple data streams
        data_sources = ["web_app", "mobile_app", "iot_sensors", "payment_gateway"]
        batch_size = 25

        # Generate data batches from different sources
        data_batches = manager.map_parallel(
            lambda source: generate_stream_data(batch_size, source), data_sources
        )

        # Flatten all batches into single stream
        all_records = []
        for batch in data_batches:
            all_records.extend(batch)

        print(
            f"📊 Generated {len(all_records)} records from {len(data_sources)} sources"
        )

        # Process through pipeline stages sequentially
        print(f"\n🔄 Processing through {len(stages)} pipeline stages...")

        current_records = all_records
        pipeline_start = time.time()

        for i, (stage, stage_name) in enumerate(zip(stages, stage_names)):
            print(f"\n   Stage {i+1}: {stage_name}")

            # Split records into smaller batches for parallel processing within stage
            batch_size = 15
            record_batches = [
                current_records[j : j + batch_size]
                for j in range(0, len(current_records), batch_size)
            ]

            # Process batches in parallel within each stage
            stage_start = time.time()
            processed_batches = manager.map_parallel(
                lambda batch: run_pipeline_stage(stage, batch), record_batches
            )
            stage_duration = time.time() - stage_start

            # Flatten processed batches
            current_records = []
            for batch in processed_batches:
                current_records.extend(batch)

            print(
                f"      Processed {len(current_records)} records in {stage_duration:.3f}s"
            )

            # Check for throughput issues
            expected_throughput = 100  # records per second
            actual_throughput = len(current_records) / stage_duration

            if actual_throughput < expected_throughput * 0.8:
                emit_event(
                    "pipeline.throughput.alert",
                    {
                        "stage": stage_name.lower(),
                        "current_rate": actual_throughput,
                        "expected_rate": expected_throughput,
                    },
                )

        total_pipeline_time = time.time() - pipeline_start

        # Pipeline completion summary
        print(f"\n📈 Pipeline Processing Summary:")
        print(f"   Input records: {len(all_records)}")
        print(f"   Output records: {len(current_records)}")
        print(f"   Total pipeline time: {total_pipeline_time:.3f}s")
        print(
            f"   Overall throughput: {len(current_records)/total_pipeline_time:.1f} records/sec"
        )

        # Show stage-specific statistics
        print(f"\n📊 Stage Statistics:")
        for stage, stage_name in zip(stages, stage_names):
            processed = getattr(stage, "processed_count", 0)
            print(f"   {stage_name}: {processed} records processed")

        # Count anomalies detected
        total_anomalies = sum(
            record.metadata.get("anomaly_count", 0) for record in current_records
        )
        records_with_anomalies = sum(
            1
            for record in current_records
            if record.metadata.get("anomaly_count", 0) > 0
        )

        print(f"\n🚨 Anomaly Detection Results:")
        print(f"   Total anomalies detected: {total_anomalies}")
        print(
            f"   Records with anomalies: {records_with_anomalies}/{len(current_records)}"
        )
        print(
            f"   Anomaly rate: {(records_with_anomalies/len(current_records)*100):.1f}%"
        )

        # Show system performance
        metrics = manager.get_metrics()
        print(f"\n🖥️ System Performance:")
        print(f"   Total tasks: {metrics['tasks_completed']}")
        print(f"   Pipeline events: {metrics['events_published']}")
        print(f"   System health: {manager.health_check()}")

        print(f"\n🎯 Pipeline demonstrates:")
        print(f"   ✅ Multi-stage stream processing")
        print(f"   ✅ Parallel processing within stages")
        print(f"   ✅ Real-time anomaly detection")
        print(f"   ✅ Throughput monitoring and alerting")
        print(f"   ✅ Data lineage tracking")


if __name__ == "__main__":
    main()
