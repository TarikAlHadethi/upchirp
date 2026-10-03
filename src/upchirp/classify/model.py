"""A small CNN over one range-Doppler patch (person, car or drone-like), and its training.

Deliberately small: two 3x3 convolutions and a dense layer, like the smallest
network in the RAD-DAR paper, so it runs on the edge box's CPU in microseconds.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
import torch
from torch import nn

from upchirp.classify.patches import CLASSES


class PatchCNN(nn.Module):
    def __init__(self, height: int, width: int, n_classes: int = len(CLASSES)) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(),
        )
        self.head = nn.Sequential(
            nn.Flatten(), nn.Dropout(0.3),
            nn.Linear(32 * height * width, 64), nn.ReLU(),
            nn.Linear(64, n_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.head(self.features(x.unsqueeze(1)))
        return out


@dataclass
class Split:
    train: npt.NDArray[np.bool_]
    val: npt.NDArray[np.bool_]
    test: npt.NDArray[np.bool_]
    test_recordings: list[str] = field(default_factory=list)


def split_by_recording(y: npt.NDArray[np.int64], rec: npt.NDArray[np.str_], seed: int,
                       test_frac: float = 0.2, val_frac: float = 0.15) -> Split:
    """Whole recordings go to one side only; samples within a recording are near-copies."""
    rng = np.random.default_rng(seed)
    test = np.zeros(len(y), bool)
    val = np.zeros(len(y), bool)
    held_out: list[str] = []
    for c in range(len(CLASSES)):
        recs = sorted(set(rec[y == c]))
        rng.shuffle(recs)
        n_test = max(1, round(test_frac * len(recs)))
        n_val = max(1, round(val_frac * len(recs)))
        held_out += recs[:n_test]
        test |= np.isin(rec, recs[:n_test])
        val |= np.isin(rec, recs[n_test:n_test + n_val])
    return Split(train=~test & ~val, val=val, test=test, test_recordings=held_out)


@dataclass
class TrainResult:
    model: PatchCNN
    val_accuracy: float
    epochs: int


def train(x: npt.NDArray[np.float32], y: npt.NDArray[np.int64], split: Split, seed: int,
          epochs: int = 25, batch: int = 128, lr: float = 1e-3) -> TrainResult:
    torch.manual_seed(seed)
    model = PatchCNN(x.shape[1], x.shape[2])
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    # balance the classes: people outnumber drones
    counts = np.bincount(y[split.train], minlength=len(CLASSES))
    weights = torch.tensor(counts.sum() / (len(CLASSES) * counts), dtype=torch.float32)
    loss_fn = nn.CrossEntropyLoss(weight=weights)
    xt, yt = torch.from_numpy(x[split.train]), torch.from_numpy(y[split.train])
    best_acc, best_state, best_epoch = -1.0, None, 0
    gen = torch.Generator().manual_seed(seed)
    for epoch in range(epochs):
        model.train()
        order = torch.randperm(len(yt), generator=gen)
        for i in range(0, len(order), batch):
            idx = order[i:i + batch]
            opt.zero_grad()
            loss_fn(model(xt[idx]), yt[idx]).backward()
            opt.step()
        acc = accuracy(model, x[split.val], y[split.val])
        if acc > best_acc:
            best_acc, best_epoch = acc, epoch + 1
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
    assert best_state is not None
    model.load_state_dict(best_state)
    return TrainResult(model, best_acc, best_epoch)


def predict(model: nn.Module, x: npt.NDArray[np.float32]) -> npt.NDArray[np.int64]:
    model.eval()
    with torch.no_grad():
        out: npt.NDArray[np.int64] = model(torch.from_numpy(x)).argmax(1).numpy()
    return out


def accuracy(model: nn.Module, x: npt.NDArray[np.float32], y: npt.NDArray[np.int64]) -> float:
    return float((predict(model, x) == y).mean()) if len(y) else float("nan")


def confusion(y_true: npt.NDArray[np.int64], y_pred: npt.NDArray[np.int64]
              ) -> npt.NDArray[np.int64]:
    m = np.zeros((len(CLASSES), len(CLASSES)), dtype=np.int64)
    np.add.at(m, (y_true, y_pred), 1)
    return m


def recall_per_class(m: npt.NDArray[np.int64]) -> dict[str, float]:
    return {c: float(m[i, i] / m[i].sum()) if m[i].sum() else float("nan")
            for i, c in enumerate(CLASSES)}


def to_onnx(model: nn.Module, height: int, width: int, path: Any) -> None:
    model.eval()
    torch.onnx.export(model, (torch.zeros(1, height, width),), str(path),
                      input_names=["patch"], output_names=["logits"],
                      dynamic_axes={"patch": {0: "n"}, "logits": {0: "n"}}, verbose=False)
