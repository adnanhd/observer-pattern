#!/usr/bin/env python3
"""
ML Model Training - Application Example
Demonstrates ML training workflow with message queue events.
"""

import random
import time
from dataclasses import dataclass
from typing import List, Optional

from callpyback import (
    ExecutionMode,
    Executor,
    MessageQueue,
    Meter,
    MetricsObserver,
    TimingObserver,
    observe,
)


@dataclass
class MLDataset:
    name: str
    train_size: int
    val_size: int
    features: int


@dataclass
class TrainingConfig:
    epochs: int
    batch_size: int
    learning_rate: float
    model_name: str


@dataclass
class EpochResult:
    epoch: int
    train_loss: float
    train_acc: float
    val_loss: Optional[float] = None
    val_acc: Optional[float] = None
    epoch_time: float = 0.0


def main():
    queue = MessageQueue()
    timing = TimingObserver()
    metrics = MetricsObserver()

    # Meters for tracking
    train_loss_meter = Meter("train_loss")
    train_acc_meter = Meter("train_acc")
    val_loss_meter = Meter("val_loss")
    val_acc_meter = Meter("val_acc")

    best_val_acc = 0.0
    epoch_results: List[EpochResult] = []

    # Event handlers
    @queue.on("training.epoch_start")
    def on_epoch_start(msg):
        epoch = msg.payload["epoch"]
        print(f"\n{'=' * 50}")
        print(f"Epoch {epoch + 1}/{msg.payload['total_epochs']}")
        print(f"{'=' * 50}")
        train_loss_meter.reset()
        train_acc_meter.reset()

    @queue.on("training.batch_complete")
    def on_batch_complete(msg):
        batch = msg.payload
        train_loss_meter.update(batch["loss"], batch["batch_size"])
        train_acc_meter.update(batch["accuracy"], batch["batch_size"])

        if batch["batch_idx"] % 10 == 0:
            print(
                f"  Batch {batch['batch_idx']}: "
                f"loss={train_loss_meter.avg:.4f}, acc={train_acc_meter.avg:.4f}"
            )

    @queue.on("training.epoch_complete")
    def on_epoch_complete(msg):
        result = msg.payload
        epoch_results.append(
            EpochResult(
                epoch=result["epoch"],
                train_loss=result["train_loss"],
                train_acc=result["train_acc"],
                val_loss=result.get("val_loss"),
                val_acc=result.get("val_acc"),
                epoch_time=result["epoch_time"],
            )
        )

        print(f"\nEpoch {result['epoch'] + 1} Complete:")
        print(
            f"  Train Loss: {result['train_loss']:.4f}, Acc: {result['train_acc']:.4f}"
        )
        if result.get("val_acc"):
            print(f"  Val Loss: {result['val_loss']:.4f}, Acc: {result['val_acc']:.4f}")

    @queue.on("validation.start")
    def on_val_start(msg):
        val_loss_meter.reset()
        val_acc_meter.reset()
        print("\nRunning validation...")

    @queue.on("validation.batch_complete")
    def on_val_batch(msg):
        batch = msg.payload
        val_loss_meter.update(batch["loss"], batch["batch_size"])
        val_acc_meter.update(batch["accuracy"], batch["batch_size"])

    @queue.on("training.complete")
    def on_training_complete(msg):
        result = msg.payload
        print(f"\n{'=' * 50}")
        print("Training Complete!")
        print(f"{'=' * 50}")
        print(f"Best Validation Accuracy: {result['best_val_acc']:.4f}")
        print(f"Total Time: {result['total_time']:.2f}s")

    # Simulated training functions
    @observe(timing, metrics)
    def train_batch(batch_idx: int, batch_size: int) -> dict:
        """Simulate training one batch."""
        time.sleep(0.001)  # Simulate compute
        loss = random.uniform(0.1, 0.5) * (1 - batch_idx * 0.001)
        accuracy = random.uniform(0.7, 0.95)
        return {"loss": loss, "accuracy": accuracy, "batch_size": batch_size}

    @observe(timing, metrics)
    def validate_batch(batch_idx: int, batch_size: int) -> dict:
        """Simulate validation one batch."""
        time.sleep(0.0005)
        loss = random.uniform(0.15, 0.4)
        accuracy = random.uniform(0.75, 0.92)
        return {"loss": loss, "accuracy": accuracy, "batch_size": batch_size}

    # Configuration
    config = TrainingConfig(
        epochs=3,
        batch_size=32,
        learning_rate=0.001,
        model_name="SimpleNet",
    )

    dataset = MLDataset(
        name="SyntheticData",
        train_size=1000,
        val_size=200,
        features=128,
    )

    num_train_batches = dataset.train_size // config.batch_size
    num_val_batches = dataset.val_size // config.batch_size

    print(f"Training {config.model_name}")
    print(f"Dataset: {dataset.name}")
    print(f"Train batches: {num_train_batches}, Val batches: {num_val_batches}")

    start_time = time.perf_counter()

    # Training loop
    for epoch in range(config.epochs):
        epoch_start = time.perf_counter()

        queue.publish(
            "training.epoch_start",
            {"epoch": epoch, "total_epochs": config.epochs},
        )

        # Train batches
        for batch_idx in range(num_train_batches):
            result = train_batch(batch_idx, config.batch_size)
            queue.publish(
                "training.batch_complete",
                {"batch_idx": batch_idx, **result},
            )

        # Validation
        queue.publish("validation.start", {"epoch": epoch})

        for batch_idx in range(num_val_batches):
            result = validate_batch(batch_idx, config.batch_size)
            queue.publish(
                "validation.batch_complete",
                {"batch_idx": batch_idx, **result},
            )

        epoch_time = time.perf_counter() - epoch_start

        # Track best
        if val_acc_meter.avg > best_val_acc:
            best_val_acc = val_acc_meter.avg

        queue.publish(
            "training.epoch_complete",
            {
                "epoch": epoch,
                "train_loss": train_loss_meter.avg,
                "train_acc": train_acc_meter.avg,
                "val_loss": val_loss_meter.avg,
                "val_acc": val_acc_meter.avg,
                "epoch_time": epoch_time,
            },
        )

    total_time = time.perf_counter() - start_time

    queue.publish(
        "training.complete",
        {"best_val_acc": best_val_acc, "total_time": total_time},
    )

    time.sleep(0.1)

    print(f"\nTiming stats: {timing.stats}")
    print(f"Metrics stats: {metrics.stats}")


if __name__ == "__main__":
    main()
