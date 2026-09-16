"""
train_classifier.py
--------------------
OPTIONAL UPGRADE: once you've collected real labeled package photos
(even a few hundred, split into folders like data/damaged/ and
data/intact/), run this script to fine-tune a small pretrained CNN
instead of relying on the classical CV heuristic in damage_detector.py.

This uses transfer learning: we take a ResNet18 already trained on
ImageNet (so it already understands edges, textures, shapes) and just
retrain its final layer to answer our yes/no question. This needs far
less data and time than training a CNN from scratch.

Expected folder layout:
    data/
      train/
        damaged/   *.jpg
        intact/    *.jpg
      val/
        damaged/   *.jpg
        intact/    *.jpg

Usage:
    python train_classifier.py --data-dir ./data --epochs 10
"""

import argparse
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import datasets, models, transforms


def build_model() -> nn.Module:
    """Load ResNet18 pretrained on ImageNet and swap the final layer
    for our binary (damaged / intact) classification task."""
    model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)

    # Freeze all the pretrained feature-extraction layers - we only want
    # to train the new final layer, which is fast and needs little data.
    for param in model.parameters():
        param.requires_grad = False

    num_features = model.fc.in_features
    model.fc = nn.Linear(num_features, 2)  # 2 classes: intact, damaged
    return model


def get_dataloaders(data_dir: str, batch_size: int = 16):
    """Standard ImageNet-style preprocessing so it matches what ResNet18
    was originally trained on."""
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225]),
    ])

    train_ds = datasets.ImageFolder(f"{data_dir}/train", transform=transform)
    val_ds = datasets.ImageFolder(f"{data_dir}/val", transform=transform)

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size)

    # train_ds.classes will be ['damaged', 'intact'] (alphabetical) -
    # print it so you can confirm label order matches what you expect
    print("Class order:", train_ds.classes)
    return train_loader, val_loader


def train(model, train_loader, val_loader, epochs: int, device: str):
    criterion = nn.CrossEntropyLoss()
    # Only the new final layer has requires_grad=True, so only it gets trained
    optimizer = torch.optim.Adam(model.fc.parameters(), lr=1e-3)

    model.to(device)
    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)

            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()

        val_acc = evaluate(model, val_loader, device)
        print(f"Epoch {epoch + 1}/{epochs} - loss: {running_loss / len(train_loader):.4f} "
              f"- val accuracy: {val_acc:.2%}")


def evaluate(model, loader, device: str) -> float:
    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            _, predicted = torch.max(outputs, dim=1)
            correct += (predicted == labels).sum().item()
            total += labels.size(0)
    return correct / total if total else 0.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="./data")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--output", default="trained_model.pt")
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Training on: {device}")

    model = build_model()
    train_loader, val_loader = get_dataloaders(args.data_dir)
    train(model, train_loader, val_loader, args.epochs, device)

    torch.save(model.state_dict(), args.output)
    print(f"Saved trained weights to {args.output}")
    print("Next step: write a trained_model.py with a predict(image_bytes) "
          "function that loads these weights, then update the [SWAP POINT] "
          "in damage_detector.py to call it instead of the heuristic.")
