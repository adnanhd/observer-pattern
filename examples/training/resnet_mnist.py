"""
ResNet18 MNIST Training with Message Queue Architecture.

This example demonstrates:
- Message queue for component communication (train, validate, metrics)
- Pydantic validation for tensor shapes and device coercion
- Observers for profiling (forward time, backward time, data loading)
- Meters for tracking running averages of metrics
- Event-driven workflow (epoch completion triggers validation, etc.)

Components:
- DataLoader: Loads batches and publishes to "data.batch"
- Trainer: Subscribes to "data.batch", trains, publishes to "train.batch_complete"
- Validator: Subscribes to "train.epoch_complete", validates, publishes to "val.complete"
- MetricsComputer: Subscribes to completion events, computes and logs metrics

Usage:
    python resnet_mnist.py
"""

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from pydantic import BaseModel, Field, field_validator, model_validator
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from callpyback import (
    CallbackObserver,
    ExecutionContext,
    LoggingObserver,
    Message,
    MessageQueue,
    Meter,
    MeterObserver,
    MetricsObserver,
    Observer,
    TimingObserver,
    observe,
)

# =============================================================================
# Pydantic Models for Type Validation
# =============================================================================


class TensorInfo(BaseModel):
    """Validates tensor metadata without serializing the tensor."""

    shape: Tuple[int, ...]
    dtype: str
    device: str

    @classmethod
    def from_tensor(cls, tensor: torch.Tensor) -> "TensorInfo":
        return cls(
            shape=tuple(tensor.shape),
            dtype=str(tensor.dtype),
            device=str(tensor.device),
        )


class BatchData(BaseModel):
    """Validated batch data structure."""

    batch_idx: int
    images: Any  # torch.Tensor
    labels: Any  # torch.Tensor
    batch_size: int
    images_info: Optional[TensorInfo] = None
    labels_info: Optional[TensorInfo] = None

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def validate_tensors(self) -> "BatchData":
        if isinstance(self.images, torch.Tensor):
            self.images_info = TensorInfo.from_tensor(self.images)
            # Validate shape: (batch, channels, height, width)
            if len(self.images.shape) != 4:
                raise ValueError(f"Expected 4D tensor, got {self.images.shape}")

        if isinstance(self.labels, torch.Tensor):
            self.labels_info = TensorInfo.from_tensor(self.labels)

        return self

    def to_device(self, device: torch.device) -> "BatchData":
        """Move tensors to specified device."""
        return BatchData(
            batch_idx=self.batch_idx,
            images=self.images.to(device),
            labels=self.labels.to(device),
            batch_size=self.batch_size,
        )


class TrainStepResult(BaseModel):
    """Result of a single training step."""

    batch_idx: int
    loss: float
    accuracy: float
    batch_size: int
    forward_time: float
    backward_time: float
    data_time: float

    model_config = {"arbitrary_types_allowed": True}


class EpochResult(BaseModel):
    """Result of a complete epoch."""

    epoch: int
    phase: str  # "train" or "val"
    avg_loss: float
    avg_accuracy: float
    total_samples: int
    epoch_time: float


class TrainingConfig(BaseModel):
    """Training configuration with validation."""

    epochs: int = Field(default=5, ge=1, le=100)
    batch_size: int = Field(default=64, ge=1, le=512)
    learning_rate: float = Field(default=0.001, gt=0, lt=1)
    device: str = Field(default="cuda" if torch.cuda.is_available() else "cpu")
    val_every_n_epochs: int = Field(default=1, ge=1)
    log_every_n_batches: int = Field(default=100, ge=1)

    @field_validator("device")
    @classmethod
    def validate_device(cls, v: str) -> str:
        if v == "cuda" and not torch.cuda.is_available():
            return "cpu"
        return v


# =============================================================================
# Custom Observers for Training
# =============================================================================


class ForwardBackwardObserver(Observer):
    """Tracks forward and backward pass timing."""

    def __init__(self):
        self.forward_meter = Meter("forward_time")
        self.backward_meter = Meter("backward_time")
        self.data_meter = Meter("data_time")

    def on_start(self, ctx: ExecutionContext) -> None:
        ctx.metadata["step_start"] = time.perf_counter()

    def on_end(self, ctx: ExecutionContext) -> None:
        if ctx.result and isinstance(ctx.result, dict):
            if "forward_time" in ctx.result:
                self.forward_meter.update(ctx.result["forward_time"])
            if "backward_time" in ctx.result:
                self.backward_meter.update(ctx.result["backward_time"])
            if "data_time" in ctx.result:
                self.data_meter.update(ctx.result["data_time"])

    def reset(self) -> None:
        self.forward_meter.reset()
        self.backward_meter.reset()
        self.data_meter.reset()

    @property
    def stats(self) -> Dict[str, float]:
        return {
            "forward_avg": self.forward_meter.avg,
            "backward_avg": self.backward_meter.avg,
            "data_avg": self.data_meter.avg,
        }

    def summary(self) -> str:
        return (
            f"Forward: {self.forward_meter.avg * 1000:.2f}ms | "
            f"Backward: {self.backward_meter.avg * 1000:.2f}ms | "
            f"Data: {self.data_meter.avg * 1000:.2f}ms"
        )


class GPUMemoryObserver(Observer):
    """Tracks GPU memory usage (extend for your needs)."""

    def __init__(self, device_id: int = 0):
        self.device_id = device_id
        self.peak_memory = 0
        self.current_memory = 0

    def on_start(self, ctx: ExecutionContext) -> None:
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats(self.device_id)

    def on_end(self, ctx: ExecutionContext) -> None:
        if torch.cuda.is_available():
            self.current_memory = torch.cuda.memory_allocated(self.device_id)
            self.peak_memory = max(
                self.peak_memory, torch.cuda.max_memory_allocated(self.device_id)
            )
            ctx.metadata["gpu_memory"] = self.current_memory
            ctx.metadata["gpu_peak_memory"] = self.peak_memory

    @property
    def stats(self) -> Dict[str, float]:
        return {
            "current_mb": self.current_memory / 1024 / 1024,
            "peak_mb": self.peak_memory / 1024 / 1024,
        }


# =============================================================================
# Simple ResNet for MNIST
# =============================================================================


class BasicBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, stride: int = 1):
        super().__init__()
        self.conv1 = nn.Conv2d(
            in_channels, out_channels, 3, stride=stride, padding=1, bias=False
        )
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.conv2 = nn.Conv2d(
            out_channels, out_channels, 3, stride=1, padding=1, bias=False
        )
        self.bn2 = nn.BatchNorm2d(out_channels)

        self.shortcut = nn.Sequential()
        if stride != 1 or in_channels != out_channels:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, 1, stride=stride, bias=False),
                nn.BatchNorm2d(out_channels),
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        out += self.shortcut(x)
        return F.relu(out)


class ResNet18MNIST(nn.Module):
    """ResNet18 adapted for MNIST (1 channel, 28x28)."""

    def __init__(self, num_classes: int = 10):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 64, 3, stride=1, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(64)

        self.layer1 = self._make_layer(64, 64, 2, stride=1)
        self.layer2 = self._make_layer(64, 128, 2, stride=2)
        self.layer3 = self._make_layer(128, 256, 2, stride=2)
        self.layer4 = self._make_layer(256, 512, 2, stride=2)

        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(512, num_classes)

    def _make_layer(
        self, in_channels: int, out_channels: int, num_blocks: int, stride: int
    ) -> nn.Sequential:
        layers = [BasicBlock(in_channels, out_channels, stride)]
        for _ in range(1, num_blocks):
            layers.append(BasicBlock(out_channels, out_channels, 1))
        return nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.layer1(out)
        out = self.layer2(out)
        out = self.layer3(out)
        out = self.layer4(out)
        out = self.avgpool(out)
        out = out.view(out.size(0), -1)
        return self.fc(out)


# =============================================================================
# Training Components with Message Queue
# =============================================================================


class TrainingPipeline:
    """Message-queue based training pipeline."""

    def __init__(self, config: TrainingConfig):
        self.config = config
        self.device = torch.device(config.device)
        self.queue = MessageQueue()

        # Model, optimizer, criterion
        self.model = ResNet18MNIST().to(self.device)
        self.optimizer = torch.optim.Adam(
            self.model.parameters(), lr=config.learning_rate
        )
        self.criterion = nn.CrossEntropyLoss()

        # Meters for tracking
        self.train_loss_meter = Meter("train_loss")
        self.train_acc_meter = Meter("train_acc")
        self.val_loss_meter = Meter("val_loss")
        self.val_acc_meter = Meter("val_acc")

        # Observers
        self.timing_observer = TimingObserver()
        self.fb_observer = ForwardBackwardObserver()
        self.gpu_observer = GPUMemoryObserver()

        # State
        self.current_epoch = 0
        self.global_step = 0

        # Setup message handlers
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Setup message queue handlers."""

        @self.queue.on("train.epoch_start")
        def on_epoch_start(msg: Message):
            epoch = msg.payload["epoch"]
            self.current_epoch = epoch
            self.train_loss_meter.reset()
            self.train_acc_meter.reset()
            self.fb_observer.reset()
            print(f"\n{'=' * 60}")
            print(f"Epoch {epoch + 1}/{self.config.epochs}")
            print(f"{'=' * 60}")

        @self.queue.on("train.batch_complete")
        def on_batch_complete(msg: Message):
            result = TrainStepResult.model_validate(msg.payload)
            self.train_loss_meter.update(result.loss, result.batch_size)
            self.train_acc_meter.update(result.accuracy, result.batch_size)

            if (result.batch_idx + 1) % self.config.log_every_n_batches == 0:
                print(
                    f"  Batch {result.batch_idx + 1}: "
                    f"loss={self.train_loss_meter.avg:.4f}, "
                    f"acc={self.train_acc_meter.avg:.4f}"
                )

        @self.queue.on("train.epoch_complete")
        def on_epoch_complete(msg: Message):
            epoch = msg.payload["epoch"]
            epoch_time = msg.payload["epoch_time"]

            result = EpochResult(
                epoch=epoch,
                phase="train",
                avg_loss=self.train_loss_meter.avg,
                avg_accuracy=self.train_acc_meter.avg,
                total_samples=self.train_loss_meter.count,
                epoch_time=epoch_time,
            )

            print(f"\nTrain Epoch {epoch + 1} Complete:")
            print(f"  Loss: {result.avg_loss:.4f}, Accuracy: {result.avg_accuracy:.4f}")
            print(f"  Time: {result.epoch_time:.2f}s")
            print(f"  Profiling: {self.fb_observer.summary()}")

            # Trigger validation
            if (epoch + 1) % self.config.val_every_n_epochs == 0:
                self.queue.publish("val.start", {"epoch": epoch})

        @self.queue.on("val.start")
        def on_val_start(msg: Message):
            self.val_loss_meter.reset()
            self.val_acc_meter.reset()
            self._run_validation(msg.payload["epoch"])

        @self.queue.on("val.batch_complete")
        def on_val_batch_complete(msg: Message):
            result = msg.payload
            self.val_loss_meter.update(result["loss"], result["batch_size"])
            self.val_acc_meter.update(result["accuracy"], result["batch_size"])

        @self.queue.on("val.complete")
        def on_val_complete(msg: Message):
            result = EpochResult.model_validate(msg.payload)
            print(f"\nValidation Complete:")
            print(f"  Loss: {result.avg_loss:.4f}, Accuracy: {result.avg_accuracy:.4f}")

            # Publish metrics for any listeners
            self.queue.publish(
                "metrics.update",
                {
                    "epoch": result.epoch,
                    "train_loss": self.train_loss_meter.avg,
                    "train_acc": self.train_acc_meter.avg,
                    "val_loss": result.avg_loss,
                    "val_acc": result.avg_accuracy,
                },
            )

    @observe(TimingObserver(), MetricsObserver())
    def _train_step(self, batch: BatchData, data_load_time: float) -> Dict[str, Any]:
        """Single training step with profiling."""
        self.model.train()

        # Move to device with validation
        batch = batch.to_device(self.device)

        # Forward pass
        forward_start = time.perf_counter()
        outputs = self.model(batch.images)
        loss = self.criterion(outputs, batch.labels)
        forward_time = time.perf_counter() - forward_start

        # Backward pass
        backward_start = time.perf_counter()
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        backward_time = time.perf_counter() - backward_start

        # Compute accuracy
        _, predicted = outputs.max(1)
        correct = predicted.eq(batch.labels).sum().item()
        accuracy = correct / batch.batch_size

        return {
            "loss": loss.item(),
            "accuracy": accuracy,
            "forward_time": forward_time,
            "backward_time": backward_time,
            "data_time": data_load_time,
        }

    def _run_validation(self, epoch: int) -> None:
        """Run validation epoch."""
        self.model.eval()
        val_loader = self._get_dataloader(train=False)

        start_time = time.perf_counter()

        with torch.no_grad():
            for batch_idx, (images, labels) in enumerate(val_loader):
                batch = BatchData(
                    batch_idx=batch_idx,
                    images=images,
                    labels=labels,
                    batch_size=len(labels),
                )
                batch = batch.to_device(self.device)

                outputs = self.model(batch.images)
                loss = self.criterion(outputs, batch.labels)

                _, predicted = outputs.max(1)
                correct = predicted.eq(batch.labels).sum().item()
                accuracy = correct / batch.batch_size

                self.queue.publish(
                    "val.batch_complete",
                    {
                        "batch_idx": batch_idx,
                        "loss": loss.item(),
                        "accuracy": accuracy,
                        "batch_size": batch.batch_size,
                    },
                )

        epoch_time = time.perf_counter() - start_time

        result = EpochResult(
            epoch=epoch,
            phase="val",
            avg_loss=self.val_loss_meter.avg,
            avg_accuracy=self.val_acc_meter.avg,
            total_samples=self.val_loss_meter.count,
            epoch_time=epoch_time,
        )

        self.queue.publish("val.complete", result.model_dump())

    def _get_dataloader(self, train: bool = True) -> DataLoader:
        """Get MNIST dataloader."""
        transform = transforms.Compose(
            [transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))]
        )

        dataset = datasets.MNIST(
            root="./data", train=train, download=True, transform=transform
        )

        return DataLoader(
            dataset,
            batch_size=self.config.batch_size,
            shuffle=train,
            num_workers=2,
            pin_memory=True,
        )

    def train(self) -> None:
        """Run full training loop."""
        train_loader = self._get_dataloader(train=True)

        for epoch in range(self.config.epochs):
            self.queue.publish("train.epoch_start", {"epoch": epoch})

            epoch_start = time.perf_counter()
            data_start = time.perf_counter()

            for batch_idx, (images, labels) in enumerate(train_loader):
                data_time = time.perf_counter() - data_start

                # Validate batch with Pydantic
                batch = BatchData(
                    batch_idx=batch_idx,
                    images=images,
                    labels=labels,
                    batch_size=len(labels),
                )

                # Train step
                result = self._train_step(batch, data_time)

                # Update forward/backward observer
                self.fb_observer.forward_meter.update(result["forward_time"])
                self.fb_observer.backward_meter.update(result["backward_time"])
                self.fb_observer.data_meter.update(result["data_time"])

                # Publish result
                step_result = TrainStepResult(
                    batch_idx=batch_idx,
                    loss=result["loss"],
                    accuracy=result["accuracy"],
                    batch_size=batch.batch_size,
                    forward_time=result["forward_time"],
                    backward_time=result["backward_time"],
                    data_time=result["data_time"],
                )

                self.queue.publish("train.batch_complete", step_result.model_dump())

                self.global_step += 1
                data_start = time.perf_counter()

            epoch_time = time.perf_counter() - epoch_start
            self.queue.publish(
                "train.epoch_complete", {"epoch": epoch, "epoch_time": epoch_time}
            )

        print("\n" + "=" * 60)
        print("Training Complete!")
        print("=" * 60)

        if self.gpu_observer.peak_memory > 0:
            print(f"Peak GPU Memory: {self.gpu_observer.stats['peak_mb']:.2f} MB")


def main():
    """Main entry point."""
    # Configuration with validation
    config = TrainingConfig(
        epochs=2,
        batch_size=128,
        learning_rate=0.001,
        val_every_n_epochs=1,
        log_every_n_batches=100,
    )

    print("Training Configuration:")
    print(f"  Epochs: {config.epochs}")
    print(f"  Batch Size: {config.batch_size}")
    print(f"  Learning Rate: {config.learning_rate}")
    print(f"  Device: {config.device}")

    # Create and run pipeline
    pipeline = TrainingPipeline(config)
    pipeline.train()


if __name__ == "__main__":
    main()
